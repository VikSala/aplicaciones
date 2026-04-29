from odoo import http
from odoo.addons.hr_attendance.controllers.main import HrAttendance as HrAttendanceBase
from odoo.http import request
from odoo.tools.image import image_data_uri


class HrAttendance(HrAttendanceBase):
    @staticmethod
    def _get_employee_from_kiosk_token(token):
        if not token:
            return request.env["hr.employee"].sudo()
        return request.env["hr.employee"].sudo().search(
            [("employee_kiosk_key", "=", token)], limit=1
        )

    @staticmethod
    def _get_company(token):
        company = HrAttendanceBase._get_company(token)
        if company:
            return company
        employee = HrAttendance._get_employee_from_kiosk_token(token)
        return employee.company_id if employee else company

    @http.route("/hr_attendance/employees_infos", type="json", auth="public")
    def employees_infos(self, token, limit, offset, domain):
        employee_from_token = self._get_employee_from_kiosk_token(token)

        # Si la URL es individual, solo se mostrará el empleado al que pertenece esa URL.
        if employee_from_token:
            if not employee_from_token.allow_kiosk_access:
                return {"records": [], "length": 0}

            record = {
                "id": employee_from_token.id,
                "display_name": employee_from_token.display_name,
                "job_id": employee_from_token.job_id.name,
                "avatar": image_data_uri(employee_from_token.avatar_128),
            }
            records = [record]
            if offset:
                records = records[offset:]
            if limit:
                records = records[:limit]
            return {"records": records, "length": 1}

        # URL general de la compañía: mantenemos el comportamiento original del módulo,
        # ocultando empleados sin permiso de acceso al quiosco.
        restricted_employees = request.env["hr.employee"].sudo().search([
            ("allow_kiosk_access", "=", False)
        ])
        restricted_ids = restricted_employees.ids

        result = super().employees_infos(token, limit, offset, domain)

        if isinstance(result, dict) and "records" in result and restricted_ids:
            result["records"] = [
                rec for rec in result["records"] if rec.get("id") not in restricted_ids
            ]
            result["length"] = len(result["records"])

        return result

    @http.route("/hr_attendance/attendance_employee_data", type="json", auth="public")
    def employee_attendance_data(self, token, employee_id):
        employee_from_token = self._get_employee_from_kiosk_token(token)
        if employee_from_token and employee_from_token.id != int(employee_id):
            return {}
        return super().employee_attendance_data(token, employee_id)

    @http.route("/hr_attendance/manual_selection", type="json", auth="public")
    def manual_selection_with_geolocation(
        self, token, employee_id, pin_code, latitude=False, longitude=False
    ):
        employee_from_token = self._get_employee_from_kiosk_token(token)
        if employee_from_token and employee_from_token.id != int(employee_id):
            return {}
        return super().manual_selection_with_geolocation(
            token, employee_id, pin_code, latitude=latitude, longitude=longitude
        )

    @http.route("/hr_attendance/attendance_barcode_scanned", type="json", auth="public")
    def scan_barcode(self, token, barcode):
        employee_from_token = self._get_employee_from_kiosk_token(token)
        if employee_from_token and employee_from_token.barcode != barcode:
            return {}
        return super().scan_barcode(token, barcode)
