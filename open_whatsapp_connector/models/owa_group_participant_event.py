"""Phase B2: WhatsApp group participants change audit log.

The sidecar subscribes to the gateway's `group-participants.update` event and
POSTs each transition to /webhook/group_participants. We persist one row
per event so admins have a full join/leave/promote/demote audit trail,
and post a chatter line on the matching Discuss WhatsApp group channel.
"""
import logging

from markupsafe import Markup

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

_ACTION_LABEL = {
    'add': _("joined"),
    'remove': _("left"),
    'promote': _("was promoted to admin"),
    'demote': _("was demoted from admin"),
}


class OwaGroupParticipantEvent(models.Model):
    _name = 'owa.group.participant.event'
    _description = 'WhatsApp Group Participant Event'
    _order = 'create_date desc, id desc'
    _rec_name = 'display_name'

    wa_account_id = fields.Many2one(
        'owa.account', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True)
    channel_id = fields.Many2one('discuss.channel', index=True)
    group_jid = fields.Char(string='WhatsApp Group JID', required=True, index=True)
    action = fields.Selection([
        ('add',     'Member added'),
        ('remove',  'Member removed'),
        ('promote', 'Promoted to admin'),
        ('demote',  'Demoted from admin'),
    ], required=True, index=True)
    participants_jids = fields.Char(
        string='Affected JIDs',
        help='Comma-separated list of WhatsApp JIDs this event applied to.')
    author_jid = fields.Char(
        string='Author JID',
        help='WhatsApp JID of the admin who performed the action.')
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('action', 'participants_jids', 'group_jid')
    def _compute_display_name(self):
        for rec in self:
            participants = (rec.participants_jids or '').split(',')
            participants = [p.strip() for p in participants if p.strip()]
            label = dict(self._fields['action'].selection).get(rec.action, rec.action)
            who = participants[0] if participants else '?'
            if len(participants) > 1:
                who = f"{who} (+{len(participants) - 1})"
            rec.display_name = f"{rec.group_jid} · {label} · {who}"

    @api.model
    def _record_event(self, account, group_jid, action, participants, author=None):
        if not group_jid or action not in dict(self._fields['action'].selection):
            return False
        Channel = self.env['discuss.channel'].sudo()
        channel = Channel.search([
            ('owa_account_id', '=', account.id),
            ('whatsapp_number', '=', group_jid),
            ('channel_type', '=', 'whatsapp'),
        ], limit=1)
        rec = self.create({
            'wa_account_id': account.id,
            'channel_id': channel.id if channel else False,
            'group_jid': group_jid,
            'action': action,
            'participants_jids': ','.join(participants or []),
            'author_jid': author or False,
        })
        # Keep the per-group session participant count fresh.
        if channel:
            session = self.env['owa.group.session'].sudo().search(
                [('channel_id', '=', channel.id)], limit=1)
            if session and session.participant_count:
                delta = (
                    len(participants or []) if action == 'add'
                    else -len(participants or []) if action == 'remove'
                    else 0
                )
                if delta:
                    session.write({
                        'participant_count': max(0, session.participant_count + delta),
                    })
        # Post a chatter line on the group's discuss.channel.
        if channel:
            self._post_chatter(channel, action, participants or [], author)
        return rec

    @staticmethod
    def _strip_jid(jid):
        if not jid:
            return '?'
        before_at = jid.split('@', 1)[0]
        # Drop multi-device suffix `:NN`.
        return before_at.split(':', 1)[0]

    def _post_chatter(self, channel, action, participants, author):
        verb = _ACTION_LABEL.get(action, action)
        names = ', '.join('+' + self._strip_jid(p) for p in participants if p)
        author_label = '+' + self._strip_jid(author) if author else _("Someone")
        if action in ('add', 'remove'):
            body = Markup('<p><strong>{names}</strong> {verb} the WhatsApp group · by {author}</p>').format(
                names=names or '?', verb=verb, author=author_label,
            )
        else:
            body = Markup('<p><strong>{names}</strong> {verb} · by {author}</p>').format(
                names=names or '?', verb=verb, author=author_label,
            )
        try:
            channel.message_post(
                body=body,
                message_type='notification',
                subtype_xmlid='mail.mt_note',
                author_id=self.env.ref('base.partner_root').id,
            )
        except Exception:  # pragma: no cover -- chatter post is best-effort
            _logger.exception(
                "owa.group.participant.event: chatter post failed for jid=%s",
                channel.whatsapp_number,
            )
