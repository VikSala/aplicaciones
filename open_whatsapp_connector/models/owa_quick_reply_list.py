import uuid

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OwaQuickReplyListSection(models.Model):
    _name = 'owa.quick.reply.list.section'
    _description = 'WhatsApp Quick Reply List Section'
    _order = 'sequence, id'

    quick_reply_id = fields.Many2one(
        'owa.quick.reply', string="Quick Reply",
        required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    title = fields.Char(string="Section Title", required=True)
    row_ids = fields.One2many(
        'owa.quick.reply.list.row', 'section_id', string="Rows")


class OwaQuickReplyListRow(models.Model):
    _name = 'owa.quick.reply.list.row'
    _description = 'WhatsApp Quick Reply List Row'
    _order = 'sequence, id'

    section_id = fields.Many2one(
        'owa.quick.reply.list.section', string="Section",
        required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    title = fields.Char(
        string="Row Title", required=True,
        help="Max 24 characters")
    description = fields.Char(
        string="Description",
        help="Max 72 characters")
    row_id = fields.Char(
        string="Row ID",
        help="Unique ID for this row. Auto-generated if empty.")

    @api.constrains('title')
    def _check_title_length(self):
        for row in self:
            if row.title and len(row.title) > 24:
                raise ValidationError(
                    _("Row title '%(title)s' exceeds 24 characters (%(length)d).",
                      title=row.title, length=len(row.title)))

    @api.constrains('description')
    def _check_description_length(self):
        for row in self:
            if row.description and len(row.description) > 72:
                raise ValidationError(
                    _("Row description exceeds 72 characters (%(length)d).",
                      length=len(row.description)))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('row_id'):
                vals['row_id'] = uuid.uuid4().hex[:12]
        return super().create(vals_list)
