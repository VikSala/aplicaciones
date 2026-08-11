from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    s3_attachment_bucket = fields.Char(
        string="S3 Bucket",
        config_parameter="s3_attachment.bucket",
        groups="base.group_system",
    )
    s3_attachment_access_key_id = fields.Char(
        string="Access Key ID",
        config_parameter="s3_attachment.access_key_id",
        groups="base.group_system",
    )
    s3_attachment_secret_access_key = fields.Char(
        string="Secret Access Key",
        config_parameter="s3_attachment.secret_access_key",
        groups="base.group_system",
    )
    s3_attachment_endpoint_url = fields.Char(
        string="Endpoint URL",
        config_parameter="s3_attachment.endpoint_url",
        groups="base.group_system",
        help="Leave empty for AWS S3. Set for S3-compatible services (e.g. MinIO, Backblaze B2, DigitalOcean Spaces).",
    )
    s3_attachment_region = fields.Char(
        string="Region",
        config_parameter="s3_attachment.region",
        groups="base.group_system",
        help="AWS region (e.g. us-east-1) or provider region code.",
    )
    s3_attachment_key_prefix = fields.Char(
        string="Object Key Prefix",
        config_parameter="s3_attachment.key_prefix",
        groups="base.group_system",
        help="Optional path prefix applied to every S3 object key from this "
        "instance. Leave empty unless multiple Odoo databases share one "
        "bucket — then set a distinct prefix per instance (e.g. \"prod-a\") "
        "so each instance's garbage collection only touches its own objects. "
        "Reads fall back to un-prefixed keys, so existing objects stay "
        "accessible after you set a prefix.",
    )
    s3_attachment_production_only = fields.Boolean(
        string="Production Only",
        config_parameter="s3_attachment.production_only",
        groups="base.group_system",
        help="When enabled, S3 is only used on production Odoo SH builds. "
        "Staging and dev builds will use local storage for writes and deletes, "
        "but can still read from S3.",
    )
