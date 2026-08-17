from odoo import fields, models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    _sql_constraints = [
        (
            "odoo_ai_appointment_session_unique",
            "unique(appointment_session_id)",
            "Una sesión del chatbot no puede crear más de una cita.",
        ),
    ]

    is_chatbot_appointment = fields.Boolean(
        string="Cita de chatbot",
        default=False,
        index=True,
        help="Marca este registro como una cita gestionada por el chatbot.",
    )
    cliente = fields.Char(
        string="Cliente",
        index=True,
        help="Nombre y apellidos del cliente que será atendido.",
    )
    appointment_service_id = fields.Many2one(
        comodel_name="odoo.ai.appointment.service",
        string="Servicio",
        ondelete="restrict",
        index=True,
    )
    appointment_session_id = fields.Many2one(
        comodel_name="odoo.ai.appointment.session",
        string="Sesión del chatbot",
        copy=False,
        ondelete="set null",
        index=True,
    )
