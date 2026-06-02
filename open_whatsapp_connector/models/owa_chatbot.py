import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format

_logger = logging.getLogger(__name__)


class OwaChatbot(models.Model):
    _name = 'owa.chatbot'
    _description = 'WhatsApp Chatbot'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'

    name = fields.Char(string="Chatbot Name", required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)
    wa_account_id = fields.Many2one('owa.account', string="WhatsApp Account",
        help="Required before the chatbot can be activated. Pre-built starter "
             "bots ship without an account so you just pick one and tick Active.")
    welcome_message = fields.Text(string="Welcome Message",
        default="Hello! How can I help you today?",
        help="Sent when the chatbot first engages with a contact")
    step_ids = fields.One2many('owa.chatbot.step', 'chatbot_id', string="Steps")
    first_step_id = fields.Many2one('owa.chatbot.step', string="First Step",
        compute='_compute_first_step_id')
    session_timeout_minutes = fields.Integer(string="Session Timeout (minutes)",
        default=30, help="Chatbot session expires after this many minutes of inactivity")

    @api.depends('step_ids.sequence')
    def _compute_first_step_id(self):
        for bot in self:
            bot.first_step_id = bot.step_ids[:1] if bot.step_ids else False

    @api.constrains('active', 'wa_account_id')
    def _check_account_required_when_active(self):
        # wa_account_id is optional so pre-built starter bots can ship without
        # an account, but a bot cannot actually run until one is assigned.
        for bot in self:
            if bot.active and not bot.wa_account_id:
                raise ValidationError(_(
                    "Select a WhatsApp account before activating this chatbot."
                ))

    @api.constrains('active', 'wa_account_id')
    def _check_single_active_per_account(self):
        for bot in self:
            if not bot.active or not bot.wa_account_id:
                continue
            if self.search_count([
                ('id', '!=', bot.id),
                ('active', '=', True),
                ('wa_account_id', '=', bot.wa_account_id.id),
            ]):
                raise ValidationError(_(
                    "Only one chatbot can be active per WhatsApp account. "
                    "Deactivate the other chatbot first."
                ))

    def _start_session(self, from_number):
        """Start a new chatbot session for a contact."""
        self.ensure_one()
        formatted_phone = wa_phone_format(self.env, from_number) or from_number
        # Close any existing active session (match either the formatted or raw
        # phone so legacy unformatted sessions are still found).
        existing = self.env['owa.chatbot.session'].search([
            ('chatbot_id', '=', self.id),
            '|', ('phone_number', '=', formatted_phone),
                 ('phone_number', '=', from_number),
            ('state', '=', 'active'),
        ])
        existing.write({'state': 'expired'})

        session = self.env['owa.chatbot.session'].create({
            'chatbot_id': self.id,
            'phone_number': formatted_phone,
            'current_step_id': self.first_step_id.id if self.first_step_id else False,
            'state': 'active',
        })

        # Send welcome message
        if self.welcome_message:
            self._send_bot_message(from_number, self.welcome_message)

        # Send first step if exists
        if self.first_step_id:
            self.first_step_id._present_step(from_number)

        return session

    def _send_bot_message(self, to_number, text):
        """Queue a chatbot message via owa.message so it gets the same audit
        trail and status tracking as other outbound messages."""
        self.ensure_one()
        if not text:
            return
        if not self.wa_account_id or self.wa_account_id.session_state != 'connected':
            return
        formatted_phone = wa_phone_format(self.env, to_number) or to_number

        mail_message = self.env['mail.message'].create({
            'body': text,
            'message_type': 'whatsapp_message',
        })
        self.env['owa.message'].create({
            'mobile_number': formatted_phone,
            'message_type': 'outbound',
            'state': 'outgoing',
            'wa_account_id': self.wa_account_id.id,
            'mail_message_id': mail_message.id,
        })
        cron = self.env.ref(
            'open_whatsapp_connector.ir_cron_send_owa_queue',
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()


class OwaChatbotStep(models.Model):
    _name = 'owa.chatbot.step'
    _description = 'Chatbot Step'
    _order = 'sequence, id'

    chatbot_id = fields.Many2one('owa.chatbot', string="Chatbot",
        required=True, ondelete='cascade')
    name = fields.Char(string="Step Name", required=True)
    sequence = fields.Integer(default=10)

    step_type = fields.Selection([
        ('message', 'Send Message'),
        ('menu', 'Show Menu'),
        ('route_to_user', 'Route to User'),
        ('create_lead', 'Create CRM Lead'),
        ('end', 'End Conversation'),
    ], string="Step Type", required=True, default='menu')

    # Message content
    message = fields.Text(string="Message",
        help="Message to send at this step")

    # Menu options
    option_ids = fields.One2many('owa.chatbot.menu.option', 'step_id',
        string="Menu Options")

    # Routing
    target_user_id = fields.Many2one('res.users', string="Route to User",
        domain=[('share', '=', False)])
    next_step_id = fields.Many2one('owa.chatbot.step', string="Next Step",
        help="For 'message' type: auto-advance to this step")

    _MAX_AUTO_ADVANCE = 20

    def _present_step(self, from_number):
        """Present this step (and any auto-advancing successors) to the user.

        ``message`` and ``create_lead`` step types auto-advance via
        ``next_step_id``. We walk that chain iteratively with a depth cap and
        a visited-set so a user-configured cycle can't recurse forever.
        """
        self.ensure_one()
        formatted_phone = wa_phone_format(self.env, from_number) or from_number
        visited = set()
        step = self
        for _ in range(self._MAX_AUTO_ADVANCE):
            if step.id in visited:
                _logger.warning(
                    "Chatbot '%s' has a cycle starting at step %s; aborting auto-advance",
                    step.chatbot_id.name, step.id,
                )
                return
            visited.add(step.id)

            if step.step_type == 'message':
                if step.message:
                    step.chatbot_id._send_bot_message(from_number, step.message)
                if step.next_step_id:
                    step = step.next_step_id
                    continue
                return

            if step.step_type == 'menu':
                text = step.message or ''
                if step.option_ids:
                    options_text = '\n'.join(
                        f'{i}. {opt.label}'
                        for i, opt in enumerate(step.option_ids.sorted('sequence'), 1)
                    )
                    text = f"{text}\n\n{options_text}" if text else options_text
                if text:
                    step.chatbot_id._send_bot_message(from_number, text)
                return

            if step.step_type == 'route_to_user':
                if step.message:
                    step.chatbot_id._send_bot_message(from_number, step.message)
                session = self.env['owa.chatbot.session'].search([
                    ('chatbot_id', '=', step.chatbot_id.id),
                    ('phone_number', '=', formatted_phone),
                    ('state', '=', 'active'),
                ], limit=1)
                if session:
                    session.state = 'routed'
                # Actually route to the configured agent: subscribe, assign and
                # alert them on the live Discuss channel. target_user_id used to
                # be declared but never read, so "route to user" notified
                # nobody. (#chatbot)
                if step.target_user_id and step.target_user_id.active:
                    step._route_to_agent(formatted_phone, step.target_user_id)
                return

            if step.step_type == 'create_lead':
                step._create_crm_lead(from_number)
                if step.message:
                    step.chatbot_id._send_bot_message(from_number, step.message)
                if step.next_step_id:
                    step = step.next_step_id
                    continue
                return

            if step.step_type == 'end':
                if step.message:
                    step.chatbot_id._send_bot_message(from_number, step.message)
                session = self.env['owa.chatbot.session'].search([
                    ('chatbot_id', '=', step.chatbot_id.id),
                    ('phone_number', '=', formatted_phone),
                    ('state', '=', 'active'),
                ], limit=1)
                if session:
                    session.state = 'completed'
                return

            return  # unknown step_type — stop

        _logger.warning(
            "Chatbot '%s' hit max auto-advance depth (%d) at step %s",
            step.chatbot_id.name, self._MAX_AUTO_ADVANCE, step.id,
        )

    def _route_to_agent(self, formatted_phone, agent):
        """Subscribe the configured agent to the WhatsApp Discuss channel,
        assign it to them, post an internal note and schedule a to-do so the
        named user is genuinely alerted. No-op if the channel isn't found."""
        self.ensure_one()
        account = self.chatbot_id.wa_account_id
        channel = self.env['discuss.channel'].sudo().search([
            ('channel_type', '=', 'whatsapp'),
            ('whatsapp_number', '=', formatted_phone),
            ('owa_account_id', '=', account.id),
        ], limit=1)
        if not channel:
            return
        if agent.partner_id:
            try:
                channel.add_members(partner_ids=agent.partner_id.ids)
            except Exception:
                _logger.exception(
                    "chatbot route: add_members failed for agent %s channel %s",
                    agent.id, channel.id)
        vals = {}
        if 'assignee_id' in channel._fields and not channel.assignee_id:
            vals['assignee_id'] = agent.id
        if 'triage_state' in channel._fields and channel.triage_state != 'resolved':
            vals['triage_state'] = 'active'
        if 'assigned_at' in channel._fields and not channel.assigned_at:
            vals['assigned_at'] = fields.Datetime.now()
        if vals:
            channel.write(vals)
        # Internal note (message_type='comment' -> goes through the base
        # message_post, never sent out to WhatsApp).
        channel.message_post(
            body=_("Chatbot routed this conversation to %s.") % agent.display_name,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        try:
            channel.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=agent.id,
                summary=_("WhatsApp conversation routed to you"),
            )
        except Exception:
            _logger.exception(
                "chatbot route: activity_schedule failed for channel %s", channel.id)

    def _create_crm_lead(self, from_number):
        """Create a CRM lead from the chatbot conversation."""
        self.ensure_one()
        if 'crm.lead' not in self.env:
            _logger.warning("CRM module not installed, cannot create lead")
            return
        formatted = wa_phone_format(self.env, from_number) or from_number
        partner = self.env['res.partner'].search([
            '|', ('phone', '=', formatted), ('phone', '=', from_number),
        ], limit=1)
        self.env['crm.lead'].create({
            'name': f'WhatsApp Lead - {partner.name if partner else formatted}',
            'partner_id': partner.id if partner else False,
            'phone': formatted,
            'description': f'Lead created from WhatsApp chatbot "{self.chatbot_id.name}"',
        })

    def _process_user_input(self, from_number, message_text):
        """Process user input for this step and return the next step."""
        self.ensure_one()
        if self.step_type == 'menu' and self.option_ids:
            options = self.option_ids.sorted('sequence')
            # Match an interactive tap echo, a bare number, or the option label.
            from odoo.addons.open_whatsapp_connector.tools.menu_match import (
                match_menu_choice)
            idx = match_menu_choice([o.label for o in options], message_text)
            if idx is None:
                # Fall back to a per-option keyword match.
                low = (message_text or '').strip().lower()
                for j, option in enumerate(options):
                    if option.keyword and low == option.keyword.lower():
                        idx = j
                        break
            if idx is not None and 0 <= idx < len(options):
                return options[idx].next_step_id
            # No match — re-present the menu
            self.chatbot_id._send_bot_message(
                from_number,
                _("Sorry, I didn't understand that. Please choose from the options above.")
            )
            self._present_step(from_number)
            return None

        # For non-menu steps, just advance to next
        return self.next_step_id


class OwaChatbotMenuOption(models.Model):
    _name = 'owa.chatbot.menu.option'
    _description = 'Chatbot Menu Option'
    _order = 'sequence, id'

    step_id = fields.Many2one('owa.chatbot.step', string="Step",
        required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    label = fields.Char(string="Label", required=True,
        help="Text shown to user, e.g. '1. Sales' or '2. Support'")
    keyword = fields.Char(string="Keyword",
        help="Keyword that also triggers this option (e.g. 'sales')")
    next_step_id = fields.Many2one('owa.chatbot.step', string="Next Step",
        required=True, ondelete='cascade')


class OwaChatbotSession(models.Model):
    _name = 'owa.chatbot.session'
    _description = 'Chatbot Session'
    _order = 'id desc'

    chatbot_id = fields.Many2one('owa.chatbot', string="Chatbot",
        required=True, ondelete='cascade')
    phone_number = fields.Char(string="Phone Number", required=True, index=True)
    current_step_id = fields.Many2one('owa.chatbot.step', string="Current Step")
    state = fields.Selection([
        ('active', 'Active'),
        ('routed', 'Routed to Agent'),
        ('completed', 'Completed'),
        ('expired', 'Expired'),
    ], string="State", default='active', required=True)
    last_activity = fields.Datetime(string="Last Activity",
        default=fields.Datetime.now)

    def _process_message(self, message_text):
        """Process an incoming message in this session."""
        self.ensure_one()
        if self.state != 'active':
            return False

        # Update last activity
        self.last_activity = fields.Datetime.now()

        if not self.current_step_id:
            return False

        next_step = self.current_step_id._process_user_input(
            self.phone_number, message_text)

        if next_step:
            self.current_step_id = next_step
            next_step._present_step(self.phone_number)

        return True

    @api.model
    def _cron_expire_sessions(self):
        """Expire inactive chatbot sessions."""
        bots = self.env['owa.chatbot'].search([('active', '=', True)])
        for bot in bots:
            timeout = timedelta(minutes=bot.session_timeout_minutes or 30)
            threshold = fields.Datetime.now() - timeout
            sessions = self.search([
                ('chatbot_id', '=', bot.id),
                ('state', '=', 'active'),
                ('last_activity', '<', threshold),
            ])
            if sessions:
                sessions.write({'state': 'expired'})
                _logger.info("Expired %d chatbot sessions for '%s'",
                           len(sessions), bot.name)
