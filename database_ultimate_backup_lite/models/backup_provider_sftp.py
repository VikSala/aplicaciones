# -*- coding: utf-8 -*-

import os
import asyncio
import datetime
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

try:
    import asyncssh
except ImportError:
    asyncssh = None
    _logger.warning(
        "AsyncSSH library not found. Please install it with: pip install asyncssh"
    )


class BackupProviderSftp(models.Model):
    """
    SFTP backup provider using AsyncSSH for high performance.

    This provider uses the modern AsyncSSH library instead of paramiko
    for better performance, reliability, and maintainability.
    """
    _name = 'backup.provider.sftp'
    _description = 'SFTP Backup Provider'
    _inherit = 'backup.provider.abstract'

    provider_type = fields.Selection(
        selection=[('sftp', 'SFTP/SSH')],
        default='sftp',
        readonly=True
    )

    # SFTP-specific configuration
    hostname = fields.Char(
        string='Hostname/IP',
        required=True,
        help='SFTP server hostname or IP address'
    )
    port = fields.Integer(
        string='Port',
        default=22,
        required=True,
        help='SFTP server port (default: 22)'
    )
    username = fields.Char(
        string='Username',
        required=True,
        help='Username for SFTP authentication'
    )
    password = fields.Char(
        string='Password',
        help='Password for authentication (leave empty to use key-based auth)'
    )
    remote_directory = fields.Char(
        string='Remote Directory',
        default='/home/backups',
        required=True,
        help='Remote directory where backups will be stored'
    )
    create_remote_dirs = fields.Boolean(
        string='Create Remote Directories',
        default=True,
        help='Automatically create remote directories if they do not exist'
    )
    connection_timeout = fields.Integer(
        string='Connection Timeout (seconds)',
        default=30,
        help='Timeout for establishing SSH connection'
    )
    transfer_timeout = fields.Integer(
        string='Transfer Timeout (seconds)',
        default=3600,
        help='Timeout for file transfer operations (0 = no timeout)'
    )
    preserve_file_permissions = fields.Boolean(
        string='Preserve File Permissions',
        default=True,
        help='Preserve file permissions during transfer'
    )
    max_concurrent_transfers = fields.Integer(
        string='Max Concurrent Transfers',
        default=1,
        help='Maximum number of concurrent file transfers (AsyncSSH feature)'
    )

    # Override abstract methods
    def test_connection(self):
        """Test SFTP connection and permissions."""
        self.ensure_one()

        if not asyncssh:
            error_msg = "AsyncSSH library not available. Please install it with: pip install asyncssh"
            return {
                'success': False,
                'message': error_msg
            }

        try:
            # Run async connection test
            result = asyncio.run(self._async_test_connection())

            return result
        except Exception as e:
            error_msg = "Connection test failed: %s" % str(e)

            return {
                'success': False,
                'message': error_msg
            }

    async def _async_test_connection(self):
        """Async method to test SFTP connection."""
        try:
            # Prepare connection options
            connect_options = self._get_connection_options()

            # Establish connection
            async with asyncssh.connect(
                self.hostname,
                port=self.port,
                username=self.username,
                **connect_options
            ) as conn:

                # Test SFTP subsystem
                async with conn.start_sftp_client() as sftp:
                    # Test remote directory access
                    try:
                        # Try to list directory
                        await sftp.listdir(self.remote_directory)
                        directory_status = "Remote directory accessible: %s" % self.remote_directory
                    except asyncssh.SFTPNoSuchFile:
                        if self.create_remote_dirs:
                            # Try to create directory
                            await sftp.makedirs(self.remote_directory)
                            directory_status = "Remote directory created: %s" % self.remote_directory
                        else:
                            raise UserError("Remote directory does not exist: %s" % self.remote_directory)

                    # Test write permissions by creating a test file
                    test_file = f"{self.remote_directory}/.backup_test_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

                    try:
                        async with sftp.open(test_file, 'w') as f:
                            await f.write('test')

                        # Clean up test file
                        await sftp.remove(test_file)

                        write_status = "Write permissions: OK"
                    except Exception as e:
                        raise UserError("No write permission in remote directory: %s" % str(e))

                    # Get server information
                    try:
                        server_info = conn.get_extra_info('server_version', 'Unknown SSH server')
                    except:
                        server_info = "SSH server (version unknown)"

                    message = (
                        f"{directory_status}\n"
                        f"{write_status}\n"
                        f"Server: {server_info}\n"
                        f"Connection: Successful"
                    )

                    return {
                        'success': True,
                        'message': message
                    }
        except asyncssh.PermissionDenied:
            raise UserError("Authentication failed. Check username/password or key.")
        except asyncssh.ConnectionLost:
            raise UserError("Connection lost. Check hostname/port and network connectivity.")
        except asyncssh.TimeoutError:
            raise UserError("Connection timeout. Server may be unreachable.")
        except Exception as e:
            raise UserError("Connection failed: %s" % str(e))

    def upload_backup(self, backup_file_path, remote_filename):
        """Upload backup file via SFTP."""
        self.ensure_one()

        if not asyncssh:
            return {
                'success': False,
                'message': "AsyncSSH library not available"
            }

        try:
            result = asyncio.run(self._async_upload_backup(backup_file_path, remote_filename))
            return result
        except Exception as e:
            return {
                'success': False,
                'message': "Upload failed: %s" % str(e),
                'metadata': {}
            }

    async def _async_upload_backup(self, backup_file_path, remote_filename):
        """Async method to upload backup file."""
        connect_options = self._get_connection_options()

        async with asyncssh.connect(
            self.hostname,
            port=self.port,
            username=self.username,
            **connect_options
        ) as conn:
            async with conn.start_sftp_client() as sftp:

                # Ensure remote directory exists
                if self.create_remote_dirs:
                    await sftp.makedirs(self.remote_directory, exist_ok=True)

                # Upload file
                remote_path = f"{self.remote_directory}/{remote_filename}"

                # Use AsyncSSH's high-performance upload
                await sftp.put(
                    backup_file_path,
                    remote_path,
                    preserve=self.preserve_file_permissions
                )

                # Verify upload by checking file size
                local_stats = os.stat(backup_file_path)
                remote_stats = await sftp.stat(remote_path)

                if local_stats.st_size != remote_stats.size:
                    raise UserError(
                        "Upload verification failed. Local size: %d, Remote size: %d"
                        % (local_stats.st_size, remote_stats.size)
                    )

                return {
                    'success': True,
                    'message': "Backup uploaded successfully to: %s" % remote_path,
                    'metadata': {
                        'remote_path': remote_path,
                        'size_bytes': remote_stats.size,
                        'size_gb': remote_stats.size / (1024**3),
                        'upload_date': datetime.datetime.now(),
                        'permissions': oct(remote_stats.permissions)
                    }
                }

    def download_backup(self, remote_filename, local_path):
        """Download backup file via SFTP."""
        self.ensure_one()

        if not asyncssh:
            return {
                'success': False,
                'message': "AsyncSSH library not available"
            }

        try:
            result = asyncio.run(self._async_download_backup(remote_filename, local_path))
            return result
        except Exception as e:
            return {
                'success': False,
                'message': "Download failed: %s" % str(e)
            }

    async def _async_download_backup(self, remote_filename, local_path):
        """Async method to download backup file."""
        connect_options = self._get_connection_options()

        async with asyncssh.connect(
            self.hostname,
            port=self.port,
            username=self.username,
            **connect_options
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                remote_path = f"{self.remote_directory}/{remote_filename}"

                # Check if remote file exists
                try:
                    remote_stats = await sftp.stat(remote_path)
                except asyncssh.SFTPNoSuchFile:
                    raise UserError("Remote backup file not found: %s" % remote_path)

                # Download file
                await sftp.get(remote_path, local_path)

                # Verify download
                local_stats = os.stat(local_path)
                if local_stats.st_size != remote_stats.size:
                    raise UserError(
                        "Download verification failed. Expected size: %d, Actual size: %d"
                        % (remote_stats.size, local_stats.st_size)
                    )

                return {
                    'success': True,
                    'message': "Backup downloaded successfully to: %s" % local_path
                }

    def list_backups(self, prefix=None):
        """List backup files on SFTP server."""
        self.ensure_one()

        if not asyncssh:
            return []

        try:
            result = asyncio.run(self._async_list_backups(prefix))
            return result
        except Exception as e:
            _logger.error("Failed to list backups: %s", str(e))
            return []

    async def _async_list_backups(self, prefix=None):
        """Async method to list backup files."""
        connect_options = self._get_connection_options()

        async with asyncssh.connect(
            self.hostname,
            port=self.port,
            username=self.username,
            **connect_options
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                try:
                    filenames = await sftp.listdir(self.remote_directory)
                except asyncssh.SFTPNoSuchFile:
                    return []

                backups = []

                for filename in filenames:
                    # Filter by prefix if specified
                    if prefix and not filename.startswith(prefix):
                        continue

                    # Check if it's a backup file
                    if self._is_backup_file(filename):
                        try:
                            # Get file attributes separately
                            file_path = f"{self.remote_directory}/{filename}"
                            file_attr = await sftp.stat(file_path)

                            backups.append({
                                'filename': filename,
                                'remote_path': file_path,
                                'size_bytes': file_attr.size,
                                'size_gb': file_attr.size / (1024**3),
                                'modified_date': datetime.datetime.fromtimestamp(file_attr.mtime),
                                'permissions': oct(file_attr.permissions) if file_attr.permissions else None
                            })
                        except Exception as e:
                            _logger.warning("Failed to get attributes for file %s: %s", filename, str(e))

                # Sort by modification date (newest first)
                backups.sort(key=lambda x: x['modified_date'], reverse=True)

                return backups

    def delete_backup(self, remote_filename):
        """Delete backup file from SFTP server."""
        self.ensure_one()

        if not asyncssh:
            return {
                'success': False,
                'message': "AsyncSSH library not available"
            }

        try:
            result = asyncio.run(self._async_delete_backup(remote_filename))
            return result
        except Exception as e:
            return {
                'success': False,
                'message': "Delete failed: %s" % str(e)
            }

    async def _async_delete_backup(self, remote_filename):
        """Async method to delete backup file."""
        connect_options = self._get_connection_options()

        async with asyncssh.connect(
            self.hostname,
            port=self.port,
            username=self.username,
            **connect_options
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                remote_path = f"{self.remote_directory}/{remote_filename}"

                try:
                    await sftp.remove(remote_path)
                    return {
                        'success': True,
                        'message': "Backup file deleted successfully: %s" % remote_path
                    }
                except asyncssh.SFTPNoSuchFile:
                    return {
                        'success': False,
                        'message': "Backup file not found: %s" % remote_path
                    }

    def get_storage_info(self):
        """Get SFTP storage information."""
        self.ensure_one()

        if not asyncssh:
            return {}

        try:
            result = asyncio.run(self._async_get_storage_info())
            return result
        except Exception as e:
            _logger.error("Failed to get storage info: %s", str(e))
            return {}

    async def _async_get_storage_info(self):
        """Async method to get storage information."""
        connect_options = self._get_connection_options()

        async with asyncssh.connect(
            self.hostname,
            port=self.port,
            username=self.username,
            **connect_options
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                # Get backup list
                backups = await self._async_list_backups()

                # Calculate total backup size
                total_size = sum(backup['size_bytes'] for backup in backups)

                # Try to get disk space information (may not be available on all servers)
                try:
                    result = await conn.run(f'df -B1 "{self.remote_directory}" | tail -1')
                    if result.exit_status == 0:
                        fields = result.stdout.split()
                        if len(fields) >= 4:
                            total_space = int(fields[1])
                            used_space = int(fields[2])
                            free_space = int(fields[3])
                        else:
                            total_space = used_space = free_space = 0
                    else:
                        total_space = used_space = free_space = 0
                except:
                    total_space = used_space = free_space = 0

                return {
                    'provider_type': 'sftp',
                    'backup_count': len(backups),
                    'total_backup_size_gb': total_size / (1024**3),
                    'free_space_gb': free_space / (1024**3) if free_space else None,
                    'total_space_gb': total_space / (1024**3) if total_space else None,
                    'used_space_gb': used_space / (1024**3) if used_space else None,
                    'storage_path': f"{self.hostname}:{self.remote_directory}",
                }

    # Private utility methods
    def _get_connection_options(self):
        """Get connection options for AsyncSSH."""
        options = {
            'connect_timeout': self.connection_timeout,
            # Disable strict host key checking to avoid "Host key is not trusted" errors
            'known_hosts': None,
        }

        # Authentication
        if self.password:
            options['password'] = self.password

        return options

    def _is_backup_file(self, filename):
        """Check if filename is a backup file."""
        backup_extensions = ['.zip', '.dump', '.sql', '.tar.gz', '.tgz']
        return any(filename.lower().endswith(ext) for ext in backup_extensions)

    # Validation methods
    @api.constrains('hostname')
    def _check_hostname(self):
        """Validate hostname."""
        for record in self:
            if not record.hostname:
                raise ValidationError("Hostname is required")

    @api.constrains('port')
    def _check_port(self):
        """Validate port number."""
        for record in self:
            if not (1 <= record.port <= 65535):
                raise ValidationError("Port must be between 1 and 65535")

    @api.constrains('connection_timeout', 'transfer_timeout')
    def _check_timeouts(self):
        """Validate timeout values."""
        for record in self:
            if record.connection_timeout < 1:
                raise ValidationError("Connection timeout must be at least 1 second")
            if record.transfer_timeout < 0:
                raise ValidationError("Transfer timeout must be non-negative")