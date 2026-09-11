from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _get_translation_frontend_modules_name(cls):
        modules = super()._get_translation_frontend_modules_name()
        module_name = "hr_attendance_employee_allow_kiosk_custom"
        if module_name not in modules:
            modules.append(module_name)
        return modules
