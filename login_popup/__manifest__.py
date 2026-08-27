# -*- coding: utf-8 -*-
{
    "name": "Website Login Popup",
    "summary": "Abre el inicio de sesión del website en un popup sin abandonar la página actual",
    "version": "18.0.1.6.0",
    "category": "Website/Website",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": [
        "website",
        "auth_signup",
    ],
    "data": [
        "views/login_popup_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "login_popup/static/src/scss/login_popup.scss",
            "login_popup/static/src/js/login_popup.js",
        ],
    },
    "installable": True,
    "application": False,
}
