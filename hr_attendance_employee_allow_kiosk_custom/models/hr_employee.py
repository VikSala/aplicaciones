# Copyright 2025 ForgeFlow S.L. (https://www.forgeflow.com)
# Part of ForgeFlow. See LICENSE file for full copyright and licensing details.

import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from werkzeug.urls import url_join


class HrEmployeeBase(models.AbstractModel):
    _inherit = "hr.employee.base"

    allow_kiosk_access = fields.Boolean(
        default=True,
        help="If enabled, the employee is selectable in the kiosk for attendance "
        "registration.",
    )


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    employee_kiosk_key = fields.Char(
        string="Clave URL del quiosco",
        copy=False,
        readonly=True,
        groups="hr_attendance.group_hr_attendance_manager",
    )
    employee_kiosk_url = fields.Char(
        string="URL del quiosco de asistencia",
        compute="_compute_employee_kiosk_url",
        readonly=True,
        groups="hr_attendance.group_hr_attendance_manager",
        help="URL individual para que este empleado pueda acceder al quiosco de asistencia.",
    )

    @api.depends("employee_kiosk_key")
    def _compute_employee_kiosk_url(self):
        base_url = self.env["res.company"].get_base_url()
        for employee in self:
            if employee.employee_kiosk_key:
                employee.employee_kiosk_url = url_join(
                    base_url, "/hr_attendance/%s" % employee.employee_kiosk_key
                )
            else:
                employee.employee_kiosk_url = False

    def action_generate_employee_kiosk_url(self):
        if not self.env.user.has_group("hr_attendance.group_hr_attendance_manager"):
            raise AccessError(_("Only attendance managers can generate kiosk URLs."))
        for employee in self:
            employee.write({
                "employee_kiosk_key": uuid.uuid4().hex,
                "allow_kiosk_access": True,
            })
        return {"type": "ir.actions.client", "tag": "reload"}
