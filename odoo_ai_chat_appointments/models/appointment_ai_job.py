from datetime import timedelta
import uuid

from odoo import api, fields, models


class OdooAIAppointmentAIJob(models.Model):
    _name = "odoo.ai.appointment.ai.job"
    _description = "Job persistente de fallback IA del chatbot de citas"
    _order = "create_date desc, id desc"

    token = fields.Char(required=True, copy=False, index=True, default=lambda self: uuid.uuid4().hex)
    status = fields.Selection(
        [("pending", "Pendiente"), ("running", "En ejecución"), ("done", "Finalizado")],
        required=True,
        default="pending",
        index=True,
    )
    reply = fields.Text()
    fallback_reply = fields.Text()
    ai_fallback_used = fields.Boolean(default=False)
    ai_error = fields.Char()
    expires_at = fields.Datetime(required=True, index=True)

    _sql_constraints = [
        ("token_unique", "unique(token)", "El token del job de IA debe ser único."),
    ]

    @api.model
    def create_job(self, fallback_reply=""):
        return self.sudo().create({
            "fallback_reply": fallback_reply or "",
            "expires_at": fields.Datetime.now() + timedelta(minutes=30),
        })

    @api.model
    def action_cleanup_jobs(self):
        jobs = self.sudo().search([("expires_at", "<", fields.Datetime.now())])
        count = len(jobs)
        if jobs:
            jobs.unlink()
        return count
