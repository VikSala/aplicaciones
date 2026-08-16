from datetime import timedelta

from odoo import api, fields, models, _


SESSION_LOCK_NAMESPACE = 20260815
OPEN_STATES = [
    "new",
    "waiting_service",
    "waiting_booking_mode",
    "waiting_employee",
    "waiting_time_preference",
    "slot_proposed",
    "waiting_customer_name",
    "ready_to_book",
]


class OdooAIAppointmentSession(models.Model):
    _name = "odoo.ai.appointment.session"
    _description = "Sesión de reserva del chatbot"
    _order = "last_activity desc, id desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env._("Nuevo"),
    )
    active = fields.Boolean(default=True)
    is_test = fields.Boolean(
        string="Sesión de prueba",
        default=False,
        index=True,
        help="Marca las sesiones creadas desde el asistente de control de calidad.",
    )

    source = fields.Selection(
        selection=[
            ("web", "Web"),
            ("whatsapp", "WhatsApp"),
        ],
        string="Origen",
        required=True,
        default="web",
        index=True,
    )
    web_session_id = fields.Char(
        string="Sesión web",
        index=True,
        copy=False,
        help="Identificador localStorage del widget web. Solo identifica el canal web; no contiene el histórico.",
    )
    whatsapp_channel_id = fields.Many2one(
        comodel_name="discuss.channel",
        string="Conversación WhatsApp",
        index=True,
        ondelete="set null",
        domain=[("channel_type", "=", "whatsapp"), ("is_whatsapp_group", "=", False)],
        help="Canal individual persistente creado por Open WhatsApp Connector para esta conversación.",
    )
    whatsapp_number = fields.Char(
        string="Número WhatsApp",
        related="whatsapp_channel_id.whatsapp_number",
        readonly=True,
    )
    whatsapp_last_inbound_message_id = fields.Many2one(
        comodel_name="mail.message",
        string="Último mensaje WhatsApp recibido",
        copy=False,
        readonly=True,
        ondelete="set null",
        help="Puntero al histórico real de Discuss. No duplica el contenido del mensaje.",
    )
    whatsapp_last_outbound_message_id = fields.Many2one(
        comodel_name="mail.message",
        string="Última respuesta WhatsApp",
        copy=False,
        readonly=True,
        ondelete="set null",
        help="Puntero a la última respuesta enviada por el chatbot a través de Open WhatsApp Connector.",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente / contacto",
        index=True,
        ondelete="set null",
    )

    state = fields.Selection(
        selection=[
            ("new", "Nueva"),
            ("waiting_service", "Esperando servicio"),
            ("waiting_booking_mode", "Esperando modalidad"),
            ("waiting_employee", "Esperando profesional"),
            ("waiting_time_preference", "Esperando preferencia horaria"),
            ("slot_proposed", "Hueco propuesto"),
            ("waiting_customer_name", "Esperando nombre del cliente"),
            ("ready_to_book", "Lista para reservar"),
            ("booked", "Reservada"),
            ("cancelled", "Cancelada"),
            ("expired", "Caducada"),
        ],
        string="Estado",
        required=True,
        default="new",
        index=True,
    )
    service_id = fields.Many2one(
        comodel_name="odoo.ai.appointment.service",
        string="Servicio",
        ondelete="restrict",
    )
    booking_mode = fields.Selection(
        selection=[
            ("choose_employee", "Elegir profesional"),
            ("first_available", "Primera disponibilidad"),
        ],
        string="Modalidad de reserva",
    )
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Profesional elegido",
        ondelete="set null",
    )

    preference_text = fields.Text(
        string="Preferencia original",
        help="Texto original de preferencia horaria indicado por el usuario.",
    )
    preferred_date_from = fields.Date(string="Fecha desde")
    preferred_date_to = fields.Date(string="Fecha hasta")
    preferred_time_from = fields.Float(string="Hora desde")
    preferred_time_to = fields.Float(string="Hora hasta")
    preference_data = fields.Json(
        string="Preferencia estructurada",
        help="Salida normalizada del parser Python.",
    )

    proposed_employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Profesional propuesto",
        ondelete="set null",
    )
    proposed_start = fields.Datetime(string="Inicio propuesto")
    proposed_end = fields.Datetime(string="Fin propuesto")

    customer_name = fields.Char(string="Nombre y apellidos")
    booked_at = fields.Datetime(
        string="Fecha de reserva",
        copy=False,
        readonly=True,
        index=True,
    )
    attendance_id = fields.Many2one(
        comodel_name="hr.attendance",
        string="Cita / asistencia creada",
        copy=False,
        ondelete="set null",
    )
    last_activity = fields.Datetime(
        string="Última actividad",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    closed_at = fields.Datetime(string="Fecha de cierre", copy=False, readonly=True, index=True)
    close_reason = fields.Char(string="Motivo de cierre", copy=False, readonly=True)

    # ------------------------------------------------------------------
    # Ciclo de vida / concurrencia
    # ------------------------------------------------------------------

    @api.model
    def _session_timeout_hours(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "odoo_ai_chat_appointments.session_timeout_hours",
            default="24",
        )
        try:
            return max(int(float(raw or 24)), 1)
        except (TypeError, ValueError):
            return 24

    @api.model
    def _stale_cutoff(self):
        return fields.Datetime.now() - timedelta(hours=self._session_timeout_hours())

    def _expire_if_stale(self):
        """Caduca de forma perezosa una sesión abandonada.

        El cron realiza la limpieza normal, pero este control evita recuperar
        una conversación obsoleta aunque el cron todavía no haya pasado.
        Las sesiones del wizard de QA no caducan mientras se están probando.
        """
        self.ensure_one()
        if self.is_test or self.state not in OPEN_STATES:
            return False
        if self.last_activity and self.last_activity < self._stale_cutoff():
            self.write({
                "state": "expired",
                "closed_at": fields.Datetime.now(),
                "close_reason": "inactivity_timeout",
            })
            return True
        return False

    @api.model
    def action_expire_stale_sessions(self):
        cutoff = self._stale_cutoff()
        stale = self.sudo().search([
            ("is_test", "=", False),
            ("state", "in", OPEN_STATES),
            ("last_activity", "<", cutoff),
        ])
        if stale:
            stale.write({
                "state": "expired",
                "closed_at": fields.Datetime.now(),
                "close_reason": "inactivity_timeout",
            })
        return len(stale)

    @api.model
    def _lock_web_key(self, web_session_id):
        # hashtext devuelve int4; la combinación namespace + hash es estable
        # dentro de PostgreSQL y el lock dura únicamente la transacción actual.
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            (SESSION_LOCK_NAMESPACE, str(web_session_id)),
        )

    @api.model
    def _lock_whatsapp_channel(self, channel_id):
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (SESSION_LOCK_NAMESPACE, int(channel_id)),
        )

    @api.model
    def find_active_web_session(self, web_session_id):
        web_session_id = str(web_session_id or "").strip()
        if not web_session_id:
            return self.browse()
        session = self.sudo().search([
            ("source", "=", "web"),
            ("web_session_id", "=", web_session_id),
            ("is_test", "=", False),
            ("active", "=", True),
            ("state", "in", OPEN_STATES),
        ], order="last_activity desc, id desc", limit=1)
        if session and session._expire_if_stale():
            return self.browse()
        return session

    @api.model
    def get_or_create_web_session(self, web_session_id, partner=None):
        web_session_id = str(web_session_id or "").strip()
        if not web_session_id:
            return self.browse()
        self._lock_web_key(web_session_id)
        session = self.find_active_web_session(web_session_id)
        partner = partner.exists() if partner else self.env["res.partner"].browse()
        if session:
            if partner and not session.partner_id:
                session.partner_id = partner.id
            return session
        vals = {
            "source": "web",
            "web_session_id": web_session_id,
            "state": "new",
            "is_test": False,
        }
        if partner:
            vals["partner_id"] = partner.id
        return self.sudo().create(vals)

    @api.model
    def get_or_create_whatsapp_session(self, channel):
        """Devuelve el proceso activo asociado a un DM de WhatsApp."""
        channel = channel.sudo().exists()
        channel.ensure_one()
        if channel.channel_type != "whatsapp" or channel.is_whatsapp_group:
            return self.browse()

        self._lock_whatsapp_channel(channel.id)
        Session = self.sudo()
        session = Session.search([
            ("source", "=", "whatsapp"),
            ("whatsapp_channel_id", "=", channel.id),
            ("is_test", "=", False),
            ("active", "=", True),
            ("state", "in", OPEN_STATES),
        ], order="last_activity desc, id desc", limit=1)
        if session and session._expire_if_stale():
            session = Session.browse()

        partner = channel.whatsapp_partner_id
        if session:
            vals = {}
            if partner and session.partner_id != partner:
                vals["partner_id"] = partner.id
            if vals:
                session.write(vals)
            return session

        vals = {
            "source": "whatsapp",
            "whatsapp_channel_id": channel.id,
            "state": "new",
            "is_test": False,
        }
        if partner:
            vals["partner_id"] = partner.id
        return Session.create(vals)

    def start_new_process(self, reason="user_restart"):
        """Cierra el proceso actual y abre otro conservando el histórico."""
        self.ensure_one()
        now = fields.Datetime.now()
        if self.state in OPEN_STATES:
            self.write({
                "state": "cancelled",
                "closed_at": now,
                "close_reason": reason,
                "last_activity": now,
            })
        vals = {
            "source": self.source,
            "state": "new",
            "is_test": self.is_test,
            "partner_id": self.partner_id.id or False,
        }
        if self.source == "web":
            vals["web_session_id"] = self.web_session_id
        elif self.source == "whatsapp":
            vals["whatsapp_channel_id"] = self.whatsapp_channel_id.id
            vals["whatsapp_last_inbound_message_id"] = self.whatsapp_last_inbound_message_id.id or False
        return self.sudo().create(vals)

    def cancel_process(self, reason="user_cancelled"):
        self.ensure_one()
        if self.state not in OPEN_STATES:
            return False
        self.write({
            "state": "cancelled",
            "closed_at": fields.Datetime.now(),
            "close_reason": reason,
            "last_activity": fields.Datetime.now(),
        })
        return True

    @api.onchange("whatsapp_channel_id")
    def _onchange_whatsapp_channel_id(self):
        for session in self:
            if session.whatsapp_channel_id and session.whatsapp_channel_id.whatsapp_partner_id:
                session.partner_id = session.whatsapp_channel_id.whatsapp_partner_id

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", self.env._("Nuevo")) == self.env._("Nuevo"):
                vals["name"] = sequence.next_by_code("odoo.ai.appointment.session") or self.env._("Nuevo")
        return super().create(vals_list)
