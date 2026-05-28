# -*- coding: utf-8 -*-
{
    'name': 'Odoo Amazon S3 Connector',
    'version': '18.0.2.0.0',
    'category': 'Document Management',
    'summary': 'Connect Odoo with Amazon S3, auto-upload attachments, and browse files from a built-in dashboard',
    'description': """
Amazon S3 Connector for Odoo
============================

A complete solution to connect your Amazon S3 buckets with Odoo and manage
files from a single S3 dashboard.

Features
--------
* **Amazon S3 integration**: full support for the official AWS S3 API via boto3
* **Multi-account, multi-bucket**: configure as many S3 Accounts as you need,
  each with its own credentials, bucket, and list of models to sync
* **Per-account model selection**: pick exactly which Odoo models' attachments
  should be auto-uploaded for each S3 Account from the **Models to Sync** tab
* **Test Connection** button on the S3 Account form for instant credential and
  bucket validation before saving
* **S3 Files Dashboard**: browse all S3 files in List View or Kanban (Grid) View
  directly inside Odoo
* **Manual file upload** from Odoo with no AWS Console login required
* **Automated daily sync**: scheduled action runs every day at 23:55 server time
  and uploads new attachments to each active account's bucket
* **Search, filter & sort**: live search, filter by file type (PDF, Image, ZIP,
  XLSX), sort by name or date
* **Inline preview**: preview images and PDFs instantly inside the dashboard
* **Duplicate-safe**: attachments are marked once uploaded so the cron never
  pushes the same file twice
* **Chatter notes**: every auto-upload posts a note on the source record
""",
    'author': 'MountSol',
    'website': 'https://www.mountsol.com',
    'depends': ['base_setup'],
    'external_dependencies': {
        'python': [
            'boto3',
        ],
    },
    'data': [
        'security/ir.model.access.csv',
        'data/schedule_action.xml',
        'views/amazon_s3_account_views.xml',
        'views/amazon_dashboard_views.xml',
        'wizard/amazon_upload_file_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ms_amazon_s3_connector/static/src/js/amazon.js',
            'ms_amazon_s3_connector/static/src/xml/amazon_dashboard_template.xml',
            'ms_amazon_s3_connector/static/src/scss/amazon.scss',
        ],
    },
    'images': [
        'static/description/banner.gif',
        'static/description/icon.png',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'AGPL-3',
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
}
