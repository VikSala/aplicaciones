# -*- coding: utf-8 -*-

import os
import datetime
import re
import subprocess
import tempfile
import json
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
        variables = {
            'database': self.database_name,
            'timestamp': timestamp,
            'format': self.backup_format,
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
            self._dump_db(self.database_name, stream, self.backup_format)
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

    def _dump_db(self, db_name, stream, backup_format='zip'):
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

                # Generate manifest
                with open(os.path.join(dump_dir, 'manifest.json'), 'w') as fh:
                    db = odoo.sql_db.db_connect(db_name)
                    with db.cursor() as cr:
                        json.dump(self._dump_db_manifest(cr), fh, indent=4)

                # Run pg_dump
                cmd.insert(-1, '--file=' + os.path.join(dump_dir, 'dump.sql'))
                subprocess.run(
                    cmd, env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    check=True,
                )

                # Write ZIP to stream
                osutil.zip_dir(
                    dump_dir, stream, include_dir=False,
                    fnct_sort=lambda file_name: file_name != 'dump.sql',
                )
        else:
            cmd.insert(-1, '--format=c')
            stdout = subprocess.Popen(
                cmd, env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
            ).stdout
            shutil.copyfileobj(stdout, stream)
    
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
                if 'dump.sql' not in file_list:
                    raise UserError("ZIP backup missing dump.sql file")
                
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
        # For dump files, we can try to parse the header
        try:
            with open(backup_file_path, 'rb') as f:
                header = f.read(5)
                # PostgreSQL custom format dumps start with 'PGDMP'
                if header != b'PGDMP':
                    raise UserError("File is not a valid PostgreSQL dump")
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
