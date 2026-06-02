from odoo import api, models
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format


class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def _owa_phone_format(self, fpath=None, number=None):
        """Format a phone number for WhatsApp using the best possible country."""
        self.ensure_one()
        if fpath:
            phone_record_path, phone_record_field = fpath.rsplit('.', 1) if '.' in fpath else ('', fpath)
            phone_record = self.mapped(phone_record_path) if phone_record_path else self
            country_field = phone_record._phone_get_country_field() if hasattr(phone_record, '_phone_get_country_field') else None
            country = phone_record[country_field] if country_field and country_field in phone_record._fields else None
        else:
            country = None

        raw_number = (next(iter(self.mapped(fpath)), None) if fpath else number) or ''
        return wa_phone_format(self.env, raw_number, country=country)

    def _owa_get_responsible(self, related_message=False, related_record=False, whatsapp_account=False):
        """Find suitable responsible users for a WhatsApp conversation.

        Heuristic:
        1. user_id/user_ids field on the record
        2. Author of the original message
        3. Record creator / last editor
        4. Account's notify_user_ids (fallback)
        """
        self.ensure_one()
        responsible = self.env['res.users']

        def is_suitable(user):
            return user.active and user._is_internal() and not user._is_superuser()

        for field in ['user_id', 'user_ids']:
            if field in self._fields and self[field]:
                responsible = self[field].filtered(is_suitable)

        if related_message:
            responsible |= related_message.author_id.user_ids.filtered(is_suitable)

        if responsible:
            return responsible

        if related_message and not related_record:
            related_record = self.env[related_message.model].browse(related_message.res_id)

        if related_record:
            responsible = related_record.create_uid.filtered(is_suitable)
            if not responsible:
                responsible = related_record.write_uid.filtered(is_suitable)

        if not responsible:
            if not whatsapp_account:
                whatsapp_account = self.env['owa.account'].search([], limit=1)
            responsible = whatsapp_account.notify_user_ids

        return responsible
