{
    "name": "S3 Attachment Storage",
    "summary": "Store and manage Odoo attachments in Amazon S3 or any S3-compatible object storage",
    "description": """
Store Odoo file attachments in Amazon S3 or S3-compatible cloud storage (MinIO, DigitalOcean Spaces, Wasabi, etc.).

Key Features:
- Automatically redirects all Odoo attachment storage to your S3 bucket
- Compatible with any S3-compatible object storage provider
- Graceful fallback to local filesystem if S3 is unreachable
- Built-in retry logic with exponential backoff for reliable uploads
- Simple configuration via environment variables or system settings
- No changes needed to existing Odoo workflows — works transparently

Ideal for companies looking to reduce server disk usage, improve backup strategies, or scale Odoo deployments with cloud-native file storage.
""",
    "author": "Alpenglow Technologies LLC",
    "version": "18.0.1.0.5",
    "category": "Tools",
    "license": "OPL-1",
    "depends": ["base", "web", "base_setup"],
    "data": [
        "views/res_config_settings_views.xml",
        "data/ir_cron.xml",
    ],
    'images': ['static/description/main_screenshot.png'],
    "installable": True,
    "auto_install": False,
    "application": False,
    "price": 20,
    "currency": "USD",
}
