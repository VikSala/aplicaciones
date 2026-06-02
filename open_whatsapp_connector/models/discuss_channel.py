import logging

from datetime import timedelta
from markupsafe import Markup

from odoo import api, Command, fields, models, tools, _
from odoo.addons.mail.tools.discuss import Store
from odoo.addons.open_whatsapp_connector.tools.baileys_api import BaileysApi
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


def is_whatsapp_channel(channel):
    return channel.channel_type == "whatsapp"


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    channel_type = fields.Selection(
        selection_add=[('whatsapp', 'WhatsApp Conversation')],
        ondelete={'whatsapp': 'cascade'})
    whatsapp_number = fields.Char(string="Phone Number")
    whatsapp_channel_valid_until = fields.Datetime(
        string="WhatsApp Channel Valid Until",
        compute="_compute_whatsapp_channel_valid_until")
    last_wa_mail_message_id = fields.Many2one(
        comodel_name='mail.message', string="Last WhatsApp Partner Message",
        index='btree_not_null')
    whatsapp_partner_id = fields.Many2one(
        comodel_name='res.partner', string="WhatsApp Partner",
        index='btree_not_null')
    owa_account_id = fields.Many2one(
        comodel_name='owa.account', string="WhatsApp Account")

    # ─── Phase 22A: conversation assignment & inbox triage ────────────
    assignee_id = fields.Many2one(
        'res.users', string="Assignee", index=True, tracking=True,
        help="Salesperson who owns this WhatsApp conversation.")
    # Phase 22A: Sales-Team and Helpdesk-Ticket linkage stored as plain
    # integer ids so the addon installs without crm/helpdesk. Cross-app
    # bridges that depend on those modules can populate these from their
    # own glue addons.
    crm_team_id_int = fields.Integer(
        string="Sales Team id",
        help="Numeric id of a crm.team record, when crm is installed.")
    triage_state = fields.Selection([
        ('unassigned', 'Unassigned'),
        ('active',     'Active'),
        ('on_hold',    'On hold'),
        ('resolved',   'Resolved'),
    ], string="Triage", default='unassigned', tracking=True, index=True)
    sla_due_at = fields.Datetime(
        string="SLA due at", compute='_compute_sla_due_at', store=True,
        help="Computed from assigned_at + the account's sla_minutes.")
    assigned_at = fields.Datetime(string="Assigned at")
    resolved_at = fields.Datetime(string="Resolved at")
    sla_breached = fields.Boolean(
        string="SLA breached", compute='_compute_sla_breached', store=True)

    # ─── Phase 23A: helpdesk bridge ───────────────────────────────────
    helpdesk_ticket_id_int = fields.Integer(
        string="Helpdesk Ticket id",
        help="Numeric id of a helpdesk.ticket record, when the helpdesk "
             "module is installed.")

    # ─── Phase 26B: conversation labels ───────────────────────────────
    wa_label_ids = fields.Many2many(
        'owa.channel.label', 'owa_channel_label_rel',
        'channel_id', 'label_id', string="Labels")
    whatsapp_channel_active = fields.Boolean(
        string="Is WhatsApp Channel Active",
        compute="_compute_whatsapp_channel_active")
    # Phase 6: group support
    is_whatsapp_group = fields.Boolean(
        string="Is WhatsApp group", compute='_compute_is_whatsapp_group', store=True,
        help="Computed True for WhatsApp channels whose JID ends with @g.us.")
    require_mention = fields.Boolean(
        string="Bot requires @mention", default=False,
        help="When set, chatbots and auto-replies in this group only fire when "
             "the bot's name or number is @-mentioned in the inbound text.")
    group_intro_sent = fields.Boolean(
        string="Group intro sent", default=False,
        help="Set after the bot has greeted this group with the configured "
             "intro message; prevents re-sending.")
    member_label = fields.Char(
        string="My display label", size=30,
        help="Custom name (≤30 chars) shown in this WhatsApp group beside the "
             "bot's number. Leave empty to keep the default.")

    def action_push_member_label(self):
        """Push the value of ``member_label`` to WhatsApp. Available only on
        WhatsApp groups. The label is sent as a GROUP_MEMBER_LABEL_CHANGE
        protocol message and applies to the connected account itself."""
        for channel in self:
            if not channel.is_whatsapp_group:
                raise UserError(_("Display label can only be set on WhatsApp groups."))
            if not channel.owa_account_id:
                raise UserError(_("Channel has no linked WhatsApp account."))
            if channel.owa_account_id.session_state != 'connected':
                raise UserError(_("WhatsApp account is not connected."))
            api = BaileysApi(channel.owa_account_id)
            api.update_member_label(channel.whatsapp_number, channel.member_label or '')
        return True

    @api.depends('whatsapp_number', 'channel_type')
    def _compute_is_whatsapp_group(self):
        for ch in self:
            ch.is_whatsapp_group = (
                ch.channel_type == 'whatsapp'
                and (ch.whatsapp_number or '').endswith('@g.us')
            )

    _sql_constraints = [
        ('group_public_id_check',
         "CHECK (channel_type = 'channel' OR channel_type = 'whatsapp' OR group_public_id IS NULL)",
         "Group authorization and group auto-subscription are only supported on channels and whatsapp."),
    ]

    def _auto_init(self):
        """Add a partial unique index so two concurrent inbound webhooks
        on the same (account, number) can't both win the create-channel
        race. Cleanup of existing duplicates must run before this index
        will install — see ``owa.account.cleanup_duplicate_whatsapp_channels``."""
        res = super()._auto_init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS discuss_channel_whatsapp_uniq
            ON discuss_channel (owa_account_id, whatsapp_number)
            WHERE channel_type = 'whatsapp' AND whatsapp_number IS NOT NULL
        """)
        return res

    # ------------------------------------------------------------------
    # COMPUTES
    # ------------------------------------------------------------------

    @api.depends('whatsapp_partner_id', 'whatsapp_number')
    def _compute_display_name(self):
        wa_channels = self.filtered(lambda c: c.channel_type == 'whatsapp' and c.whatsapp_partner_id)
        for channel in wa_channels:
            number = channel.whatsapp_number
            partner = channel.whatsapp_partner_id
            partner_name = partner.name if partner.name != partner.phone else False
            channel.display_name = f'{partner_name} ({number})' if partner_name else number
        super(DiscussChannel, self - wa_channels)._compute_display_name()

    @api.depends('last_wa_mail_message_id')
    def _compute_whatsapp_channel_valid_until(self):
        for channel in self:
            if channel.channel_type == "whatsapp" and channel.last_wa_mail_message_id:
                # The gateway has no 24h limit, but we keep this for UI consistency
                # Set a generous window (7 days) since the gateway can send anytime
                channel.whatsapp_channel_valid_until = (
                    channel.last_wa_mail_message_id.create_date + timedelta(days=7)
                )
            else:
                channel.whatsapp_channel_valid_until = False

    @api.depends('whatsapp_channel_valid_until')
    def _compute_whatsapp_channel_active(self):
        for channel in self:
            channel.whatsapp_channel_active = (
                channel.whatsapp_channel_valid_until
                and channel.whatsapp_channel_valid_until > fields.Datetime.now()
            )

    @api.constrains('channel_type', 'whatsapp_number')
    def _check_whatsapp_number(self):
        missing = self.filtered(
            lambda c: c.channel_type == 'whatsapp' and not c.whatsapp_number
        )
        if missing:
            raise ValidationError(
                _("A phone number is required for WhatsApp channels")
            )

    @api.constrains('group_public_id', 'group_ids')
    def _constraint_group_id_channel(self):
        valid_channels = self.filtered(lambda c: c.channel_type == 'whatsapp')
        super(DiscussChannel, self - valid_channels)._constraint_group_id_channel()

    def _compute_group_public_id(self):
        wa_channels = self.filtered(lambda c: c.channel_type == "whatsapp")
        wa_channels.filtered(lambda c: not c.group_public_id).group_public_id = self.env.ref('base.group_user')
        super(DiscussChannel, self - wa_channels)._compute_group_public_id()

    # ------------------------------------------------------------------
    # MAILING
    # ------------------------------------------------------------------

    def _get_notify_valid_parameters(self):
        if self.channel_type == 'whatsapp':
            return super()._get_notify_valid_parameters() | {'owa_inbound_msg_uid', 'owa_sender_jid'}
        return super()._get_notify_valid_parameters()

    def _notify_thread(self, message, msg_vals=False, **kwargs):
        parent_msg_id = kwargs.pop('parent_msg_id', False)
        if kwargs.get('owa_inbound_msg_uid') and self.channel_type == 'whatsapp':
            self.env['owa.message'].create({
                'mail_message_id': message.id,
                'message_type': 'inbound',
                'mobile_number': f'+{self.whatsapp_number}',
                'msg_uid': kwargs['owa_inbound_msg_uid'],
                'sender_jid': kwargs.get('owa_sender_jid') or False,
                'parent_id': parent_msg_id,
                'state': 'received',
                'wa_account_id': self.owa_account_id.id,
            })
            if parent_msg_id:
                self.env['owa.message'].browse(parent_msg_id).state = 'replied'
        return super()._notify_thread(message, msg_vals=msg_vals, **kwargs)

    def message_post(self, *args, body='', attachment_ids=None,
                     message_type='notification', parent_id=False,
                     quick_reply_id=False, **kwargs):
        # Validate parent message for WhatsApp replies
        valid_parent_id = False
        if parent_id and self.whatsapp_number:
            parent_wa_msg = self.env['mail.message'].browse(parent_id).owa_message_ids
            if (parent_wa_msg and len(parent_wa_msg) == 1
                    and parent_wa_msg.message_type == "outbound"
                    and parent_wa_msg.mobile_number_formatted == self.whatsapp_number):
                valid_parent_id = parent_id

        if message_type != 'whatsapp_message' or self.channel_type != 'whatsapp':
            message = super().message_post(
                *args, body=body, attachment_ids=attachment_ids,
                message_type=message_type, parent_id=parent_id, **kwargs
            )
            if valid_parent_id:
                message.parent_id = valid_parent_id
            return message

        # Handle audio splitting — audio must be sent separately
        messages = None
        if (not kwargs.get('owa_inbound_msg_uid') and attachment_ids
                and body and not tools.is_html_empty(body)):
            AUDIO_TYPES = ('audio/aac', 'audio/mp4', 'audio/mpeg', 'audio/amr', 'audio/ogg',
                           'audio/ogg; codecs=opus')
            attachment_records = self.env['ir.attachment'].browse(attachment_ids)
            audio_attachments = attachment_records.filtered(lambda x: x.mimetype in AUDIO_TYPES)
            if audio_attachments:
                body_message = super().message_post(
                    *args, message_type=message_type, body=body,
                    attachment_ids=(attachment_records - audio_attachments).ids,
                    parent_id=parent_id, **kwargs,
                )
                audio_message = super().message_post(
                    *args, message_type=message_type,
                    attachment_ids=audio_attachments.ids,
                    parent_id=parent_id, **kwargs,
                )
                messages = body_message + audio_message

        if not messages:
            messages = super().message_post(
                *args, body=body, message_type=message_type,
                attachment_ids=attachment_ids, parent_id=parent_id, **kwargs,
            )

        # Create owa.message records for outbound. When this is a reply to
        # a specific inbound message, link the outbound owa.message to its
        # inbound counterpart via ``parent_id`` so ``_maybe_clear_ack_reaction``
        # can find the original to clear the 👀 ack from.
        outbound_parent_owa_id = False
        if valid_parent_id:
            parent_wa_msgs = self.env['mail.message'].browse(valid_parent_id).owa_message_ids
            inbound_parent = parent_wa_msgs.filtered(lambda m: m.message_type == 'inbound')
            if inbound_parent:
                outbound_parent_owa_id = inbound_parent[:1].id
        owa_message_vals = []
        for new_msg in messages:
            if not new_msg.owa_message_ids:
                owa_message_vals.append({
                    'body': new_msg.body,
                    'mail_message_id': new_msg.id,
                    'message_type': 'outbound',
                    'mobile_number': f'+{self.whatsapp_number}',
                    'wa_account_id': self.owa_account_id.id,
                    'parent_id': outbound_parent_owa_id,
                    # Carry the template id so _send_single_message dispatches
                    # button/list templates as interactive content. (#compose)
                    'quick_reply_id': quick_reply_id or False,
                })

        # Track last inbound message for valid_until computation
        if messages.author_id == self.whatsapp_partner_id:
            self.last_wa_mail_message_id = messages[-1]
            # v18-compat: Store(bus_channel=...).bus_send() is v19-only; use
            # _bus_send_store. NOTE: the v18 Store API requires a *dict* of
            # {field: value}; passing a bare field-name string makes
            # Store.add do `{**"string"}` which raises TypeError. (#discuss)
            self._bus_send_store(
                self,
                {"whatsapp_channel_valid_until": self.whatsapp_channel_valid_until},
            )

        if owa_message_vals:
            self.env['owa.message'].create(owa_message_vals)._send_message()

        if valid_parent_id:
            messages.parent_id = valid_parent_id

        # Phase 22A: an inbound on a resolved channel reopens it
        if (self.channel_type == 'whatsapp'
                and self.triage_state == 'resolved'
                and self.whatsapp_partner_id
                and messages.author_id == self.whatsapp_partner_id):
            self.action_reopen()

        # Phase 27A: relay inbound WhatsApp messages to the linked helpdesk
        # ticket's chatter as an internal note. This block was previously a
        # SECOND `message_post` definition further down the class, which
        # silently shadowed this whole method (Python keeps the last def) and
        # killed all outbound send logic above. Folded here so both behaviours
        # coexist. Guarded against loops (skip_helpdesk_relay) and never blocks
        # the primary post. Only inbound (customer-authored) messages relay.
        if (self.helpdesk_ticket_id_int
                and 'helpdesk.ticket' in self.env
                and not self.env.context.get('skip_helpdesk_relay')
                and messages.author_id == self.whatsapp_partner_id):
            try:
                ticket = self.env['helpdesk.ticket'].sudo().browse(
                    self.helpdesk_ticket_id_int).exists()
                if ticket:
                    author = self.whatsapp_partner_id or messages[:1].author_id
                    prefix = _("WhatsApp inbound from %s:") % (
                        author.display_name if author
                        else (self.whatsapp_number or '?'))
                    relay_body = Markup("<p><em>%s</em></p>%s") % (
                        prefix, Markup(messages[:1].body or ''))
                    ticket.with_context(skip_helpdesk_relay=True).message_post(
                        body=relay_body,
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                        author_id=author.id if author else False,
                    )
            except Exception:
                _logger.exception(
                    "WhatsApp->Helpdesk relay failed for channel %s ticket %s",
                    self.id, self.helpdesk_ticket_id_int)

        return messages[0]

    # ------------------------------------------------------------------
    # CHANNEL MANAGEMENT
    # ------------------------------------------------------------------

    def _get_whatsapp_channel(self, whatsapp_number, wa_account_id,
                              sender_name=False, create_if_not_found=False,
                              related_message=False):
        """Find or create a WhatsApp discuss channel."""
        # Group/community/newsletter JIDs are not phone numbers; passing them
        # through `wa_phone_format` would have phonenumbers reinterpret the
        # leading digits as a US number and silently drop the `@g.us` /
        # `@newsletter` / `@broadcast` suffix, which would route every group
        # inbound to a per-sender personal channel and surface as separate
        # 1-on-1 threads instead of one group conversation.
        if '@' in (whatsapp_number or ''):
            wa_formatted = whatsapp_number.lstrip('+')
        else:
            base_number = whatsapp_number if whatsapp_number.startswith('+') else f'+{whatsapp_number}'
            wa_number = base_number.lstrip('+')
            wa_formatted = wa_phone_format(self.env, base_number) or wa_number

        related_record = False
        responsible_partners = self.env['res.partner']
        channel_domain = [
            ('whatsapp_number', '=', wa_formatted),
            ('owa_account_id', '=', wa_account_id.id),
        ]

        if related_message:
            related_record = self.env[related_message.model].browse(related_message.res_id)
            if hasattr(related_record, '_owa_get_responsible'):
                responsible_partners = related_record._owa_get_responsible(
                    related_message=related_message,
                    related_record=related_record,
                    whatsapp_account=wa_account_id,
                ).partner_id

        channel = self.sudo().search(channel_domain, order='create_date desc', limit=1)
        if responsible_partners:
            channel = channel.filtered(
                lambda c: all(r in c.channel_member_ids.partner_id for r in responsible_partners)
            )

        partners_to_notify = responsible_partners
        if not channel and create_if_not_found:
            recipient_partner = self.env['res.partner']._find_or_create_from_wa_number(
                wa_formatted, sender_name
            )
            recipient_name = (
                recipient_partner.name
                if recipient_partner and recipient_partner.name != recipient_partner.phone
                else False
            )
            channel = self.sudo().with_context(tools.clean_context(self.env.context)).create({
                'name': f"{recipient_name} ({wa_formatted})" if recipient_name else wa_formatted,
                'channel_type': 'whatsapp',
                'whatsapp_number': wa_formatted,
                'whatsapp_partner_id': recipient_partner.id if recipient_partner else False,
                'owa_account_id': wa_account_id.id,
            })
            if recipient_partner:
                partners_to_notify |= recipient_partner

            if related_message and related_record:
                # Add related document link in channel
                info = _("Related %(model_name)s: ",
                         model_name=self.env['ir.model']._get(related_message.model).display_name)
                url = Markup('{base_url}/odoo/{model}/{res_id}').format(
                    base_url=self.get_base_url(),
                    model=related_message.model,
                    res_id=related_message.res_id)
                channel.message_post(
                    body=Markup('<p>{info}<a target="_blank" href="{url}">{name}</a></p>').format(
                        info=info, url=url, name=related_message.record_name),
                    message_type='comment',
                    author_id=self.env.ref('base.partner_root').id,
                    subtype_xmlid='mail.mt_note',
                )
                if hasattr(related_record, 'message_post'):
                    info2 = _("A new WhatsApp channel is created for this document")
                    ch_url = Markup('{base_url}/odoo/discuss.channel/{id}').format(
                        base_url=self.get_base_url(), id=channel.id)
                    related_record.message_post(
                        author_id=self.env.ref('base.partner_root').id,
                        body=Markup(
                            '<p>{info} <a target="_blank" class="o_whatsapp_channel_redirect"'
                            ' data-oe-id="{id}" href="{url}">{name}</a></p>'
                        ).format(info=info2, url=ch_url, id=channel.id, name=channel.display_name),
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )

            if partners_to_notify == (recipient_partner or self.env['res.partner']):
                if wa_account_id.notify_user_ids.partner_id:
                    partners_to_notify |= wa_account_id.notify_user_ids.partner_id
            channel.channel_member_ids = (
                [Command.clear()]
                + [Command.create({'partner_id': p.id}) for p in partners_to_notify]
            )
            channel._broadcast(partners_to_notify.ids)

        return channel

    # ------------------------------------------------------------------
    # OVERRIDES
    # ------------------------------------------------------------------

    def _action_unfollow(self, partner=None, guest=None):
        # v18 base signature is (self, partner=None, guest=None) — it does NOT
        # accept post_leave_message (that param is v19-only). Passing a third
        # positional to super() raises TypeError and crashes unfollow on every
        # WhatsApp channel. (#coexist)
        if (partner and self.channel_type == "whatsapp"
                and next(
                    (m.partner_id for m in self.channel_member_ids if not m.partner_id.partner_share),
                    self.env["res.partner"]
                ) == partner):
            msg = _("You can't leave this channel. As the owner, you can only delete it.")
            partner._bus_send_transient_message(self, msg)
            return
        super()._action_unfollow(partner, guest)

    def _to_store(self, store: Store):
        # v18-compat: v18 has NO `_to_store_defaults` (that is a v19 API) and
        # no Store.Attr / Store.One. Without this override the whatsapp store
        # fields never reach the frontend, so thread.owa_account_id is always
        # undefined and `isOwaWhatsappThread` is always false — silently
        # disabling every composer WhatsApp enhancement. Inject them here via
        # the v18 Store API instead. (#discuss)
        super()._to_store(store)
        for channel in self.filtered(is_whatsapp_channel):
            account = channel.sudo().owa_account_id
            vals = {
                "whatsapp_channel_valid_until": channel.whatsapp_channel_valid_until,
                "whatsapp_partner_id": (
                    Store.one(channel.whatsapp_partner_id)
                    if channel.whatsapp_partner_id else False
                ),
                "owa_account_id": (
                    Store.one(account, only_id=True) if account else False
                ),
            }
            store.add(channel, vals)
            if account:
                # The frontend owa.account Record only needs {id, name}; send it
                # explicitly rather than relying on a _to_store on owa.account.
                store.add("owa.account", {"id": account.id, "name": account.name or ""})

    def _types_allowing_seen_infos(self):
        return super()._types_allowing_seen_infos() + ["whatsapp"]

    def execute_command_leave(self, **kwargs):
        if self.channel_type == 'whatsapp':
            self.action_unfollow()
        else:
            super().execute_command_leave(**kwargs)

    # ─── Phase 22A: triage helpers ───────────────────────────────────────

    @api.depends('assigned_at', 'owa_account_id.sla_minutes')
    def _compute_sla_due_at(self):
        for ch in self:
            if ch.assigned_at and ch.owa_account_id and ch.owa_account_id.sla_minutes:
                ch.sla_due_at = ch.assigned_at + timedelta(
                    minutes=ch.owa_account_id.sla_minutes)
            else:
                ch.sla_due_at = False

    @api.depends('sla_due_at', 'triage_state', 'resolved_at')
    def _compute_sla_breached(self):
        now = fields.Datetime.now()
        for ch in self:
            ch.sla_breached = bool(
                ch.sla_due_at and ch.sla_due_at < now
                and ch.triage_state in ('unassigned', 'active'))

    def action_assign_to_me(self):
        for ch in self.filtered(lambda c: c.channel_type == 'whatsapp'):
            ch.write({
                'assignee_id': self.env.user.id,
                'triage_state': 'active' if ch.triage_state == 'unassigned' else ch.triage_state,
                'assigned_at': ch.assigned_at or fields.Datetime.now(),
            })
        return True

    def action_mark_resolved(self):
        for ch in self.filtered(lambda c: c.channel_type == 'whatsapp'):
            ch.write({
                'triage_state': 'resolved',
                'resolved_at': fields.Datetime.now(),
            })
            # Phase 23B: trigger CSAT if account has it enabled
            if (ch.owa_account_id and getattr(ch.owa_account_id, 'auto_csat', False)
                    and ch.whatsapp_partner_id):
                try:
                    self.env['owa.satisfaction.score'].sudo()._send_csat_invite(ch)
                except Exception:
                    _logger.exception("CSAT invite failed for channel %s", ch.id)
        return True

    def action_reopen(self):
        for ch in self.filtered(lambda c: c.channel_type == 'whatsapp'):
            ch.write({
                'triage_state': 'active',
                'resolved_at': False,
            })
        return True

    def action_put_on_hold(self):
        self.filtered(lambda c: c.channel_type == 'whatsapp').write({
            'triage_state': 'on_hold',
        })
        return True

    # ─── Phase 27A: helpdesk bridge ───────────────────────────────────
    def action_open_helpdesk_ticket(self):
        """Smart-button action: open the linked helpdesk.ticket form. Raises
        if no ticket linked or helpdesk module not installed."""
        self.ensure_one()
        if 'helpdesk.ticket' not in self.env:
            raise UserError(_(
                "Helpdesk module is not installed on this database."))
        if not self.helpdesk_ticket_id_int:
            raise UserError(_("No helpdesk ticket is linked to this conversation."))
        ticket = self.env['helpdesk.ticket'].browse(self.helpdesk_ticket_id_int)
        if not ticket.exists():
            raise UserError(_(
                "The linked helpdesk ticket (id %s) no longer exists.",
                self.helpdesk_ticket_id_int))
        return {
            'type': 'ir.actions.act_window',
            'name': ticket.display_name or _("Helpdesk Ticket"),
            'res_model': 'helpdesk.ticket',
            'res_id': ticket.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _cron_check_sla(self):
        """Phase 22A: surface SLA breaches as activities for the assignee."""
        breached = self.search([
            ('channel_type', '=', 'whatsapp'),
            ('triage_state', 'in', ['unassigned', 'active']),
            ('sla_due_at', '<', fields.Datetime.now()),
        ])
        for ch in breached:
            existing = self.env['mail.activity'].search([
                ('res_model', '=', 'discuss.channel'),
                ('res_id', '=', ch.id),
                ('summary', '=', 'WhatsApp SLA breached'),
            ], limit=1)
            if existing:
                continue
            target = ch.assignee_id or self.env.user
            ch.activity_schedule(
                'mail.mail_activity_data_warning',
                user_id=target.id,
                summary='WhatsApp SLA breached',
                note=Markup(
                    '<p>This WhatsApp conversation has exceeded its SLA window. '
                    'Either reply, reassign, or mark as resolved.</p>'
                ),
            )

