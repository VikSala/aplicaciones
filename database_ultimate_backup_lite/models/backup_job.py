# -*- coding: utf-8 -*-

import os
import datetime
import re
import subprocess
import tempfile
import json
import glob
import shutil
import zipfile
import logging

import odoo.release
import odoo.sql_db
from odoo import models, fields, api, tools
from odoo.exceptions import UserError, AccessDenied
from odoo.tools import osutil
from odoo.tools.misc import exec_pg_environ, find_pg_tool

_logger = logging.getLogger(__name__)


class BackupJob(models.Model):
    """
    Backup job model representing individual backup executions.
    
    This model tracks the execution of backup operations, including
    progress, results, and detailed logging.
    """
    _name = 'backup.job'
    _description = 'Backup Job'
    _order = 'start_time desc, id desc'
    _rec_name = 'display_name'
    
    # Basic information
    config_id = fields.Many2one(
        'backup.config',
        string='Backup Configuration',
        required=True,
        ondelete='cascade'
    )
    database_name = fields.Char(
        string='Database Name',
        required=True,
        help='Name of the database being backed up'
    )
    backup_format = fields.Selection([
        ('zip', 'ZIP Archive'),
        ('dump', 'PostgreSQL Dump'),
    ], string='Backup Format', required=True)
    database_dump_format = fields.Selection([
        ('dump', 'PostgreSQL Custom Dump (.dump)'),
        ('sql', 'Plain SQL Dump (.sql)'),
    ], string='Database Dump Type', required=True, default='dump',
       help='Database dump type used for the backup: PostgreSQL custom format or plain SQL.')
    zip_content_mode = fields.Selection([
        ('manifest', 'Modules JSON / manifest.json'),
        ('odoo0_addons', 'Odoo project addons folder'),
    ], string='ZIP Extra Content', default='manifest',
       help='Extra content included inside ZIP backups.')
    odoo0_root_path = fields.Char(
        string='Odoo Project Root Path',
        help='Optional root folder of the Odoo project structure used to copy the addons folder. If empty, it will be auto-detected.'
    )
    is_manual = fields.Boolean(
        string='Manual Backup',
        default=False,
        help='True if this backup was triggered manually by a user'
    )
    
    # Status and timing
    status = fields.Selection([
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Status', required=True, default='pending')
    start_time = fields.Datetime(
        string='Start Time',
        required=True,
        default=fields.Datetime.now
    )
    end_time = fields.Datetime(
        string='End Time'
    )
    duration = fields.Float(
        string='Duration (seconds)',
        compute='_compute_duration',
        store=True,
        help='Total backup duration in seconds'
    )
    
    # File information
    backup_filename = fields.Char(
        string='Backup Filename',
        help='Name of the generated backup file'
    )
    backup_size_mb = fields.Integer(
        string='Backup Size (MB)',
        help='Size of the backup file in megabytes'
    )
    backup_size_human = fields.Char(
        string='Backup Size',
        compute='_compute_backup_size_human',
        help='Human-readable backup file size'
    )
    
    # Results and logging
    backup_details = fields.Text(
        string='Backup Details',
        help='Detailed information about the backup process'
    )
    error_message = fields.Text(
        string='Error Message',
        help='Error message if backup failed'
    )
    log_entries = fields.Text(
        string='Log Entries',
        help='Detailed log of backup process'
    )
    
    # Provider results
    provider_results = fields.Text(
        string='Provider Results',
        help='JSON-encoded results from storage providers'
    )
    
    # Verification
    verification_status = fields.Selection([
        ('not_verified', 'Not Verified'),
        ('verified', 'Verified'),
        ('failed', 'Verification Failed'),
    ], string='Verification Status', default='not_verified')
    verification_details = fields.Text(
        string='Verification Details'
    )
    
    # Computed fields
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )
    
    @api.depends('config_id.name', 'start_time', 'status')
    def _compute_display_name(self):
        """Compute display name for backup job."""
        for record in self:
            if record.config_id and record.start_time:
                record.display_name = f"{record.config_id.name} - {record.start_time.strftime('%Y-%m-%d %H:%M')}"
            else:
                record.display_name = f"Backup Job #{record.id}"
    
    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        """Compute backup duration."""
        for record in self:
            if record.start_time and record.end_time:
                delta = record.end_time - record.start_time
                record.duration = delta.total_seconds()
            else:
                record.duration = 0.0

    @api.depends('backup_size_mb')
    def _compute_backup_size_human(self):
        """Compute human-readable backup size."""
        for record in self:
            if record.backup_size_mb:
                # Convert MB back to bytes for human_size display
                size_bytes = record.backup_size_mb * 1024 * 1024
                record.backup_size_human = tools.human_size(size_bytes)
            else:
                record.backup_size_human = ''
    
    def _process_backup(self):
        """
        Process the backup job.
        
        This is the main method that orchestrates the entire backup process.
        """
        self.ensure_one()
        
        try:
            self._log("Starting backup process")
            
            # Generate backup filename
            backup_filename = self._generate_backup_filename()
            self.backup_filename = backup_filename
            
            # Create backup file
            backup_file_path = self._create_backup_file()

            # Get backup file size in MB
            size_bytes = os.path.getsize(backup_file_path)
            self.backup_size_mb = int(size_bytes / (1024 * 1024))  # Convert bytes to MB
            self._log(f"Backup file created: {backup_file_path} ({tools.human_size(size_bytes)})")

            # Verify backup integrity if enabled
            if self.config_id.verify_backups:
                self._verify_backup_integrity(backup_file_path)
            
            # Upload to storage providers
            provider_results = self._upload_to_providers(backup_file_path)
            self.provider_results = self._serialize_provider_results(provider_results)
            
            # Clean up local backup file
            try:
                os.remove(backup_file_path)
                self._log("Local backup file cleaned up")
            except Exception as e:
                self._log(f"Warning: Failed to clean up local backup file: {e}")
            
            # Determine final status
            successful_uploads = sum(1 for r in provider_results.values() if r.get('success'))
            total_providers = len(self.config_id.all_providers)
            
            if successful_uploads == 0:
                # All uploads failed
                self.status = 'error'
                self.error_message = "All storage provider uploads failed"
                success = False
            elif successful_uploads < total_providers:
                # Some uploads failed
                self.status = 'warning'
                self.error_message = f"Only {successful_uploads}/{total_providers} provider uploads succeeded"
                success = True  # Partial success
            else:
                # All uploads succeeded
                self.status = 'success'
                success = True
            
            self.end_time = fields.Datetime.now()
            self._log(f"Backup process completed with status: {self.status}")
            
            return {
                'success': success,
                'message': self.error_message or 'Backup completed successfully',
                'backup_job': self,
                'provider_results': provider_results
            }
        except Exception as e:
            self.status = 'error'
            self.end_time = fields.Datetime.now()
            self.error_message = str(e)
            self._log(f"Backup process failed: {e}")
            
            return {
                'success': False,
                'message': str(e),
                'backup_job': self
            }
    
    def _generate_backup_filename(self):
        """Generate backup filename based on template."""
        template = self.config_id.backup_name_template or '{database}_{timestamp}.{format}'
        
        # Prepare template variables
        timestamp = datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
        effective_format = 'zip' if self.backup_format == 'zip' else self.database_dump_format
        variables = {
            'database': self.database_name,
            'timestamp': timestamp,
            'format': effective_format,
            'config': self.config_id.name,
        }
        
        # Replace variables in template
        filename = template.format(**variables)
        
        # Sanitize filename
        filename = self._sanitize_filename(filename)
        
        return filename
    
    def _sanitize_filename(self, filename):
        """Sanitize filename to be safe for all filesystems."""
        # Remove or replace invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove multiple consecutive underscores
        filename = re.sub(r'_+', '_', filename)
        # Trim underscores from ends
        filename = filename.strip('_')
        return filename
    
    def _create_backup_file(self):
        """Create the actual backup file."""
        self._log(f"Creating {self.backup_format.upper()} backup of database: {self.database_name}")
        
        # Create temporary file
        temp_dir = tempfile.mkdtemp(prefix='odoo_backup_')
        backup_file_path = os.path.join(temp_dir, self.backup_filename)
        
        try:
            with open(backup_file_path, 'wb') as backup_file:
                self._create_database_dump(backup_file)
            
            self._log(f"Backup file created successfully: {backup_file_path}")
            return backup_file_path
        except Exception as e:
            # Clean up temp directory on error
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
            raise UserError(f"Failed to create backup file: {e}")
    
    def _create_database_dump(self, stream):
        """
        Create database dump.

        Uses an internal dump implementation that replicates Odoo's
        ``odoo.service.db.dump_db`` logic without the
        ``@check_db_management_enabled`` decorator.  This allows backups
        to work even when ``list_db = False`` is set in odoo.conf.
        """
        # Security check - ensure we're running from the backup system or manual backup
        cron_user = self.env.ref('database_ultimate_backup_lite.backup_cron').user_id
        is_cron_user = self.env.user.id == cron_user.id
        is_manual_backup = self.is_manual

        if not is_cron_user and not is_manual_backup:
            raise AccessDenied("Database dumps can only be created by the backup system or as manual backups")

        self._log(f"Creating {self.backup_format} dump of database: {self.database_name}")

        try:
            self._dump_db(self.database_name, stream, self.backup_format, self.database_dump_format)
            self._log("Database dump created successfully")
        except Exception as e:
            self._log(f"Database dump failed: {str(e)}")
            raise UserError(f"Database backup failed: {str(e)}")

    # ------------------------------------------------------------------
    # Internal dump helpers (mirror odoo.service.db without decorator)
    # ------------------------------------------------------------------

    def _dump_db_manifest(self, cr):
        """Generate the manifest dict for a ZIP backup.

        Replicates ``odoo.service.db.dump_db_manifest`` so that we are
        not affected by the ``@check_db_management_enabled`` decorator.
        """
        pg_version = "%d.%d" % divmod(cr._obj.connection.server_version / 100, 100)
        cr.execute("SELECT name, latest_version FROM ir_module_module WHERE state = 'installed'")
        modules = dict(cr.fetchall())
        return {
            'odoo_dump': '1',
            'db_name': cr.dbname,
            'version': odoo.release.version,
            'version_info': odoo.release.version_info,
            'major_version': odoo.release.major_version,
            'pg_version': pg_version,
            'modules': modules,
        }

    def _dump_db(self, db_name, stream, backup_format='zip', database_dump_format='dump'):
        """Dump *db_name* into the file-like *stream*.

        This is a faithful copy of ``odoo.service.db.dump_db`` **without**
        the ``@check_db_management_enabled`` decorator so that backups
        work regardless of the ``list_db`` setting.
        """
        _logger.info(
            'DUMP DB: %s format %s with filestore', db_name, backup_format,
        )

        cmd = [find_pg_tool('pg_dump'), '--no-owner', db_name]
        env = exec_pg_environ()

        if backup_format == 'zip':
            with tempfile.TemporaryDirectory() as dump_dir:
                # Copy filestore
                filestore = odoo.tools.config.filestore(db_name)
                if os.path.exists(filestore):
                    shutil.copytree(filestore, os.path.join(dump_dir, 'filestore'))

                # Extra ZIP content: either the standard Odoo manifest JSON or
                # the addons folder from the user's detected Odoo project structure.
                if self.zip_content_mode == 'odoo0_addons':
                    self._copy_odoo_project_folder(dump_dir)
                else:
                    with open(os.path.join(dump_dir, 'manifest.json'), 'w') as fh:
                        db = odoo.sql_db.db_connect(db_name)
                        with db.cursor() as cr:
                            json.dump(self._dump_db_manifest(cr), fh, indent=4)

                # Run pg_dump in the selected database dump format.
                dump_filename = 'dump.sql' if database_dump_format == 'sql' else 'dump.dump'
                dump_path = os.path.join(dump_dir, dump_filename)
                dump_cmd = list(cmd)
                if database_dump_format == 'dump':
                    dump_cmd.insert(-1, '--format=c')
                dump_cmd.insert(-1, '--file=' + dump_path)
                subprocess.run(
                    dump_cmd, env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    check=True,
                )

                # Write ZIP to stream
                osutil.zip_dir(
                    dump_dir, stream, include_dir=False,
                    fnct_sort=lambda file_name: file_name != dump_filename,
                )
        else:
            dump_cmd = list(cmd)
            if database_dump_format == 'dump':
                dump_cmd.insert(-1, '--format=c')
            stdout = subprocess.Popen(
                dump_cmd, env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
            ).stdout
            shutil.copyfileobj(stdout, stream)

    def _copy_odoo_project_folder(self, dump_dir):
        """Copy the detected Odoo project folder into the backup ZIP.

        The project root name is not hardcoded. If the configured path is empty
        or invalid, the module searches for a folder such as /odoo0, /odoo1 or
        /odoo2 that contains an addons directory. The detected folder basename is
        preserved inside the ZIP.
        """
        root_path = self._get_odoo_project_root_path()
        project_folder_name = os.path.basename(root_path.rstrip(os.sep))
        target_root = os.path.join(dump_dir, project_folder_name)
        addons_path = os.path.join(root_path, 'addons')

        os.makedirs(target_root, exist_ok=True)
        shutil.copytree(addons_path, os.path.join(target_root, 'addons'), dirs_exist_ok=True)

        # Keep the known project structure visible inside the backup.
        for folder_name in ('config', 'logs'):
            source_folder = os.path.join(root_path, folder_name)
            target_folder = os.path.join(target_root, folder_name)
            if os.path.isdir(source_folder):
                shutil.copytree(source_folder, target_folder, dirs_exist_ok=True)
            else:
                os.makedirs(target_folder, exist_ok=True)

        for file_name in ('docker-compose.yml', 'Dockerfile', 'dockerfile'):
            source_file = os.path.join(root_path, file_name)
            if os.path.isfile(source_file):
                shutil.copy2(source_file, os.path.join(target_root, file_name))

        self._log(f"Copied Odoo project folder '{project_folder_name}' from {root_path}")

    def _get_odoo_project_root_path(self):
        """Return the configured or auto-detected Odoo project root path."""
        configured_path = (self.odoo0_root_path or self.config_id.odoo0_root_path or '').strip().rstrip('/')

        # Accept both the project root path and a direct addons path.
        for candidate in self._normalize_odoo_project_candidates(configured_path):
            if self._is_valid_odoo_project_root(candidate):
                return candidate

        detected_path = self._detect_odoo_project_root_path()
        if detected_path:
            return detected_path

        searched = configured_path or '/odoo*, /opt/odoo*, /home/*/odoo*, /mnt/odoo*, /var/lib/odoo*'
        raise UserError(
            "Odoo project folder not found. Configure the 'Odoo Project Root Path' "
            "or make sure the project folder contains an addons directory. Searched: %s"
            % searched
        )

    def _normalize_odoo_project_candidates(self, configured_path):
        """Build possible root candidates from a configured root or addons path."""
        if not configured_path:
            return []

        candidates = [configured_path]
        if os.path.basename(configured_path.rstrip(os.sep)) == 'addons':
            candidates.append(os.path.dirname(configured_path.rstrip(os.sep)))
        else:
            candidates.append(os.path.dirname(configured_path.rstrip(os.sep)))
        return [candidate for candidate in candidates if candidate]

    def _is_valid_odoo_project_root(self, path):
        """A valid project root contains an addons folder."""
        return bool(path and os.path.isdir(os.path.join(path, 'addons')))

    def _detect_odoo_project_root_path(self):
        """Auto-detect /odoo0, /odoo1, /odoo2... preserving the real folder name."""
        search_patterns = [
            '/odoo*',
            '/opt/odoo*',
            '/home/*/odoo*',
            '/mnt/odoo*',
            '/var/lib/odoo*',
        ]

        candidates = []
        for pattern in search_patterns:
            candidates.extend(glob.glob(pattern))

        # Prefer exact project-like folders first: odoo0, odoo1, odoo2...
        candidates = sorted(set(candidates), key=lambda path: (
            0 if os.path.basename(path).startswith('odoo') else 1,
            os.path.basename(path),
            path,
        ))

        for candidate in candidates:
            if self._is_valid_odoo_project_root(candidate):
                return candidate.rstrip('/')

        return False
    
    def _verify_backup_integrity(self, backup_file_path):
        """Verify backup file integrity."""
        self._log("Verifying backup integrity")
        
        try:
            # Basic file checks
            if not os.path.exists(backup_file_path):
                raise UserError("Backup file does not exist")
            
            file_size = os.path.getsize(backup_file_path)
            if file_size == 0:
                raise UserError("Backup file is empty")
            
            # Format-specific verification
            if self.backup_format == 'zip':
                self._verify_zip_backup(backup_file_path)
            else:
                self._verify_dump_backup(backup_file_path)
            
            self.verification_status = 'verified'
            self.verification_details = f"Backup verified successfully. File size: {tools.human_size(file_size)}"
            self._log("Backup integrity verification passed")
        except Exception as e:
            self.verification_status = 'failed'
            self.verification_details = f"Verification failed: {e}"
            self._log(f"Backup integrity verification failed: {e}")
            raise UserError(f"Backup verification failed: {e}")
    
    def _verify_zip_backup(self, backup_file_path):
        """Verify ZIP backup integrity."""
        try:
            with zipfile.ZipFile(backup_file_path, 'r') as zip_file:
                # Test ZIP file integrity
                zip_file.testzip()
                
                # Check required files
                file_list = zip_file.namelist()
                dump_filename = 'dump.sql' if self.database_dump_format == 'sql' else 'dump.dump'
                if dump_filename not in file_list:
                    raise UserError(f"ZIP backup missing {dump_filename} file")

                with zip_file.open(dump_filename) as dump_file:
                    if self.database_dump_format == 'dump':
                        if dump_file.read(5) != b'PGDMP':
                            raise UserError("dump.dump is not a valid PostgreSQL custom dump")
                    else:
                        if not dump_file.read(1):
                            raise UserError("dump.sql is empty")

                if self.zip_content_mode == 'odoo0_addons':
                    if not any(name.endswith('/addons/') or '/addons/' in name for name in file_list):
                        raise UserError("ZIP backup missing Odoo project addons folder")
                else:
                    if 'manifest.json' not in file_list:
                        raise UserError("ZIP backup missing manifest.json file")

                    # Validate manifest
                    with zip_file.open('manifest.json') as manifest_file:
                        manifest = json.loads(manifest_file.read().decode())
                        if manifest.get('db_name') != self.database_name:
                            raise UserError("Manifest database name mismatch")
        except zipfile.BadZipFile:
            raise UserError("Backup file is not a valid ZIP archive")
    
    def _verify_dump_backup(self, backup_file_path):
        """Verify PostgreSQL dump backup integrity."""
        try:
            with open(backup_file_path, 'rb') as f:
                if self.database_dump_format == 'dump':
                    header = f.read(5)
                    # PostgreSQL custom format dumps start with 'PGDMP'
                    if header != b'PGDMP':
                        raise UserError("File is not a valid PostgreSQL custom dump")
                else:
                    if not f.read(1):
                        raise UserError("SQL dump file is empty")
        except Exception as e:
            raise UserError(f"Failed to verify dump file: {e}")
    
    def _upload_to_providers(self, backup_file_path):
        """Upload backup to all configured storage providers."""
        providers = self.config_id.all_providers
        return self._upload_to_providers_sequential(backup_file_path, providers)
    
    def _upload_to_providers_sequential(self, backup_file_path, providers):
        """Upload to providers sequentially."""
        results = {}
        
        for provider in providers:
            self._log(f"Uploading to provider: {provider.name}")
            
            try:
                result = provider.upload_backup(backup_file_path, self.backup_filename)
                results[provider.name] = result
                
                if result.get('success'):
                    self._log(f"Upload to {provider.name} successful")
                else:
                    self._log(f"Upload to {provider.name} failed: {result.get('message', 'Unknown error')}")
            except Exception as e:
                error_msg = f"Upload to {provider.name} failed with exception: {e}"
                self._log(error_msg)
                results[provider.name] = {
                    'success': False,
                    'message': str(e),
                    'metadata': {}
                }
        
        return results
    
    def _serialize_provider_results(self, provider_results):
        """Serialize provider results to JSON, handling datetime objects."""
        def datetime_serializer(obj):
            """JSON serializer function for datetime objects."""
            if isinstance(obj, datetime.datetime):
                return obj.isoformat()
            elif isinstance(obj, datetime.date):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        
        try:
            return json.dumps(provider_results, indent=2, default=datetime_serializer)
        except Exception as e:
            # Fallback - convert to string representation
            _logger.warning("Failed to serialize provider results to JSON: %s", str(e))
            return str(provider_results)
    
    def _log(self, message):
        """Add entry to backup job log."""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        
        if self.log_entries:
            self.log_entries += f"\n{log_entry}"
        else:
            self.log_entries = log_entry
        
        # Also log to system logger
        _logger.info("Backup Job %d: %s", self.id, message)
    
    def retry_backup(self):
        """Retry a failed backup job."""
        self.ensure_one()
        
        if self.status not in ['error', 'warning']:
            raise UserError("Can only retry failed or warning backups")
        
        # Reset job status
        self.write({
            'status': 'pending',
            'end_time': False,
            'error_message': False,
            'log_entries': False,
            'provider_results': False,
            'verification_status': 'not_verified',
            'verification_details': False,
        })
        
        # Process the backup
        return self._process_backup()
    
    def view_provider_results(self):
        """View detailed provider results."""
        self.ensure_one()
        
        if not self.provider_results:
            raise UserError("No provider results available")
        
        try:
            results = json.loads(self.provider_results)
            formatted_results = json.dumps(results, indent=2)
        except:
            formatted_results = self.provider_results
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Provider Results',
            'res_model': 'backup.job',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': {
                'default_provider_results': formatted_results,
            },
        }
