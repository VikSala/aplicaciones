from odoo import models, fields


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    is_file_uploaded = fields.Boolean(string='File Uploaded', default=False)
    s3_uploaded_account_ids = fields.Many2many(
        'amazon.s3.account',
        'ir_attachment_s3_account_rel',
        'attachment_id',
        'account_id',
        string='Uploaded to S3 Accounts',
    )
