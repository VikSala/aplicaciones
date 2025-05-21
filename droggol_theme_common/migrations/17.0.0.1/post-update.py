# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

ATTACHMENTS = ['/theme_prime/static/src/xml/frontend/notification_template.xml']
# ------------------
# Migrate documents
# ------------------

def delete_views(domain, env):
    views_to_delete = env['ir.ui.view'].with_context(active_test=False).search(domain)
    _logger.info('DRGL-MIG: (%s) Views to delete: %s' % (len(views_to_delete.ids), views_to_delete.ids))
    if views_to_delete:
        child_views = views_to_delete.mapped('inherit_children_ids')
        _logger.info('DRGL-MIG: (%s) Child Views to delete: %s' % (len(child_views.ids), child_views.ids))
        child_views.unlink()
    dr_views_to_delete = views_to_delete.filtered(lambda v: not len(v.inherit_children_ids))
    if dr_views_to_delete:
        dr_views_to_delete.unlink()

def deactivate_assets(domain, env):
    assets_to_remove = env['ir.asset'].with_context(active_test=False).search(domain)
    _logger.info('DRGL-MIG: (%s) assets to delete: %s' % (len(assets_to_remove.ids), assets_to_remove.ids))
    if assets_to_remove:
        assets_to_remove.unlink()


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    ProductDocument = env['product.document'].sudo()
    for product_id in env['product.template'].search([('dr_document_ids', '!=', False)]):
        for attachment_id in product_id.dr_document_ids:
            new_id = attachment_id.with_context(disable_product_documents_creation=True).copy({'res_id': product_id.id, 'res_model': 'product.template'})
            document_id = ProductDocument.with_context(disable_product_documents_creation=True).create({
                'ir_attachment_id': new_id.id,
                'shown_on_product_page': True,
            })
            attachment_id.unlink()

    _logger.info('DRGL-MIG START: -------------------------------------------- ')
    views_id_to_delete = ["droggol_theme_common"]
    domain = [('arch_fs', 'ilike', f'{view}/%') for view in views_id_to_delete]
    ors = ['|'] * (len(domain) - 1)
    domain = ors + domain
    delete_views(domain, env)
    paths = ['/droggol_theme_common/static/src/js/backend/res_config_settings.js', '/droggol_theme_common/static/src/scss/variants.scss', '/droggol_theme_common/static/src/js/backend/list_view_brand.js']
    domain = [('path', 'in', paths)]
    deactivate_assets(domain, env)
