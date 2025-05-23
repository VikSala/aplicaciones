# Copyright 2023-2025 Tecnativa - Víctor Martínez
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models


class CalendarHolidaysPublicLine(models.Model):
    _inherit = "calendar.public.holiday.line"

    city_ids = fields.Many2many(
        "res.city",
        "hr_holiday_public_city_rel",
        "line_id",
        "city_id",
        "Related Cities",
    )

    @api.constrains("city_ids")
    def _check_date_state_city_ids(self):
        self._check_date_state()

    @api.constrains("city_ids")
    def _update_calendar_event_city_ids(self):
        self._update_calendar_event()

    def _get_domain_check_date_state_one_state_ids(self):
        domain = super()._get_domain_check_date_state_one_state_ids()
        if self.city_ids:
            domain += [("city_ids", "!=", False)]
        return domain

    def _get_domain_check_date_state_one(self):
        domain = super()._get_domain_check_date_state_one()
        domain += [("city_ids", "=", False)]
        return domain

    def _prepare_holidays_meeting_values(self):
        res = super()._prepare_holidays_meeting_values()
        if self.city_ids:
            res["description"] += ": " + ", ".join(self.city_ids.mapped("name"))
        return res
