import uuid

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OwaQuickReplyButton(models.Model):
    _name = 'owa.quick.reply.button'
    _description = 'WhatsApp Quick Reply Button'
    _order = 'sequence, id'

    quick_reply_id = fields.Many2one(
        'owa.quick.reply', string="Quick Reply",
        required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    text = fields.Char(
        string="Button Text", required=True,
        help="Max 20 characters")
    button_id = fields.Char(
        string="Button ID",
        help="Unique ID for this button. Auto-generated if empty.")

    @api.constrains('text')
    def _check_text_length(self):
        for btn in self:
            if btn.text and len(btn.text) > 20:
                raise ValidationError(
                    _("Button text '%(text)s' exceeds 20 characters (%(length)d).",
                      text=btn.text, length=len(btn.text)))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('button_id'):
                vals['button_id'] = uuid.uuid4().hex[:12]
        return super().create(vals_list)
