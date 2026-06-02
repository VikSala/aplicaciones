import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class OwaSlashCommand(models.Model):
    """Phase 9 — pluggable chat-side slash command registry.

    A WhatsApp recipient types ``/menu``, ``/stop``, ``/agent`` etc. and the
    inbound webhook routes the message to the matching record's handler
    instead of the normal chatbot/auto-reply pipeline.

    Built-in handlers live as Python methods on this model; the records
    themselves point at one of those methods by name. Third-party modules
    can either add their own records pointing at custom Python methods on
    other models, or replace the built-in handler implementation by
    inheriting and overriding.
    """
    _name = 'owa.slash.command'
    _description = 'WhatsApp Slash Command'
    _order = 'sequence, command'

    name = fields.Char(string="Display name", required=True)
    command = fields.Char(
        string="Command", required=True, index=True,
        help="The literal slash command, e.g. '/menu' or '/stop'. "
             "Case-insensitive at match time.")
    sequence = fields.Integer(default=10)
    description = fields.Char(
        string="Help text",
        help="One-line description shown by /help.")
    active = fields.Boolean(default=True)
    handler = fields.Selection([
        ('help', '/help — list available commands'),
        ('menu', '/menu — re-trigger the active chatbot'),
        ('stop', '/stop — opt out (add to blacklist)'),
        ('agent', '/agent — escalate to a human'),
    ], required=True, default='help')

    _sql_constraints = [
        ('command_uniq',
         'UNIQUE(command)',
         'Slash command must be unique.'),
    ]

    @api.model
    def parse_and_dispatch(self, account, from_number, body, channel):
        """If body starts with a slash, look up the matching command and run
        the handler. Returns True iff the command was handled (and the normal
        chatbot/auto-reply pipeline should be skipped)."""
        if not body:
            return False
        text = body.strip()
        if not text.startswith('/'):
            return False
        first = text.split(None, 1)[0].lower()
        cmd = self.sudo().search(
            [('command', '=', first), ('active', '=', True)], limit=1,
        )
        if not cmd:
            return False
        try:
            handler = getattr(self, f'_handle_{cmd.handler}', None)
            if handler:
                handler(account, from_number, body, channel)
                return True
        except Exception:
            _logger.exception("Slash-command %s handler failed", cmd.command)
        return False

    # ── Built-in handlers ────────────────────────────────────────────────

    def _send_reply(self, account, from_number, body):
        """Helper: queue a text reply via owa.message + cron trigger."""
        from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format
        formatted = wa_phone_format(self.env, from_number) or from_number
        mail_message = self.env['mail.message'].create({
            'body': body,
            'message_type': 'whatsapp_message',
        })
        self.env['owa.message'].create({
            'mobile_number': formatted,
            'message_type': 'outbound',
            'state': 'outgoing',
            'wa_account_id': account.id,
            'mail_message_id': mail_message.id,
        })
        cron = self.env.ref(
            'open_whatsapp_connector.ir_cron_send_owa_queue',
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()

    def _handle_help(self, account, from_number, body, channel):
        cmds = self.sudo().search([('active', '=', True)])
        lines = ["*Available commands*"]
        for c in cmds:
            lines.append(f"{c.command} — {c.description or c.name}")
        self._send_reply(account, from_number, '\n'.join(lines))

    def _handle_menu(self, account, from_number, body, channel):
        Chatbot = self.env['owa.chatbot'].sudo()
        bot = Chatbot.search([
            ('wa_account_id', '=', account.id), ('active', '=', True),
        ], limit=1)
        if not bot:
            self._send_reply(account, from_number, _("No active chatbot configured."))
            return
        bot._start_session(from_number)

    def _handle_stop(self, account, from_number, body, channel):
        self.env['owa.blacklist'].sudo().add_to_blacklist(
            from_number, reason='User /stop',
        )
        self._send_reply(
            account, from_number,
            _("You've been opted out. Reply /start to opt back in."),
        )

    def _handle_agent(self, account, from_number, body, channel):
        # Mark any active chatbot session as routed-to-human so the bot
        # doesn't fight the agent.
        sessions = self.env['owa.chatbot.session'].sudo().search([
            ('phone_number', '=', from_number), ('state', '=', 'active'),
        ])
        sessions.write({'state': 'routed'})
        self._send_reply(
            account, from_number,
            _("Connecting you to a human agent. Please hold on."),
        )
