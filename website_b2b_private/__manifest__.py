{
    "name": "Website B2B Private",
    "summary": "B2B approval flow with private prices, cart and stock",
    "version": "18.0.6.0.0",
    "category": "Website/eCommerce",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": [
        "website_sale",
        "website_sale_stock",
        "auth_signup",
    ],
    "data": [
        "data/b2b_pricelist_data.xml",
        "views/product_pricelist_views.xml",
        "views/website_sale_templates.xml",
        "views/b2b_ux_templates.xml",
        "data/custom_stock_privacy_data.xml",
        "data/final_audit_data.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "website_b2b_private/static/src/scss/b2b_price_privacy.scss",
            "website_b2b_private/static/src/js/b2b_contact_position.js",
            "website_b2b_private/static/src/xml/b2b_stock_privacy.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
