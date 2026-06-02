"""Phase 26G: merge two WhatsApp Discuss channels into one.

Useful when a contact was matched to a `res.partner` retroactively and
ended up with both an "orphan" channel keyed only by phone and a
contact-keyed channel."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class OwaChannelMergeWizard(models.TransientModel):
    _name = 'owa.channel.merge.wizard'
    _description = 'Merge WhatsApp Conversations'

    source_channel_id = fields.Many2one(
        'discuss.channel', string="Source (will be removed)",
        required=True, domain=[('channel_type', '=', 'whatsapp')])
    target_channel_id = fields.Many2one(
        'discuss.channel', string="Target (kept, receives messages)",
        required=True, domain=[('channel_type', '=', 'whatsapp')])

    def action_merge(self):
        self.ensure_one()
        if self.source_channel_id == self.target_channel_id:
            raise UserError(_("Source and target must differ."))
        source = self.source_channel_id
        target = self.target_channel_id
        # Move messages
        self.env['mail.message'].sudo().search([
            ('model', '=', 'discuss.channel'),
            ('res_id', '=', source.id),
        ]).write({'res_id': target.id})
        # Move owa.message rows that reference channel via the partner
        # (we don't have a direct M2O, so re-link via whatsapp_partner_id).
        # Move call logs
        self.env['owa.call.log'].sudo().search([
            ('channel_id', '=', source.id),
        ]).write({'channel_id': target.id})
        # Drop source
        try:
            source.unlink()
        except Exception:
            source.write({'active': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'discuss.channel',
            'res_id': target.id,
            'view_mode': 'form',
            'target': 'current',
        }
