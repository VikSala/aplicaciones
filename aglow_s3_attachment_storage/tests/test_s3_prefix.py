"""Moto-backed tests for the s3_attachment.key_prefix feature.

These tests use an in-memory S3 mock (moto) so no real bucket is ever
contacted, and dummy credentials so no real AWS keys are used.

Acceptance criteria (1:1 with assertions below):
1. Default = legacy behavior (no prefix): object stored at key == store_fname.
2. Prefix applied on write: object at "<prefix>/<store_fname>", DB store_fname
   remains un-prefixed.
3. Read fallback: with prefix set, an object present only at the un-prefixed
   key is still readable.
4. GC isolation (the fix): with prefix set, GC deletes only the prefixed key;
   another instance's un-prefixed object survives.
5. Regression demonstration: with NO prefix, GC deletes the un-prefixed key
   (documents the data-loss the prefix prevents).
"""

from unittest.mock import patch

import boto3
from moto import mock_aws

from odoo.addons.aglow_s3_attachment_storage.models import ir_attachment
from odoo.tests.common import TransactionCase, tagged

BUCKET = "test-bucket"
REGION = "us-east-1"


@tagged("post_install", "-at_install")
class TestS3KeyPrefix(TransactionCase):

    def _configure(self, key_prefix=None):
        """Clear the module-global client cache and set S3 config params.

        Must run inside the moto mock so the boto3 client the module builds
        is created under the active moto backend.
        """
        # Force a fresh boto3 client under this test's moto backend.
        ir_attachment._S3_CLIENT_CACHE.clear()

        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("s3_attachment.bucket", BUCKET)
        ICP.set_param("s3_attachment.access_key_id", "dummy")
        ICP.set_param("s3_attachment.secret_access_key", "dummy")
        ICP.set_param("s3_attachment.region", REGION)
        if key_prefix is None:
            ICP.set_param("s3_attachment.key_prefix", "")
        else:
            ICP.set_param("s3_attachment.key_prefix", key_prefix)

        # Create the bucket with our own client (us-east-1: no LocationConstraint).
        client = boto3.client(
            "s3",
            aws_access_key_id="dummy",
            aws_secret_access_key="dummy",
            region_name=REGION,
        )
        client.create_bucket(Bucket=BUCKET)
        return client

    def _make_s3_attachment(self, data, name="doc.bin"):
        """Create an attachment that routes to S3 and return it."""
        att = self.env["ir.attachment"].create({
            "name": name,
            "res_model": "res.partner",
            "res_id": 1,
            "mimetype": "application/octet-stream",
            "raw": data,
        })
        return att

    def _key_exists(self, client, key):
        try:
            client.head_object(Bucket=BUCKET, Key=key)
            return True
        except client.exceptions.ClientError:
            return False

    # --- Criterion 1 ------------------------------------------------------
    @mock_aws
    def test_1_default_legacy_behavior(self):
        client = self._configure(key_prefix=None)
        data = b"legacy-default-bytes"
        att = self._make_s3_attachment(data, name="c1.bin")
        fname = att.store_fname

        self.assertTrue(fname, "attachment should have a store_fname")
        # Object stored under key exactly equal to store_fname (no prefix).
        self.assertTrue(
            self._key_exists(client, fname),
            "object must exist at un-prefixed key == store_fname",
        )
        # Read back returns original bytes.
        self.assertEqual(
            self.env["ir.attachment"]._file_read(fname), data
        )

    # --- Criterion 2 ------------------------------------------------------
    @mock_aws
    def test_2_prefix_applied_on_write(self):
        client = self._configure(key_prefix="inst-a")
        data = b"prefixed-write-bytes"
        att = self._make_s3_attachment(data, name="c2.bin")
        fname = att.store_fname

        # DB store_fname stays un-prefixed.
        self.assertFalse(
            fname.startswith("inst-a/"),
            "store_fname in DB must NOT carry the prefix",
        )
        # Object stored at prefixed key.
        self.assertTrue(
            self._key_exists(client, "inst-a/%s" % fname),
            "object must exist at prefixed key inst-a/<store_fname>",
        )
        # Un-prefixed key must NOT exist.
        self.assertFalse(
            self._key_exists(client, fname),
            "object must NOT exist at the un-prefixed key",
        )
        # Read back returns original bytes.
        self.assertEqual(
            self.env["ir.attachment"]._file_read(fname), data
        )

    # --- Criterion 3 ------------------------------------------------------
    @mock_aws
    def test_3_read_fallback_to_unprefixed(self):
        client = self._configure(key_prefix="inst-a")
        legacy_fname = "zz/legacyobject"
        client.put_object(
            Bucket=BUCKET, Key=legacy_fname, Body=b"legacy-bytes"
        )
        # Only the un-prefixed key exists; read must fall back to it.
        self.assertEqual(
            self.env["ir.attachment"]._file_read(legacy_fname),
            b"legacy-bytes",
        )

    # --- Criterion 4 ------------------------------------------------------
    @mock_aws
    def test_4_gc_isolation_with_prefix(self):
        client = self._configure(key_prefix="inst-a")
        data = b"gc-isolation-bytes"
        att = self._make_s3_attachment(data, name="c4.bin")
        K = att.store_fname

        # Instance-A's own copy lives at the prefixed key (written on create).
        self.assertTrue(self._key_exists(client, "inst-a/%s" % K))
        # Simulate ANOTHER instance's shared object at the un-prefixed key.
        client.put_object(
            Bucket=BUCKET, Key=K, Body=b"other-instance-bytes"
        )

        # Orphan K in THIS database: unlink adds its store_fname to checklist.
        att.unlink()

        with patch.object(self.env.cr, "commit", lambda: None):
            self.env["ir.attachment"]._gc_file_store_s3()

        # The prefixed (own) key is gone.
        self.assertFalse(
            self._key_exists(client, "inst-a/%s" % K),
            "GC must delete instance-A's own prefixed key",
        )
        # The other instance's un-prefixed object SURVIVES.
        self.assertTrue(
            self._key_exists(client, K),
            "GC must NOT delete the other instance's un-prefixed key",
        )

    # --- Criterion 5 ------------------------------------------------------
    @mock_aws
    def test_5_regression_no_prefix_destroys_shared(self):
        client = self._configure(key_prefix=None)
        data = b"gc-noprefix-bytes"
        att = self._make_s3_attachment(data, name="c5.bin")
        K = att.store_fname

        # With no prefix the attachment's own write already lives at K;
        # this represents the "shared" object in a shared bucket.
        self.assertTrue(self._key_exists(client, K))

        att.unlink()

        with patch.object(self.env.cr, "commit", lambda: None):
            self.env["ir.attachment"]._gc_file_store_s3()

        # Without a prefix, GC destroys the un-prefixed (shared) object.
        self.assertFalse(
            self._key_exists(client, K),
            "no-prefix GC deletes the un-prefixed key (data-loss the "
            "prefix prevents)",
        )
