# -*- coding: utf-8 -*-

import datetime
import logging
import re

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class BackupConfig(models.Model):
    """
    Main backup configuration model.
    
    This model defines backup configurations with support for multiple
    storage providers, scheduling, and advanced features.
    """
    _name = 'backup.config'
    _description = 'Backup Configuration'
    _order = 'name, id desc'
    
    # Basic configuration
    name = fields.Char(
        string='Name',
        required=True,
        help='Human-readable name for this backup configuration'
    )
    description = fields.Text(
        string='Description',
        help='Optional description for this backup configuration'
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Whether this backup configuration is active'
    )
    
    # Database configuration
    database_name = fields.Char(
        string='Database Name',
        required=True,
        default=lambda self: self._get_current_database(),
        help='Name of the database to backup'
    )
    backup_format = fields.Selection([
        ('zip', 'ZIP Archive (includes filestore)'),
        ('dump', 'PostgreSQL Dump (SQL only)'),
    ], string='Backup Format', required=True, default='zip',
       help='Format of the backup file')
    zip_content_mode = fields.Selection([
        ('manifest', 'Modules JSON / manifest.json'),
        ('odoo0_addons', 'Odoo project addons folder'),
    ], string='ZIP Extra Content', required=True, default='manifest',
       help='For ZIP backups, choose whether to include the modules JSON manifest or the addons folder from your Odoo project structure.')
    odoo0_root_path = fields.Char(
        string='Odoo Project Root Path',
        default=lambda self: self._get_current_database(),
        help='Optional root folder of your Odoo project structure. If empty, the module will auto-detect a folder such as /odoo0, /odoo1 or /odoo2 containing addons.'
    )
    
    # Storage providers
    local_provider_ids = fields.Many2many(
        'backup.provider.local',
        'backup_config_local_provider_rel',
        'config_id', 'provider_id',
        string='Local Storage Providers',
        help='Local filesystem storage providers'
    )
    sftp_provider_ids = fields.Many2many(
        'backup.provider.sftp',
        'backup_config_sftp_provider_rel',
        'config_id', 'provider_id',
        string='SFTP Storage Providers',
        help='SFTP/SSH remote storage providers'
    )
    # Retention policy
    retention_policy = fields.Selection([
        ('count', 'Keep Last N Backups'),
        ('days', 'Keep Backups for N Days'),
        ('custom', 'Custom Retention Policy'),
    ], string='Retention Policy', required=True, default='count')
    retention_count = fields.Integer(
        string='Number of Backups to Keep',
        default=7,
        help='Number of recent backups to keep (for count-based retention)'
    )
    retention_days = fields.Integer(
        string='Days to Keep Backups',
        default=30,
        help='Number of days to keep backups (for time-based retention)'
    )
    # Advanced options
    backup_name_template = fields.Char(
        string='Backup Name Template',
        default='{database}_{timestamp}.{format}',
        help='Template for backup filenames. Available variables: {database}, {timestamp}, {format}'
    )
    verify_backups = fields.Boolean(
        string='Verify Backup Integrity',
        default=True,
        help='Verify backup integrity after creation and upload'
    )
    
    # Notifications
    notify_success = fields.Boolean(
        string='Notify on Success',
        default=False,
        help='Send notification when backup completes successfully'
    )
    notify_failure = fields.Boolean(
        string='Notify on Failure',
        default=True,
        help='Send notification when backup fails'
    )
    notification_emails = fields.Char(
        string='Notification Emails',
        help='Comma-separated list of email addresses for notifications'
    )
    
    # Statistics and monitoring
    last_backup_date = fields.Datetime(
        string='Last Backup Date',
        readonly=True
    )
    last_backup_status = fields.Selection([
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Last Backup Status', readonly=True)
    last_backup_message = fields.Text(
        string='Last Backup Message',
        readonly=True
    )
    total_backups_created = fields.Integer(
        string='Total Backups Created',
        default=0,
        readonly=True
    )
    backup_success_rate = fields.Float(
        string='Success Rate (%)',
        compute='_compute_success_rate',
        store=True,
        help='Success rate based on backup job history'
    )

    # Relationship to backup jobs
    backup_job_ids = fields.One2many(
        'backup.job',
        'config_id',
        string='Backup Jobs',
        readonly=True
    )

    @property
    def all_providers(self):
        """Get all configured providers."""
        return list(self.local_provider_ids) + list(self.sftp_provider_ids)

    def _get_current_database(self):
        """Get current database name."""
        return self.env.cr.dbname
    
    @api.depends('backup_job_ids.status')
    def _compute_success_rate(self):
        """Compute backup success rate."""
        for record in self:
            jobs = record.backup_job_ids
            if jobs:
                successful_jobs = jobs.filtered(lambda j: j.status == 'success')
                record.backup_success_rate = (len(successful_jobs) / len(jobs)) * 100
            else:
                record.backup_success_rate = 0.0
    
    def create_backup(self):
        """
        Create a backup using this configuration.
        
        This method creates a new backup job and processes it.
        """
        self.ensure_one()
        
        if not self.active:
            raise UserError("Cannot create backup: configuration is inactive")
        
        if not self.all_providers:
            raise UserError("Cannot create backup: no storage providers configured")
        
        # Create backup job
        is_manual = self.env.context.get('manual_execution', True)
        backup_job = self.env['backup.job'].create({
            'config_id': self.id,
            'database_name': self.database_name,
            'backup_format': self.backup_format,
            'zip_content_mode': self.zip_content_mode,
            'odoo0_root_path': self.odoo0_root_path,
            'status': 'running',
            'start_time': fields.Datetime.now(),
            'is_manual': is_manual,  # Flag to indicate execution type
        })
        
        try:
            # Process the backup job
            result = backup_job._process_backup()
            
            # Update configuration statistics
            self._update_backup_statistics(result)
            
            # Send notifications if needed
            if result.get('success') and self.notify_success:
                self._send_notification(backup_job, 'success')
            elif not result.get('success') and self.notify_failure:
                self._send_notification(backup_job, 'failure')
            
            # Return appropriate response based on context
            # For UI calls, return notifications. For programmatic calls (cron), return the backup_job
            if self.env.context.get('manual_execution', True):
                # Show user notification based on result
                if result.get('success'):
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Backup Successful',
                            'message': f"Backup '{backup_job.backup_filename}' created successfully.",
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Backup Failed',
                            'message': result.get('message', 'Unknown error occurred during backup.'),
                            'type': 'danger',
                            'sticky': True,
                        }
                    }
            else:
                # For programmatic execution (cron), return the backup_job
                return backup_job
        except Exception as e:
            _logger.error("Backup creation failed: %s", str(e))
            backup_job.write({
                'status': 'error',
                'end_time': fields.Datetime.now(),
                'error_message': str(e),
            })
            
            # Update configuration
            self.write({
                'last_backup_date': fields.Datetime.now(),
                'last_backup_status': 'error',
                'last_backup_message': str(e),
            })
            
            # Send failure notification
            if self.notify_failure:
                self._send_notification(backup_job, 'failure')
            
            # Return appropriate response based on context
            if self._context.get('manual_execution', True):
                # Show error notification to user instead of raising
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Backup Error',
                        'message': f"Backup failed: {str(e)}",
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            else:
                # For programmatic execution, return the backup_job
                return backup_job
    
    def test_providers(self):
        """Test all configured providers."""
        self.ensure_one()
        
        if not self.all_providers:
            raise UserError("No storage providers configured")
        
        results = []
        
        for provider in self.all_providers:
            try:
                result = provider.test_connection()
                results.append({
                    'provider': provider.name,
                    'success': result.get('success', False),
                    'message': result.get('message', 'Unknown error')
                })
            except Exception as e:
                results.append({
                    'provider': provider.name,
                    'success': False,
                    'message': str(e)
                })
        
        # Create summary message
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]
        
        if failed:
            # Some providers failed
            message_parts = []
            if successful:
                message_parts.append(f"Successful ({len(successful)}):")
                message_parts.extend([f"✓ {r['provider']}: {r['message']}" for r in successful])
                message_parts.append("")  # Empty line
            
            message_parts.append(f"Failed ({len(failed)}):")
            message_parts.extend([f"✗ {r['provider']}: {r['message']}" for r in failed])
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Provider Test Results',
                    'message': '\n'.join(message_parts),
                    'type': 'warning',
                    'sticky': True,
                }
            }
        else:
            # All providers successful
            message_parts = [f"All provider tests successful! ({len(successful)})", ""]
            message_parts.extend([f"✓ {r['provider']}: {r['message']}" for r in successful])
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Provider Tests Successful',
                    'message': '\n'.join(message_parts),
                    'type': 'success',
                    'sticky': False,
                }
            }
    
    def test_retention_policy(self):
        """Test retention policy without actually deleting backups."""
        self.ensure_one()
        
        results = []
        
        for provider in self.all_providers:
            try:
                # Get list of backups
                backups = provider.list_backups(prefix=self.database_name)
                
                # Determine which backups would be deleted
                backups_to_delete = self._get_backups_to_delete(backups)
                
                results.append({
                    'provider': provider.name,
                    'success': True,
                    'total_backups': len(backups),
                    'backups_to_delete': len(backups_to_delete),
                    'backups_to_keep': len(backups) - len(backups_to_delete),
                    'deletion_list': [b['filename'] for b in backups_to_delete[:5]]  # Show first 5
                })
                
            except Exception as e:
                results.append({
                    'provider': provider.name,
                    'success': False,
                    'error': str(e),
                    'total_backups': 0,
                    'backups_to_delete': 0,
                    'backups_to_keep': 0,
                    'deletion_list': []
                })
        
        # Create summary message
        message_parts = [f"Retention Policy Test Results ({self.retention_policy}):", ""]
        
        if self.retention_policy == 'count':
            message_parts.append(f"Policy: Keep last {self.retention_count} backups")
        elif self.retention_policy == 'days':
            message_parts.append(f"Policy: Keep backups for {self.retention_days} days")
        
        message_parts.append("")
        
        for result in results:
            if result['success']:
                message_parts.append(f"✓ {result['provider']}:")
                message_parts.append(f"  Total backups: {result['total_backups']}")
                message_parts.append(f"  Would delete: {result['backups_to_delete']}")
                message_parts.append(f"  Would keep: {result['backups_to_keep']}")
                if result['deletion_list']:
                    message_parts.append(f"  Files to delete: {', '.join(result['deletion_list'])}")
                    if result['backups_to_delete'] > 5:
                        message_parts.append(f"    ... and {result['backups_to_delete'] - 5} more")
            else:
                message_parts.append(f"✗ {result['provider']}: {result['error']}")
            message_parts.append("")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Retention Policy Test',
                'message': '\n'.join(message_parts),
                'type': 'info',
                'sticky': True,
            }
        }
    
    def cleanup_old_backups(self):
        """Clean up old backups according to retention policy."""
        self.ensure_one()
        
        is_manual = self._context.get('manual_execution', True)
        results = []
        total_deleted = 0
        
        for provider in self.all_providers:
            try:
                # Get list of backups
                backups = provider.list_backups(prefix=self.database_name)
                
                # Determine which backups to delete
                backups_to_delete = self._get_backups_to_delete(backups)
                
                deleted_count = 0
                failed_count = 0
                
                # Delete old backups
                for backup in backups_to_delete:
                    result = provider.delete_backup(backup['filename'])
                    if result.get('success'):
                        deleted_count += 1
                        _logger.info(
                            "Deleted old backup %s from provider %s", 
                            backup['filename'], provider.name
                        )
                    else:
                        failed_count += 1
                        _logger.warning(
                            "Failed to delete backup %s from provider %s: %s",
                            backup['filename'], provider.name, result.get('message', 'Unknown error')
                        )
                
                results.append({
                    'provider': provider.name,
                    'success': True,
                    'deleted': deleted_count,
                    'failed': failed_count,
                    'total_backups': len(backups)
                })
                total_deleted += deleted_count
                
            except Exception as e:
                _logger.error(
                    "Error cleaning up backups for provider %s: %s",
                    provider.name, str(e)
                )
                results.append({
                    'provider': provider.name,
                    'success': False,
                    'error': str(e),
                    'deleted': 0,
                    'failed': 0,
                    'total_backups': 0
                })
        
        # Return notification for manual execution
        if is_manual:
            # Create summary message
            message_parts = [f"Cleanup completed! Policy: {self.retention_policy}", ""]
            
            if self.retention_policy == 'count':
                message_parts.append(f"Keeping last {self.retention_count} backups per provider")
            elif self.retention_policy == 'days':
                message_parts.append(f"Keeping backups for {self.retention_days} days")
            
            message_parts.extend(["", f"Total files deleted: {total_deleted}", ""])
            
            for result in results:
                if result['success']:
                    message_parts.append(f"✓ {result['provider']}:")
                    message_parts.append(f"  Total backups: {result['total_backups']}")
                    message_parts.append(f"  Deleted: {result['deleted']}")
                    if result['failed'] > 0:
                        message_parts.append(f"  Failed: {result['failed']}")
                else:
                    message_parts.append(f"✗ {result['provider']}: {result['error']}")
                message_parts.append("")
            
            notification_type = 'success' if total_deleted > 0 else 'info'
            if any(not r['success'] for r in results):
                notification_type = 'warning'
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Backup Cleanup Results',
                    'message': '\n'.join(message_parts),
                    'type': notification_type,
                    'sticky': True,
                }
            }
    
    def _get_backups_to_delete(self, backups):
        """Determine which backups should be deleted based on retention policy."""
        if not backups:
            return []
        
        # Sort backups by creation date (newest first)
        sorted_backups = sorted(
            backups, 
            key=lambda x: x.get('created_date') or x.get('modified_date', datetime.datetime.min),
            reverse=True
        )
        
        backups_to_delete = []
        
        if self.retention_policy == 'count':
            # Keep only the last N backups
            if len(sorted_backups) > self.retention_count:
                backups_to_delete = sorted_backups[self.retention_count:]
        elif self.retention_policy == 'days':
            # Delete backups older than N days
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=self.retention_days)
            
            for backup in sorted_backups:
                backup_date = backup.get('created_date') or backup.get('modified_date')
                if backup_date and backup_date < cutoff_date:
                    backups_to_delete.append(backup)
        
        return backups_to_delete
    
    def _update_backup_statistics(self, result):
        """Update backup statistics after a backup operation."""
        status = 'success' if result.get('success') else 'error'
        message = result.get('message', 'Unknown result')
        
        vals = {
            'last_backup_date': fields.Datetime.now(),
            'last_backup_status': status,
            'last_backup_message': message,
        }
        
        if result.get('success'):
            vals['total_backups_created'] = self.total_backups_created + 1
        
        self.write(vals)

    def _send_notification(self, backup_job, notification_type):
        """
        Send backup notification email.

        This method runs independently from the backup process to ensure
        email failures don't affect the backup job status.
        """
        if not self.notification_emails:
            _logger.debug("Skipping notification: no recipient emails configured")
            return

        try:
            # Check if mail server is configured
            mail_server = self.env['ir.mail_server'].sudo().search([], order='sequence asc', limit=1)
            if not mail_server:
                _logger.warning("Cannot send backup notification: no mail server configured in Odoo")
                return

            # Prepare email content
            if notification_type == 'success':
                subject = "Backup Successful: %s" % self.name
                body = self._get_success_notification_body(backup_job)
            else:
                subject = "Backup Failed: %s" % self.name
                body = self._get_failure_notification_body(backup_job)

            # Get sender email
            catch_all_domain = self.env["ir.config_parameter"].sudo().get_param("mail.catchall.domain")
            system_email = self.env["ir.config_parameter"].sudo().get_param("mail.default.from")
            sender_email = (
                f"backup@{catch_all_domain}" if catch_all_domain
                else system_email if system_email
                else mail_server.smtp_user
            )

            # Validate sender email
            if not sender_email:
                _logger.warning("Cannot send backup notification: no valid sender email address")
                return

            # Parse recipient emails
            recipient_emails = [email.strip() for email in self.notification_emails.split(',') if email.strip()]
            if not recipient_emails:
                _logger.warning("Cannot send backup notification: no valid recipient emails")
                return

            # Build and send email
            _logger.info("Sending backup notification email from %s to %s", sender_email, recipient_emails)
            msg = mail_server.build_email(
                sender_email,
                recipient_emails,
                subject,
                body
            )
            mail_server.send_email(msg)
            _logger.info("Backup notification sent successfully")
        except Exception as e:
            # Log detailed error but don't raise - email failures shouldn't affect backup success
            _logger.warning(
                "Failed to send backup notification for job %s (Status: %s). "
                "Error: %s. The backup itself completed successfully, but email notification failed. "
                "Please check your mail server configuration.",
                backup_job.id, notification_type, str(e)
            )

    @staticmethod
    def _format_duration(duration_seconds):
        """
        Format duration in a human-readable format.

        Args:
            duration_seconds: Duration in seconds (float)

        Returns:
            Formatted string with appropriate unit (e.g., "45 seconds", "2.5 minutes", "1.2 hours")
        """
        if not duration_seconds:
            return 'Unknown'

        # Less than 60 seconds: show as seconds (no decimals)
        if duration_seconds < 60:
            return f"{int(duration_seconds)} seconds"
        # Less than 60 minutes: show as minutes (1 decimal if needed)
        elif duration_seconds < 3600:
            minutes = duration_seconds / 60
            # Show 1 decimal only if not a whole number
            if minutes == int(minutes):
                return f"{int(minutes)} minutes"
            else:
                return f"{minutes:.1f} minutes"
        # 60 minutes or more: show as hours (1 decimal if needed)
        else:
            hours = duration_seconds / 3600
            # Show 1 decimal only if not a whole number
            if hours == int(hours):
                return f"{int(hours)} hours"
            else:
                return f"{hours:.1f} hours"
    
    def _get_success_notification_body(self, backup_job):
        """Generate success notification email body."""
        return ("""
            Backup completed successfully!
            
            Configuration: %(config_name)s
            Database: %(database)s
            Format: %(format)s
            Start Time: %(start_time)s
            End Time: %(end_time)s
            Duration: %(duration)s
            Size: %(size)s
            
            Backup Details:
            %(details)s
            
            Best regards,
            Odoo Backup System
        """ % {
            'config_name': self.name,
            'database': self.database_name,
            'format': self.backup_format.upper(),
            'start_time': backup_job.start_time.strftime('%Y-%m-%d %H:%M:%S') if backup_job.start_time else 'Unknown',
            'end_time': backup_job.end_time.strftime('%Y-%m-%d %H:%M:%S') if backup_job.end_time else 'Unknown',
            'duration': self._format_duration(backup_job.duration),
            'size': backup_job.backup_size_human or 'Unknown',
            'details': backup_job.backup_details or 'No additional details',
        })
    
    def _get_failure_notification_body(self, backup_job):
        """Generate failure notification email body."""
        return ("""
            Backup failed!
            
            Configuration: %(config_name)s
            Database: %(database)s
            Format: %(format)s
            Start Time: %(start_time)s
            Error Time: %(end_time)s
            
            Error Details:
            %(error_message)s
            
            Please check the backup configuration and try again.
            
            Best regards,
            Odoo Backup System
        """ % {
            'config_name': self.name,
            'database': self.database_name,
            'format': self.backup_format.upper(),
            'start_time': backup_job.start_time.strftime('%Y-%m-%d %H:%M:%S') if backup_job.start_time else 'Unknown',
            'end_time': backup_job.end_time.strftime('%Y-%m-%d %H:%M:%S') if backup_job.end_time else 'Unknown',
            'error_message': backup_job.error_message or 'Unknown error',
        })
    
    # Validation methods
    @api.constrains('active')
    def _check_providers(self):
        """Ensure at least one provider is configured for active configurations."""
        for record in self:
            # Only validate when activating a configuration (not during installation)
            if (record.active and 
                not self.env.context.get('install_mode') and
                not self.env.context.get('module_installation') and
                len(record.all_providers) == 0):
                raise ValidationError("At least one storage provider must be configured for active backup configurations")

    @api.constrains('retention_count')
    def _check_retention_count(self):
        """Validate retention count."""
        for record in self:
            if record.retention_policy == 'count' and record.retention_count < 1:
                raise ValidationError("Retention count must be at least 1")
    
    @api.constrains('retention_days')
    def _check_retention_days(self):
        """Validate retention days."""
        for record in self:
            if record.retention_policy == 'days' and record.retention_days < 1:
                raise ValidationError("Retention days must be at least 1")
    
    @api.constrains('notification_emails')
    def _check_notification_emails(self):
        """Validate notification email format."""
        for record in self:
            if record.notification_emails:
                emails = [email.strip() for email in record.notification_emails.split(',')]
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                
                for email in emails:
                    if email and not re.match(email_pattern, email):
                        raise ValidationError("Invalid email address: %s" % email)
    
    @api.onchange('database_name')
    def _onchange_database_name_set_odoo0_root_path(self):
        """Use the current database name as the default Odoo project root path."""
        for record in self:
            if record.database_name and not record.odoo0_root_path:
                record.odoo0_root_path = record.database_name

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to validate configuration."""
        for vals in vals_list:
            if not vals.get('database_name'):
                vals['database_name'] = self._get_current_database()
            if not vals.get('odoo0_root_path'):
                vals['odoo0_root_path'] = vals.get('database_name')
        
        return super().create(vals_list)
    
    # Scheduled action method
    @api.model
    def run_scheduled_backups(self):
        """
        Run scheduled backups for all active configurations.
        
        This method is called by the scheduled action (cron job).
        """
        # Find active backup configurations
        configs = self.search([('active', '=', True)])
        
        _logger.info("Running scheduled backups for %d configurations", len(configs))
        
        for config in configs:
            try:
                _logger.info("Starting backup for configuration: %s", config.name)
                # Set context to indicate programmatic execution
                backup_job = config.with_context(manual_execution=False).create_backup()
                _logger.info(
                    "Backup completed for configuration %s, status: %s", 
                    config.name, backup_job.status
                )
                
                # Clean up old backups (programmatic execution)
                config.with_context(manual_execution=False).cleanup_old_backups()
                
            except Exception as e:
                _logger.error(
                    "Failed to create backup for configuration %s: %s",
                    config.name, str(e)
                )
                continue
