from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OdooAIAppointmentAvailabilityWizard(models.TransientModel):
    _name = "odoo.ai.appointment.availability.wizard"
    _description = "Prueba del motor de disponibilidad"

    service_id = fields.Many2one(
        "odoo.ai.appointment.service",
        string="Servicio",
        required=True,
        domain=[("active", "=", True)],
    )
    eligible_employee_ids = fields.Many2many(
        "hr.employee",
        string="Profesionales compatibles",
        compute="_compute_eligible_employee_ids",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Profesional",
        domain="[('id', 'in', eligible_employee_ids)]",
        help="Déjalo vacío para buscar entre todos los profesionales compatibles y ordenar por primera disponibilidad.",
    )
    date_from = fields.Date(
        string="Fecha desde",
        required=True,
        default=fields.Date.context_today,
    )
    date_to = fields.Date(
        string="Fecha hasta",
        required=True,
        default=lambda self: fields.Date.context_today(self) + timedelta(days=13),
    )
    time_from = fields.Float(
        string="Hora desde",
        required=True,
        default=0.0,
    )
    time_to = fields.Float(
        string="Hora hasta",
        required=True,
        default=24.0,
    )
    max_results = fields.Integer(
        string="Máximo de resultados",
        required=True,
        default=50,
    )
    line_ids = fields.One2many(
        "odoo.ai.appointment.availability.wizard.line",
        "wizard_id",
        string="Huecos encontrados",
        readonly=True,
    )
    result_count = fields.Integer(
        string="Huecos encontrados",
        compute="_compute_result_count",
    )

    @api.depends("line_ids")
    def _compute_result_count(self):
        for wizard in self:
            wizard.result_count = len(wizard.line_ids)

    @api.depends("service_id")
    def _compute_eligible_employee_ids(self):
        Employee = self.env["hr.employee"]
        for wizard in self:
            wizard.eligible_employee_ids = wizard.service_id.get_eligible_employees() if wizard.service_id else Employee

    @api.onchange("service_id")
    def _onchange_service_id(self):
        if not self.service_id:
            self.employee_id = False
            return

        eligible = self.service_id.get_eligible_employees()
        if self.employee_id and self.employee_id not in eligible:
            self.employee_id = False
        if self.date_from:
            self.date_to = self.date_from + timedelta(days=max(self.service_id.max_search_days, 1) - 1)

    @api.onchange("date_from")
    def _onchange_date_from(self):
        if self.date_from and self.service_id:
            max_date = self.date_from + timedelta(days=max(self.service_id.max_search_days, 1) - 1)
            if not self.date_to or self.date_to < self.date_from or self.date_to > max_date:
                self.date_to = max_date

    def action_calculate(self):
        self.ensure_one()
        if self.max_results <= 0:
            raise ValidationError(_("El máximo de resultados debe ser mayor que cero."))

        slots = self.env["odoo.ai.appointment.availability"].get_available_slots(
            service=self.service_id,
            employee=self.employee_id or None,
            date_from=self.date_from,
            date_to=self.date_to,
            time_from=self.time_from,
            time_to=self.time_to,
            limit=self.max_results,
        )

        commands = [fields.Command.clear()]
        for position, slot in enumerate(slots, start=1):
            commands.append(fields.Command.create({
                "sequence": position,
                "employee_id": slot["employee_id"],
                "start": slot["start"],
                "end": slot["end"],
                "timezone": slot["timezone"],
                "start_local": slot["start_local"],
                "end_local": slot["end_local"],
            }))
        self.line_ids = commands

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }


class OdooAIAppointmentAvailabilityWizardLine(models.TransientModel):
    _name = "odoo.ai.appointment.availability.wizard.line"
    _description = "Resultado de disponibilidad"
    _order = "sequence, start, employee_id"

    wizard_id = fields.Many2one(
        "odoo.ai.appointment.availability.wizard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer()
    employee_id = fields.Many2one("hr.employee", string="Profesional", required=True, readonly=True)
    start = fields.Datetime(string="Inicio UTC/Odoo", required=True, readonly=True)
    end = fields.Datetime(string="Fin UTC/Odoo", required=True, readonly=True)
    timezone = fields.Char(string="Zona horaria", readonly=True)
    start_local = fields.Char(string="Inicio local", readonly=True)
    end_local = fields.Char(string="Fin local", readonly=True)
