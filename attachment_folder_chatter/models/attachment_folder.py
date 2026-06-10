from odoo import models, fields, api, _


class AttachmentFolder(models.Model):
    _name = "attachment.folder"
    _description = "Carpeta de adjuntos"
    _order = "sequence, name, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    sale_order_id = fields.Many2one(
        "sale.order",
        string="Pedido de venta",
        ondelete="cascade",
        index=True,
    )

    project_task_id = fields.Many2one(
        "project.task",
        string="Tarea",
        ondelete="cascade",
        index=True,
    )

    res_model = fields.Char(string="Modelo", index=True)
    res_id = fields.Integer(string="ID del registro", index=True)

    parent_id = fields.Many2one(
        "attachment.folder",
        string="Carpeta padre",
        ondelete="cascade",
        index=True,
    )
    child_ids = fields.One2many(
        "attachment.folder",
        "parent_id",
        string="Subcarpetas",
    )

    attachment_ids = fields.One2many(
        "ir.attachment",
        "folder_id",
        string="Adjuntos",
    )

    attachment_count = fields.Integer(
        string="Nº adjuntos",
        compute="_compute_attachment_count",
    )

    full_name = fields.Char(
        string="Ruta",
        compute="_compute_full_name",
        store=True,
    )

    @api.depends("attachment_ids")
    def _compute_attachment_count(self):
        for folder in self:
            folder.attachment_count = len(folder.attachment_ids)

    @api.depends("name", "parent_id.full_name")
    def _compute_full_name(self):
        for folder in self:
            if folder.parent_id:
                folder.full_name = "%s / %s" % (folder.parent_id.full_name, folder.name)
            else:
                folder.full_name = folder.name or ""

    def _get_linked_record_values(self):
        self.ensure_one()
        if self.sale_order_id:
            return {"res_model": "sale.order", "res_id": self.sale_order_id.id}
        if self.project_task_id:
            return {"res_model": "project.task", "res_id": self.project_task_id.id}
        return {}

    @api.onchange("sale_order_id", "project_task_id")
    def _onchange_linked_record(self):
        for folder in self:
            values = folder._get_linked_record_values()
            if values:
                folder.res_model = values["res_model"]
                folder.res_id = values["res_id"]

    @api.onchange("parent_id")
    def _onchange_parent_id(self):
        for folder in self:
            if folder.parent_id:
                folder.sale_order_id = folder.parent_id.sale_order_id
                folder.project_task_id = folder.parent_id.project_task_id
                folder.res_model = folder.parent_id.res_model
                folder.res_id = folder.parent_id.res_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            parent_id = vals.get("parent_id")
            if parent_id:
                parent = self.env["attachment.folder"].browse(parent_id)
                if parent.exists():
                    vals.setdefault("sale_order_id", parent.sale_order_id.id)
                    vals.setdefault("project_task_id", parent.project_task_id.id)
                    vals.setdefault("res_model", parent.res_model)
                    vals.setdefault("res_id", parent.res_id)

            sale_order_id = vals.get("sale_order_id")
            project_task_id = vals.get("project_task_id")
            if sale_order_id:
                vals["res_model"] = "sale.order"
                vals["res_id"] = sale_order_id
                vals["project_task_id"] = False
            elif project_task_id:
                vals["res_model"] = "project.task"
                vals["res_id"] = project_task_id
                vals["sale_order_id"] = False
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if vals.get("sale_order_id"):
            vals["res_model"] = "sale.order"
            vals["res_id"] = vals["sale_order_id"]
            vals["project_task_id"] = False
        elif vals.get("project_task_id"):
            vals["res_model"] = "project.task"
            vals["res_id"] = vals["project_task_id"]
            vals["sale_order_id"] = False
        return super().write(vals)

    def action_open_attachments(self):
        self.ensure_one()
        kanban_view = self.env.ref(
            "attachment_folder_chatter.view_ir_attachment_folder_kanban",
            raise_if_not_found=False,
        )
        list_view = self.env.ref(
            "attachment_folder_chatter.view_ir_attachment_folder_list",
            raise_if_not_found=False,
        )
        form_view = self.env.ref(
            "attachment_folder_chatter.view_ir_attachment_folder_form",
            raise_if_not_found=False,
        )

        views = []
        if kanban_view:
            views.append((kanban_view.id, "kanban"))
        if list_view:
            views.append((list_view.id, "list"))
        if form_view:
            views.append((form_view.id, "form"))

        return {
            "type": "ir.actions.act_window",
            "name": _("Adjuntos de %s") % self.name,
            "res_model": "ir.attachment",
            "view_mode": "kanban,list,form",
            "views": views,
            "domain": [("folder_id", "=", self.id)],
            "context": {
                "default_folder_id": self.id,
                "default_res_model": self.res_model,
                "default_res_id": self.res_id,
            },
        }

    def action_open_folder_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "attachment.folder",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }
    def action_open_upload_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Subir archivos a %s") % self.name,
            "res_model": "attachment.folder.upload.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_folder_id": self.id,
            },
        }

