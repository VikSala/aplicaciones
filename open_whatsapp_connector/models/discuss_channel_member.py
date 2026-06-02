from datetime import datetime, timedelta

from odoo import api, models
from odoo.osv import expression
from odoo.addons.mail.tools.discuss import Store


class DiscussChannelMember(models.Model):
    _inherit = 'discuss.channel.member'

    @api.autovacuum
    def _gc_unpin_whatsapp_channels(self):
        """Unpin read WhatsApp channels with no activity for at least 1 day."""
        one_day_ago = datetime.now() - timedelta(days=1)
        five_days_ago = datetime.now() - timedelta(days=5)
        members = self.search(expression.AND([
            [("is_pinned", "=", True)],
            [("channel_id.channel_type", "=", "whatsapp")],
            expression.OR([
                [("last_seen_dt", "<", one_day_ago)],
                [
                    ("last_seen_dt", "=", False),
                    ("channel_id.create_date", "<=", five_days_ago),
                ],
            ]),
        ]), limit=1000)
        members_to_unpin = members.filtered(
            lambda m: m.message_unread_counter == 0
            or (not m.last_seen_dt and m.channel_id.create_date <= five_days_ago)
            or m.last_seen_dt <= five_days_ago
        )
        members_to_unpin.unpin_dt = datetime.now()
        for member in members_to_unpin:
            # v18-compat: Store(bus_channel=...).bus_send() is v19-only; use _bus_send_store
            member._bus_channel()._bus_send_store(
                member.channel_id, {"close_chat_window": True}
            )
