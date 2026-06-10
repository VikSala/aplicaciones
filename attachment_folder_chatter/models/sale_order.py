from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = "sale.order"

    attachment_folder_ids = fields.One2many(
        "attachment.folder",
        "sale_order_id",
        string="Carpetas de adjuntos",
    )
