from odoo import models, fields


class ProjectTask(models.Model):
    _inherit = "project.task"

    attachment_folder_ids = fields.One2many(
        "attachment.folder",
        "project_task_id",
        string="Carpetas de adjuntos",
    )
