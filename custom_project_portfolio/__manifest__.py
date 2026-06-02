{
    "name": "Custom Project Portfolio Carousel",
    "version": "18.0.1.0.0",
    "depends": ["project", "website"],
    "data": [
        "security/ir.model.access.csv",
        "views/project_views.xml",
        "views/website_templates.xml"
    ],
    "assets": {
        "web.assets_frontend": [
            "custom_project_portfolio/static/src/js/portfolio_carousel.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3"
}
