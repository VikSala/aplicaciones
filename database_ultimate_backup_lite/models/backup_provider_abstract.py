# -*- coding: utf-8 -*-

import logging

from abc import abstractmethod
from odoo import models, fields

_logger = logging.getLogger(__name__)


class BackupProviderAbstract(models.AbstractModel):
    """
    Abstract base class for all backup storage providers.
    
    This class defines the interface that all backup providers must implement.
    It uses the Strategy pattern to allow easy extension with new storage providers.
    """
    _name = 'backup.provider.abstract'
    _description = 'Abstract Backup Provider'
    
    name = fields.Char(
        string='Name',
        required=True,
        help='Human-readable name for this backup provider'
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Whether this provider is available for use'
    )
    test_connection_result = fields.Text(
        string='Last Connection Test',
        readonly=True,
        help='Result of the last connection test'
    )
    test_connection_date = fields.Datetime(
        string='Last Test Date',
        readonly=True
    )
    
    def name_get(self):
        """Return name with provider type for better identification."""
        result = []
        for record in self:
            if record.name and hasattr(record, 'provider_type') and record.provider_type:
                # Get provider type name from field selection if available
                provider_type_field = record._fields.get('provider_type')
                if provider_type_field and hasattr(provider_type_field, 'selection'):
                    provider_type_name = dict(provider_type_field.selection).get(record.provider_type, record.provider_type)
                    name = f"{record.name} ({provider_type_name})"
                else:
                    name = f"{record.name} ({record.provider_type})"
            elif record.name:
                name = record.name
            else:
                name = f"Provider #{record.id}" if record.id else "New Provider"
            result.append((record.id, name))
        return result
    
    # Abstract methods that must be implemented by concrete providers
    @abstractmethod
    def test_connection(self):
        """
        Test the connection to the storage provider.
        
        Returns:
            dict: Result containing success status and message
        """
        pass
    
    def test_connection_action(self):
        """
        Test connection method for UI button - shows notification and updates fields.
        
        This method calls test_connection() and displays appropriate notifications.
        """
        try:
            result = self.test_connection()
            
            # Update test connection fields
            self.test_connection_result = result.get('message', 'Unknown result')
            self.test_connection_date = fields.Datetime.now()
            
            # Show notification
            if result.get('success'):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Connection Test Successful',
                        'message': result.get('message', 'Connection test passed'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Connection Test Failed',
                        'message': result.get('message', 'Connection test failed'),
                        'type': 'danger',
                        'sticky': True,
                    }
                }
        except Exception as e:
            # Update fields on exception
            error_msg = f"Connection test failed: {str(e)}"
            self.test_connection_result = error_msg
            self.test_connection_date = fields.Datetime.now()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Test Error',
                    'message': error_msg,
                    'type': 'danger',
                    'sticky': True,
                }
            }
    
    @abstractmethod
    def upload_backup(self, backup_file_path, remote_filename):
        """
        Upload a backup file to the storage provider.
        
        Args:
            backup_file_path (str): Local path to the backup file
            remote_filename (str): Name to use for the remote file
            
        Returns:
            dict: Result containing success status, message, and metadata
        """
        pass
    
    @abstractmethod
    def download_backup(self, remote_filename, local_path):
        """
        Download a backup file from the storage provider.
        
        Args:
            remote_filename (str): Name of the remote file
            local_path (str): Local path where to save the file
            
        Returns:
            dict: Result containing success status and message
        """
        pass
    
    @abstractmethod
    def list_backups(self, prefix=None):
        """
        List available backup files in the storage provider.
        
        Args:
            prefix (str, optional): Filter files by prefix
            
        Returns:
            list: List of backup file information dicts
        """
        pass
    
    @abstractmethod
    def delete_backup(self, remote_filename):
        """
        Delete a backup file from the storage provider.
        
        Args:
            remote_filename (str): Name of the remote file to delete
            
        Returns:
            dict: Result containing success status and message
        """
        pass
    
    @abstractmethod
    def get_storage_info(self):
        """
        Get storage information (used space, available space, etc.).
        
        Returns:
            dict: Storage information
        """
        pass
