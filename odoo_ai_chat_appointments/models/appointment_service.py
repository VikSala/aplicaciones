from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OdooAIAppointmentService(models.Model):
    _name = "odoo.ai.appointment.service"
    _description = "Servicio reservable del chatbot"
    _order = "sequence, name, id"

    name = fields.Char(string="Servicio", required=True, translate=True)
    aliases = fields.Text(
        string="Alias del parser",
        help="Sinónimos que el parser Python reconocerá como este servicio. Sepáralos por comas o líneas, por ejemplo: fisio, fisioterapeuta.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    duration_minutes = fields.Integer(
        string="Duración (minutos)",
        required=True,
        help="Duración que ocupará una cita de este servicio.",
    )
    slot_step_minutes = fields.Integer(
        string="Intervalo entre inicios (minutos)",
        required=True,
        default=30,
        help="Granularidad de los inicios que propondrá el motor. Por ejemplo, 30 permite 09:00, 09:30, 10:00...",
    )
    min_notice_minutes = fields.Integer(
        string="Antelación mínima (minutos)",
        required=True,
        default=0,
        help="Tiempo mínimo entre el momento actual y el inicio de una cita propuesta.",
    )
    max_search_days = fields.Integer(
        string="Horizonte máximo (días)",
        required=True,
        default=30,
        help="Número máximo de días que el motor recorrerá desde la fecha inicial al buscar disponibilidad.",
    )
    department_ids = fields.Many2many(
        comodel_name="hr.department",
        relation="odoo_ai_appointment_service_hr_department_rel",
        column1="service_id",
        column2="department_id",
        string="Departamentos habilitados",
        help="Un empleado podrá ofrecer este servicio cuando pertenezca a uno de estos departamentos.",
    )
    eligible_employee_ids = fields.Many2many(
        comodel_name="hr.employee",
        string="Profesionales compatibles",
        compute="_compute_eligible_employee_ids",
        help="Empleados activos cuyo departamento está habilitado para este servicio.",
    )
    description = fields.Text(string="Descripción")

    _sql_constraints = [
        ("name_uniq", "unique(name)", "Ya existe un servicio con ese nombre."),
    ]

    @api.depends("department_ids")
    def _compute_eligible_employee_ids(self):
        Employee = self.env["hr.employee"]
        for service in self:
            service.eligible_employee_ids = Employee.search([
                ("active", "=", True),
                ("department_id", "in", service.department_ids.ids),
            ]) if service.department_ids else Employee.search([("active", "=", True)])

    @api.constrains("duration_minutes", "slot_step_minutes", "min_notice_minutes", "max_search_days")
    def _check_availability_settings(self):
        for service in self:
            if service.duration_minutes <= 0:
                raise ValidationError("La duración del servicio debe ser mayor que cero minutos.")
            if service.slot_step_minutes <= 0:
                raise ValidationError("El intervalo entre inicios debe ser mayor que cero minutos.")
            if service.slot_step_minutes > 24 * 60:
                raise ValidationError("El intervalo entre inicios no puede superar 24 horas.")
            if service.min_notice_minutes < 0:
                raise ValidationError("La antelación mínima no puede ser negativa.")
            if service.max_search_days <= 0:
                raise ValidationError("El horizonte máximo debe ser mayor que cero días.")

    def get_alias_list(self):
        """Devuelve aliases configurados, separados por coma, punto y coma o línea."""
        self.ensure_one()
        if not self.aliases:
            return []
        import re
        return [value.strip() for value in re.split(r"[,;\n]+", self.aliases) if value.strip()]

    def get_eligible_employees(self):
        """Devuelve empleados activos compatibles por departamento."""
        self.ensure_one()
        domain = [("active", "=", True)]
        if self.department_ids:
            domain.append(("department_id", "in", self.department_ids.ids))
        return self.env["hr.employee"].search(domain)

    def get_available_slots(self, employee=None, **kwargs):
        """API pública del servicio para el motor de disponibilidad."""
        self.ensure_one()
        return self.env["odoo.ai.appointment.availability"].get_available_slots(
            service=self,
            employee=employee,
            **kwargs,
        )

    def get_first_available_slot(self, employee=None, **kwargs):
        """Devuelve el primer hueco válido o False."""
        self.ensure_one()
        return self.env["odoo.ai.appointment.availability"].get_first_available_slot(
            service=self,
            employee=employee,
            **kwargs,
        )

    def action_open_availability_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Probar disponibilidad"),
            "res_model": "odoo.ai.appointment.availability.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_service_id": self.id,
            },
        }
