{
    "name": "Login Attempt Security",
    "summary": "Limit failed login attempts and temporarily block users to prevent brute-force attacks.",
    "description": """
Login Attempt Security for Odoo 18

Features:
- Limit maximum failed login attempts
- Automatically block users after threshold
- Configurable block duration
- Auto unlock after block period
- Works with Odoo 18 authentication system
- Clean integration with Settings → Users & Companies

Ideal for improving system security against brute-force attacks.
    """,
    "version": "18.0.1.0.0",
    "category": "Security",
    "author": "Deepak Verma",
    "company": "DeeCoders",
    "maintainer": "Deepak Verma",
    "website": "https://www.linkedin.com/in/deepak-verma-07144012a",
    "support": "dpakverma789@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_view.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/screenshot_settings.png",
        "static/description/screenshot_blocked.png",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
