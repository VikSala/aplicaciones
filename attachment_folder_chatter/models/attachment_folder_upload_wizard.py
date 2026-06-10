from odoo import models, fields, _
from odoo.exceptions import UserError


class AttachmentFolderUploadWizard(models.TransientModel):
    _name = "attachment.folder.upload.wizard"
    _description = "Subir varios adjuntos a una carpeta"

    folder_id = fields.Many2one(
        "attachment.folder",
        string="Carpeta",
        required=True,
        readonly=True,
    )

    attachment_ids = fields.Many2many(
        "ir.attachment",
        "attachment_folder_upload_wizard_ir_attachment_rel",
        "wizard_id",
        "attachment_id",
        string="Archivos",
        help="Selecciona o arrastra varios archivos para subirlos a la carpeta.",
    )

    def action_upload_files(self):
        self.ensure_one()
        if not self.attachment_ids:
            raise UserError(_("Debes seleccionar al menos un archivo."))

        folder = self.folder_id
        vals = {
            "folder_id": folder.id,
            "res_model": folder.res_model,
            "res_id": folder.res_id,
        }
        self.attachment_ids.write(vals)

        return folder.action_open_attachments()
