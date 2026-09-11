# Copyright 2025 ForgeFlow S.L. (https://www.forgeflow.com)
# Part of ForgeFlow. See LICENSE file for full copyright and licensing details.

{
    "name": "HR Attendance Employee Allow Kiosk",
    "version": "18.0.1.1.3",
    'category': 'Operations',
    "website": "https://github.com/OCA/hr-attendance",
    "author": "ForgeFlow S.L., Odoo Community Association (OCA)",
    "license": "LGPL-3",
    "depends": ["hr_attendance"],
    "data": [
        "views/hr_employee_view.xml",
    ],
    "assets": {
        "hr_attendance.assets_public_attendance": [
            "hr_attendance_employee_allow_kiosk_custom/static/src/components/greetings/greetings.xml",
        ],
    },
    "application": False,
    "installable": True,
}
