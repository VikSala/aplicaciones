# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

{
    'name': 'Droggol Theme Common',
    'description': 'Droggol Theme Common',
    'category': 'eCommerce',
    'version': '18.0.0.0.15',
    'depends': [
        'website_sale_comparison',
        'website_sale_wishlist',
        'website_sale_stock',
        'website_sale_stock_wishlist',
    ],

    'license': 'OPL-1',
    'author': 'Droggol Infotech Private Limited',
    'company': 'Droggol Infotech Private Limited',
    'maintainer': 'Droggol Infotech Private Limited',
    'website': 'https://www.droggol.com/',

    'price': 10.00,
    'currency': 'USD',
    'live_test_url': '',

    'data': [
        'security/ir.model.access.csv',
        'deprecated/ir.model.access.csv',
        'views/templates.xml',

        # Backend
        'views/backend/menu_label.xml',
        'views/backend/website_menu.xml',
        'views/backend/product_label.xml',
        'views/backend/product_template.xml',
        'views/backend/product_attribute.xml',
        'views/backend/product_brand.xml',
        'views/backend/dr_website_content.xml',
        'views/backend/product_pricelist.xml',
        'views/backend/pwa_screenshots.xml',
        'views/backend/pwa_shortcuts.xml',
        'views/backend/res_config_settings.xml',
        'views/backend/dr_theme_config.xml',
        'views/backend/category_label.xml',
        'views/backend/product_category.xml',
        'views/backend/website.xml',
        'views/backend/search_report.xml',

        'data/search_report_cron.xml',

        # Snippets
        'views/snippets/s_mega_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'droggol_theme_common/static/src/js/hooks.js',
            'droggol_theme_common/static/src/js/theme_config/*.xml',
            'droggol_theme_common/static/src/js/product/**/*',
            'droggol_theme_common/static/src/js/product_template_attribute_line/**/*',
        ],
        'website.assets_editor': [
            'droggol_theme_common/static/src/js/theme_config/*.js',
            'droggol_theme_common/static/src/js/theme_config/*.scss',
            'droggol_theme_common/static/src/js/navbar/*',
        ],
        'web.assets_frontend': [
            'droggol_theme_common/static/src/js/notification/**/*',
            'droggol_theme_common/static/src/js/product/**/*',
            'droggol_theme_common/static/src/js/product_template_attribute_line/**/*',
        ],
    },
}
