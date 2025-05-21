# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Remove assets
    paths = [
        'droggol_theme_common/static/src/js/components/*.xml',
        'droggol_theme_common/static/src/js/product_template_attribute_line.js',
        'droggol_theme_common/static/src/js/product_template_attribute_line.xml',
        'droggol_theme_common/static/src/js/components/*.js',
        'droggol_theme_common/static/src/js/components/*.scss',
        'droggol_theme_common/static/src/js/navbar/*.js',
        'droggol_theme_common/static/src/js/components/notification/*',

        'theme_prime/static/src/js/sidebar.js',
        'theme_prime/static/src/xml/sidebar.xml',
        'theme_prime/static/src/js/suggested_product_slider.js',
        'theme_prime/static/src/xml/frontend/suggested_product_slider.xml',
        'theme_prime/static/src/js/service_worker_register.js',
        'theme_prime/static/src/xml/pwa.xml',
        'theme_prime/static/src/js/frontend/quick_view_dialog.js',
        'theme_prime/static/src/scss/front_end/quick_view.scss',
        'theme_prime/static/src/js/core/cart_confirmation_dialog.js',
        'theme_prime/static/src/xml/core/cart_confirmation_dialog.xml',
        'theme_prime/static/src/js/core/lazy_dialog.js',
        'theme_prime/static/src/xml/core/lazy_dialog.xml',
        'theme_prime/static/src/js/frontend/search.js',
        'theme_prime/static/src/xml/frontend/search_autocomplete.xml',
        'theme_prime/static/src/scss/web_editor.frontend.scss',
    ]
    assets_ids = env['ir.asset'].with_context(active_test=False).search([('path', 'in', paths)])
    if assets_ids:
        _logger.info('Theme Prime v18 Migration: Deleted %s asset(s): %s' % (len(assets_ids.ids), assets_ids.ids))
        assets_ids.unlink()
