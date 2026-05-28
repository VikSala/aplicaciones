import logging
import os
import random
import time

import boto3
from botocore.exceptions import ClientError

from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.tools import config

_logger = logging.getLogger(__name__)

S3_RETRY_MAX = 3
S3_RETRY_BASE_DELAY = 2  # seconds
S3_RETRY_MAX_DELAY = 10  # seconds

# Odoo SH sets ODOO_STAGE to 'production', 'staging', or 'dev'
IS_PRODUCTION = os.environ.get("ODOO_STAGE", "production") == "production"


# Mimetypes that should always stay on local disk (web assets, icons)
_S3_EXCLUDED_MIMETYPES = frozenset({
    "text/css",
    "text/scss",
    "text/less",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "image/x-icon",
})

# Models whose attachments should always stay on local disk. Menu icons are
# read on every session_info() call, so round-tripping to S3 adds seconds to
# every page load.
_S3_EXCLUDED_MODELS = frozenset({
    "ir.ui.menu",
    "ir.ui.view",
})

# Module-level boto3 client cache keyed on the full credential tuple so that
# credential rotation invalidates stale entries automatically. Boto3 clients
# are thread-safe, so sharing across workers and threads is fine.
_S3_CLIENT_CACHE = {}


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _should_use_s3(self):
        """Determine whether this attachment should be stored in S3.

        Returns False for web assets, system resources, and attachments
        without a res_model (typically editor uploads and static assets).
        """
        self.ensure_one()
        if self.mimetype in _S3_EXCLUDED_MIMETYPES:
            return False
        if self.res_model in _S3_EXCLUDED_MODELS:
            return False
        if not self.res_model:
            return False
        return True

    @api.model_create_multi
    def create(self, vals_list):
        """Set S3 context based on attachment values during create."""
        for vals in vals_list:
            mimetype = vals.get("mimetype", "")
            res_model = vals.get("res_model", "")
            use_s3 = (
                bool(res_model)
                and res_model not in _S3_EXCLUDED_MODELS
                and mimetype not in _S3_EXCLUDED_MIMETYPES
            )
            if use_s3 and "_use_s3_storage" not in self.env.context:
                self = self.with_context(_use_s3_storage=True)
                break
        return super().create(vals_list)

    def _set_attachment_data(self, asbytes):
        """Override to pass S3 storage context per attachment."""
        for attach in self:
            use_s3 = attach._should_use_s3()
            super(
                IrAttachment, attach.with_context(_use_s3_storage=use_s3)
            )._set_attachment_data(asbytes)

    @api.model
    def _get_s3_credentials(self):
        """Retrieve S3 configuration from system parameters, falling back to
        environment variables for backward compatibility."""
        ICP = self.env["ir.config_parameter"].sudo()
        bucket = ICP.get_param("s3_attachment.bucket") or os.environ.get(
            "S3_ATTACHMENT_MANAGER_BUCKET"
        )
        access_key = ICP.get_param("s3_attachment.access_key_id") or os.environ.get(
            "S3_ATTACHMENT_MANAGER_ACCESS_KEY_ID"
        )
        secret_key = ICP.get_param(
            "s3_attachment.secret_access_key"
        ) or os.environ.get("S3_ATTACHMENT_MANAGER_SECRET_ACCESS_KEY")
        endpoint_url = ICP.get_param("s3_attachment.endpoint_url") or os.environ.get(
            "S3_ATTACHMENT_MANAGER_ENDPOINT_URL"
        )
        region = ICP.get_param("s3_attachment.region") or os.environ.get(
            "S3_ATTACHMENT_MANAGER_REGION"
        )

        if not bucket or not access_key or not secret_key:
            raise ValidationError(
                "S3 credentials not configured. Set them in Settings > General "
                "Settings > S3 Attachment Storage, or via environment variables."
            )

        return {
            "bucket": bucket,
            "access_key_id": access_key,
            "secret_access_key": secret_key,
            "endpoint_url": endpoint_url,
            "region": region,
        }

    @api.model
    def _get_s3_client(self):
        """Return a configured boto3 S3 client and the bucket name.

        Clients are cached at module scope keyed on the full credential
        tuple so that credential rotation transparently invalidates the
        entry. Boto3 clients are thread-safe.
        """
        creds = self._get_s3_credentials()
        cache_key = (
            creds["access_key_id"],
            creds["secret_access_key"],
            creds.get("endpoint_url"),
            creds.get("region"),
            creds["bucket"],
        )
        cached = _S3_CLIENT_CACHE.get(cache_key)
        if cached is not None:
            return cached
        client_kwargs = {
            "aws_access_key_id": creds["access_key_id"],
            "aws_secret_access_key": creds["secret_access_key"],
        }
        if creds.get("endpoint_url"):
            client_kwargs["endpoint_url"] = creds["endpoint_url"]
        if creds.get("region"):
            client_kwargs["region_name"] = creds["region"]
        client = boto3.client("s3", **client_kwargs)
        entry = (client, creds["bucket"])
        _S3_CLIENT_CACHE[cache_key] = entry
        return entry

    @api.model
    def _is_s3_write_enabled(self):
        """Check if S3 writes are allowed in the current environment."""
        if not IS_PRODUCTION:
            production_only = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("s3_attachment.production_only", "False")
            )
            if production_only == "True":
                return False
        return True

    def action_verify_and_cleanup_s3(self):
        """Verify attachment exists in S3, then delete the local copy.

        Intended for use as a server action on individual attachment records.
        """
        self.ensure_one()
        s3, s3_bucket = self._get_s3_client()
        fname = self.store_fname
        if not fname:
            raise ValidationError("This attachment has no store_fname.")

        # Verify file exists in S3
        s3.head_object(Bucket=s3_bucket, Key=fname)

        # Delete local copy if it exists
        full_path = self._full_path(fname)
        if os.path.exists(full_path):
            os.remove(full_path)
            _logger.info(
                "Verified and cleaned local file for attachment %d: %s",
                self.id,
                fname,
            )
        else:
            _logger.info(
                "Attachment %d verified in S3, no local file to clean: %s",
                self.id,
                fname,
            )

    def action_repair_local_excluded_attachments(self):
        """Rehydrate attachments for S3-excluded res_models back to local disk.

        Idempotent: skips files already present locally. Intended for
        one-shot recovery when the cleanup cron has removed local copies
        of attachments that are now in _S3_EXCLUDED_MODELS (e.g. menu
        icons), and every session_info() is paying an S3 round-trip for
        them.

        Leaves the S3 copies in place — they are still referenced by the
        ir.attachment rows, so the GC cron won't touch them, and keeping
        them is harmless belt-and-suspenders.
        """
        try:
            s3, s3_bucket = self._get_s3_client()
        except ValidationError as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "S3 Repair Failed",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }

        attachments = self.sudo().search([
            ("res_model", "in", list(_S3_EXCLUDED_MODELS)),
            ("type", "=", "binary"),
            ("store_fname", "!=", False),
        ])

        repaired = 0
        skipped = 0
        failed = 0
        for att in attachments:
            fname = att.store_fname
            full_path = att._full_path(fname)
            if os.path.isfile(full_path):
                skipped += 1
                continue
            try:
                response = s3.get_object(Bucket=s3_bucket, Key=fname)
                data = response["Body"].read()
            except ClientError as e:
                _logger.warning(
                    "S3 repair: attachment %d (%s) not fetchable from S3: %s",
                    att.id, fname, e,
                )
                failed += 1
                continue
            except Exception as e:
                _logger.exception(
                    "S3 repair: unexpected error fetching attachment %d: %s",
                    att.id, e,
                )
                failed += 1
                continue

            dirname = os.path.dirname(full_path)
            if not os.path.isdir(dirname):
                os.makedirs(dirname, exist_ok=True)
            tmp_path = full_path + ".tmp"
            try:
                with open(tmp_path, "wb") as f:
                    f.write(data)
                os.replace(tmp_path, full_path)
                repaired += 1
            except (IOError, OSError) as e:
                _logger.exception(
                    "S3 repair: failed to write local file for attachment "
                    "%d: %s",
                    att.id, e,
                )
                failed += 1
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

        _logger.info(
            "S3 repair complete: %d rehydrated, %d already local, %d failed.",
            repaired, skipped, failed,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "S3 Repair Complete",
                "message": (
                    "Rehydrated %d file(s), %d already local, %d failed. "
                    "See server log for details."
                ) % (repaired, skipped, failed),
                "type": "warning" if failed else "success",
                "sticky": bool(failed),
            },
        }

    @staticmethod
    def _s3_backoff_delay(attempt):
        """Calculate sleep time for exponential backoff with jitter."""
        delay = S3_RETRY_BASE_DELAY * 2**attempt
        return min(S3_RETRY_MAX_DELAY, delay * (1 + random.uniform(-0.1, 0.1)))

    @api.model
    def _store_file_write(self, fname, bin_data):
        """Write binary data to an S3 bucket with retry logic."""
        s3, s3_bucket = self._get_s3_client()

        for attempt in range(S3_RETRY_MAX):
            try:
                s3.put_object(Bucket=s3_bucket, Key=fname, Body=bin_data)
                return fname
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                _logger.exception(
                    "Error writing to S3 (attempt %d): %s - %s",
                    attempt + 1,
                    error_code,
                    e,
                )
            except Exception as e:
                _logger.exception(
                    "Unexpected error writing to S3 (attempt %d): %s",
                    attempt + 1,
                    e,
                )

            if attempt < S3_RETRY_MAX - 1:
                time.sleep(self._s3_backoff_delay(attempt))
            else:
                return False

    @api.model
    def _file_read(self, fname):
        """Read a file from local disk first, then fall back to S3.

        Local-first avoids an S3 round-trip for web assets and any file
        that still has a local copy.  We check locally with a silent
        os.path read instead of super() to avoid noisy base-class
        traceback logging for files that only exist in S3.

        Boto3 already retries transient failures internally, so we make
        a single attempt here — wrapping it in our own retry loop would
        amplify tail latency without adding reliability.
        """
        full_path = self._full_path(fname)
        if os.path.isfile(full_path):
            try:
                with open(full_path, "rb") as f:
                    return f.read()
            except (IOError, OSError):
                pass

        try:
            s3, s3_bucket = self._get_s3_client()
        except ValidationError:
            return b""

        try:
            response = s3.get_object(Bucket=s3_bucket, Key=fname)
            return response["Body"].read()
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "NoSuchKey":
                return b""
            _logger.exception(
                "Error reading from S3: %s - %s", error_code, e
            )
        except Exception as e:
            _logger.exception("Unexpected error reading from S3: %s", e)
        return b""

    def _to_http_stream(self):
        """Override para Odoo 18.
        Si Odoo va a generar un stream de un archivo que está en S3
        pero no existe en el filestore local de Docker, lo descargamos
        justo antes de que ejecute os.stat().
        """
        self.ensure_one()
        if self.type == 'binary' and self.store_fname and self._should_use_s3():
            full_path = self._full_path(self.store_fname)
            
            # Si el archivo no está físicamente en el contenedor
            if not os.path.isfile(full_path):
                try:
                    s3, s3_bucket = self._get_s3_client()
                    response = s3.get_object(Bucket=s3_bucket, Key=self.store_fname)
                    bin_data = response["Body"].read()
                    
                    # Asegurar que el árbol de directorios local exista (ej: /3a/)
                    dirname = os.path.dirname(full_path)
                    if not os.path.isdir(dirname):
                        os.makedirs(dirname, exist_ok=True)
                        
                    # Escribir el archivo en el filestore local
                    tmp_path = full_path + ".tmp"
                    with open(tmp_path, "wb") as f:
                        f.write(bin_data)
                    os.replace(tmp_path, full_path)
                except Exception as e:
                    _logger.error("S3: Error al descargar archivo para stream HTTP: %s", e)

        return super(IrAttachment, self)._to_http_stream()

    @api.model
    def _file_write(self, bin_value, checksum):
        """Write a file to S3 or local disk based on attachment context.

        Business documents go to S3; web assets and system resources
        stay on local disk.  Falls back to local on S3 failure.
        """
        if not self.env.context.get("_use_s3_storage", False):
            return super()._file_write(bin_value, checksum)
        if not self._is_s3_write_enabled():
            return super()._file_write(bin_value, checksum)
        try:
            self._get_s3_client()
        except ValidationError:
            return super()._file_write(bin_value, checksum)

        fname, full_path = self._get_path(bin_value, checksum)
        res = self._store_file_write(fname, bin_value)
        if not res:
            fname = super()._file_write(bin_value, checksum)
            _logger.warning("Attachment stored locally due to S3 upload failure.")
        return fname

    @api.model
    def _file_delete(self, fname):
        """Mark file for S3 deletion via local GC checklist.

        We do NOT delete from S3 here because multiple ir.attachment
        records can share the same store_fname (content-addressed).
        Immediate deletion would orphan siblings.  Instead we defer to
        the base _file_delete which adds the fname to a GC checklist;
        the actual S3 removal happens in _gc_file_store_s3.
        """
        return super()._file_delete(fname)

    @api.model
    def _gc_file_store_s3(self):
        """Garbage-collect S3 objects that are no longer referenced.

        Mirrors the logic of base _gc_file_store but for S3 keys.
        Only deletes an S3 object when zero ir.attachment rows still
        reference the corresponding store_fname.
        """
        if not self._is_s3_write_enabled():
            return

        try:
            s3, s3_bucket = self._get_s3_client()
        except ValidationError:
            _logger.warning("S3 credentials not configured. Skipping S3 GC.")
            return

        cr = self._cr
        cr.commit()

        try:
            cr.execute("SET LOCAL lock_timeout TO '10s'")
            cr.execute("LOCK ir_attachment IN SHARE MODE")
        except Exception:
            _logger.info("Could not acquire lock for S3 GC, will retry later.")
            cr.rollback()
            return

        # Collect fnames from the local GC checklist
        checklist = {}
        checklist_dir = self._full_path('checklist')
        if not os.path.isdir(checklist_dir):
            cr.commit()
            return

        for dirpath, _, filenames in os.walk(checklist_dir):
            dirname = os.path.basename(dirpath)
            for filename in filenames:
                fname = "%s/%s" % (dirname, filename)
                checklist[fname] = os.path.join(dirpath, filename)

        if not checklist:
            cr.commit()
            return

        removed = 0
        for names in cr.split_for_in_conditions(checklist):
            cr.execute(
                "SELECT store_fname FROM ir_attachment "
                "WHERE store_fname IN %s",
                [names],
            )
            whitelist = set(row[0] for row in cr.fetchall())

            for fname in names:
                if fname not in whitelist:
                    for attempt in range(S3_RETRY_MAX):
                        try:
                            s3.delete_object(Bucket=s3_bucket, Key=fname)
                            _logger.debug(
                                "S3 GC deleted '%s' from bucket '%s'.",
                                fname,
                                s3_bucket,
                            )
                            removed += 1
                            break
                        except ClientError as e:
                            error_code = e.response["Error"]["Code"]
                            if error_code == "NoSuchKey":
                                break
                            _logger.exception(
                                "S3 GC error deleting '%s' (attempt %d): %s",
                                fname,
                                attempt + 1,
                                e,
                            )
                        except Exception as e:
                            _logger.exception(
                                "S3 GC unexpected error deleting '%s' "
                                "(attempt %d): %s",
                                fname,
                                attempt + 1,
                                e,
                            )

                        if attempt < S3_RETRY_MAX - 1:
                            time.sleep(self._s3_backoff_delay(attempt))

        cr.commit()
        _logger.info(
            "S3 filestore GC: %d checked, %d removed from S3.",
            len(checklist),
            removed,
        )

    def _cron_migrate_filestore_to_s3(self):
        """Migrate existing filestore attachments to S3 in batches.

        Triggered manually from Scheduled Actions. Tracks progress via
        ir.config_parameter and self-reschedules until all attachments
        are migrated.
        """
        ICP = self.env["ir.config_parameter"].sudo()

        try:
            self._get_s3_client()
        except ValidationError:
            _logger.error("S3 credentials not configured. Cannot run migration.")
            return

        # Initialize max_id on first run
        max_id = int(ICP.get_param("s3_attachment.migration_max_id", 0))
        if not max_id:
            last = (
                self.env["ir.attachment"]
                .sudo()
                .search([], limit=1, order="id desc")
            )
            max_id = last.id if last else 0
            if not max_id:
                _logger.info("No attachments to migrate.")
                return
            ICP.set_param("s3_attachment.migration_max_id", str(max_id))

        min_id = int(ICP.get_param("s3_attachment.migration_min_id", 0))

        # Time limit: use half of cron time limit to leave room for cleanup
        limit_time = config.get("limit_time_real_cron") or config.get(
            "limit_time_real", 120
        )
        if limit_time <= 0:
            limit_time = 120
        end_time = time.monotonic() + (limit_time // 2)

        batch_size = int(ICP.get_param("s3_attachment.migration_batch_size", 100))
        migrated = 0
        skipped_dup = 0
        failed = 0
        uploaded_fnames = set()
        while True:
            attachments = (
                self.env["ir.attachment"]
                .sudo()
                .search(
                    [
                        ("id", ">", min_id),
                        ("id", "<=", max_id),
                        ("type", "=", "binary"),
                        ("store_fname", "!=", False),
                    ],
                    limit=batch_size,
                    order="id asc",
                )
            )

            if not attachments:
                ICP.set_param("s3_attachment.migration_min_id", str(max_id))
                self.env.cr.commit()
                _logger.info(
                    "S3 migration complete. Migrated %d, skipped %d "
                    "duplicates, failed %d in this run.",
                    migrated,
                    skipped_dup,
                    failed,
                )
                return

            for attachment in attachments:
                # Skip if we already uploaded this file in this run
                if attachment.store_fname in uploaded_fnames:
                    skipped_dup += 1
                    continue

                # Skip web assets and system resources
                if not attachment._should_use_s3():
                    continue

                try:
                    # Read from LOCAL filesystem (bypass our S3 override)
                    bin_data = super(IrAttachment, self)._file_read(
                        attachment.store_fname
                    )
                    if bin_data:
                        result = self._store_file_write(
                            attachment.store_fname, bin_data
                        )
                        if result:
                            migrated += 1
                            uploaded_fnames.add(attachment.store_fname)
                        else:
                            _logger.warning(
                                "Failed to upload attachment %d to S3.",
                                attachment.id,
                            )
                            failed += 1
                    else:
                        _logger.warning(
                            "Attachment %d has empty file data, skipping.",
                            attachment.id,
                        )
                except Exception:
                    _logger.exception(
                        "Error migrating attachment %d.", attachment.id
                    )
                    failed += 1

            # Commit progress after each batch
            min_id = attachments[-1].id
            ICP.set_param("s3_attachment.migration_min_id", str(min_id))
            self.env.cr.commit()
            _logger.info(
                "S3 migration batch committed. Migrated %d so far "
                "(last id: %d).",
                migrated,
                min_id,
            )

            if time.monotonic() > end_time:
                break

        _logger.info(
            "S3 migration paused after %d migrated, %d duplicates skipped, "
            "%d failed. Will resume on next cron cycle.",
            migrated,
            skipped_dup,
            failed,
        )

    def _cron_cleanup_local_filestore(self):
        """Phase 2: Remove local files that have been verified in S3.

        Can run alongside Phase 1 — cleans up everything Phase 1 has
        processed so far. Each run picks up new Phase 1 progress
        automatically.
        """
        ICP = self.env["ir.config_parameter"].sudo()

        try:
            s3, s3_bucket = self._get_s3_client()
        except ValidationError:
            _logger.error("S3 credentials not configured. Cannot run cleanup.")
            return

        # Phase 2 cleans up to wherever Phase 1 has reached so far.
        # migration_min_id is the high-water mark of Phase 1 progress.
        migration_min = int(ICP.get_param("s3_attachment.migration_min_id", 0))
        if not migration_min:
            _logger.error(
                "Phase 1 migration has not started yet. "
                "Run the migration cron first."
            )
            return

        # cleanup_max advances each run to match Phase 1 progress
        cleanup_max = migration_min

        cleanup_min = int(ICP.get_param("s3_attachment.cleanup_min_id", 0))

        if cleanup_min >= cleanup_max:
            _logger.info(
                "S3 cleanup is caught up with Phase 1 (up to id %d). "
                "Nothing to clean.",
                cleanup_max,
            )
            return

        # Time limit
        limit_time = config.get("limit_time_real_cron") or config.get(
            "limit_time_real", 120
        )
        if limit_time <= 0:
            limit_time = 120
        end_time = time.monotonic() + (limit_time // 2)

        batch_size = int(ICP.get_param("s3_attachment.migration_batch_size", 100))
        cleaned = 0
        skipped_dup = 0
        failed = 0
        verified_fnames = set()
        while True:
            attachments = (
                self.env["ir.attachment"]
                .sudo()
                .search(
                    [
                        ("id", ">", cleanup_min),
                        ("id", "<=", cleanup_max),
                        ("type", "=", "binary"),
                        ("store_fname", "!=", False),
                    ],
                    limit=batch_size,
                    order="id asc",
                )
            )

            if not attachments:
                ICP.set_param("s3_attachment.cleanup_min_id", str(cleanup_max))
                self.env.cr.commit()
                _logger.info(
                    "S3 cleanup complete. Deleted %d local files, "
                    "skipped %d duplicates, failed %d in this run.",
                    cleaned,
                    skipped_dup,
                    failed,
                )
                return

            for attachment in attachments:
                # Defensive: never delete local copies of attachments that
                # the current module policy keeps on local disk.
                if not attachment._should_use_s3():
                    continue

                fname = attachment.store_fname

                # Skip if we already verified and cleaned this file
                if fname in verified_fnames:
                    skipped_dup += 1
                    continue

                full_path = self._full_path(fname)

                # Skip if local file doesn't exist (already cleaned)
                if not os.path.exists(full_path):
                    verified_fnames.add(fname)
                    continue

                try:
                    # Verify the file exists in S3 (HEAD is cheaper than GET)
                    s3.head_object(Bucket=s3_bucket, Key=fname)

                    # S3 has it — safe to delete locally
                    os.remove(full_path)
                    cleaned += 1
                    verified_fnames.add(fname)
                except ClientError as e:
                    error_code = e.response["Error"]["Code"]
                    if error_code in ("404", "NoSuchKey"):
                        _logger.warning(
                            "Attachment %d (%s) NOT found in S3 — keeping "
                            "local copy.",
                            attachment.id,
                            fname,
                        )
                    else:
                        _logger.exception(
                            "Error verifying attachment %d in S3: %s",
                            attachment.id,
                            e,
                        )
                    failed += 1
                except Exception:
                    _logger.exception(
                        "Error cleaning up attachment %d.", attachment.id
                    )
                    failed += 1

            # Commit progress after each batch
            cleanup_min = attachments[-1].id
            ICP.set_param("s3_attachment.cleanup_min_id", str(cleanup_min))
            self.env.cr.commit()
            _logger.info(
                "S3 cleanup batch committed. Deleted %d so far "
                "(last id: %d).",
                cleaned,
                cleanup_min,
            )

            if time.monotonic() > end_time:
                break

        _logger.info(
            "S3 cleanup paused after %d deleted, %d duplicates skipped, "
            "%d failed. Will resume on next cron cycle.",
            cleaned,
            skipped_dup,
            failed,
        )
