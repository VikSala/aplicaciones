from odoo import models, fields, api


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    folder_id = fields.Many2one(
        "attachment.folder",
        string="Carpeta",
        ondelete="set null",
        index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            folder_id = vals.get("folder_id")
            if folder_id:
                folder = self.env["attachment.folder"].browse(folder_id)
                if folder.exists():
                    vals.setdefault("res_model", folder.res_model)
                    vals.setdefault("res_id", folder.res_id)
        return super().create(vals_list)
