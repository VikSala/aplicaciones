# -*- coding: utf-8 -*-
{
    'name': "Database Ultimate Backup Lite",

    'summary': "Free automated database backups with Local + SFTP storage, retention policies, integrity verification, and monitoring",

    'description': """
        Database Ultimate Backup Lite - Free Backup Solution with Local & SFTP
        ======================================================================

        A free, reliable database backup solution for Odoo 18.0 with local and SFTP
        remote storage, automated scheduling, retention policies, and comprehensive monitoring.

        Core Features
        -------------
        * **Local Storage**: Store backups on local filesystem or network-mounted drives
        * **SFTP Remote Storage**: Securely transfer backups to remote servers via SSH/SFTP
        * **Backup Formats**: ZIP archives (with filestore) or PostgreSQL dumps
        * **Integrity Verification**: Automatic verification after backup creation
        * **Flexible Scheduling**: Automated backups via configurable cron jobs
        * **Retention Policies**: Keep last N backups or retain for N days
        * **Automated Cleanup**: Automatic removal of old backups based on policy
        * **Job Monitoring**: Track backup history, status, duration, and file sizes
        * **Email Notifications**: Get notified on backup success or failure
        * **Success Rate Tracking**: Monitor backup reliability over time

        SFTP Provider Features
        ----------------------
        * High-performance transfers powered by AsyncSSH
        * Password-based authentication
        * Automatic remote directory creation
        * Upload verification (size check)
        * Configurable connection and transfer timeouts

        Security Features
        -----------------
        * Two-tier access control: User and Administrator roles
        * Secure credential storage
        * Granular model-level permissions

        Need Multi-Cloud Storage?
        -------------------------
        Upgrade to Database Ultimate Backup (Full) for enterprise multi-cloud support:
        AWS S3, Azure Blob Storage, Google Cloud Storage, DigitalOcean Spaces,
        parallel uploads, server-side encryption, and more!
    """,

    'author': "René Hechavarría",
    'website': "https://github.com/renelhs",
    'maintainer': "René Hechavarría",
    'support': "reneluishs@gmail.com",

    'category': 'Administration',
    'version': '18.0.1.0.0',

    # Module dependencies
    'depends': ['base'],

    # External dependencies
    'external_dependencies': {
        'python': ['asyncssh'],
    },

    # Data files
    'data': [
        # Security
        'security/backup_security.xml',
        'security/ir.model.access.csv',

        # Data
        'data/backup_cron.xml',
        'data/backup_provider_data.xml',

        # Views
        'views/backup_config_views.xml',
        'views/backup_job_views.xml',
        'views/backup_provider_views.xml',
        'views/menus.xml'
    ],

    'installable': True,
    'auto_install': False,
    'application': True,

    'license': 'Other OSI approved licence',

    # Store metadata
    'price': 0,
    'currency': 'USD',

    # Images
    'images': [
        'static/description/banner.png',
    ],
}
