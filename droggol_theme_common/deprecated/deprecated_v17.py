# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    dr_document_ids = fields.Many2many('ir.attachment', 'product_template_document_attachment_rel', 'product_template_id', 'attachment_id', string='Deprecated Documents', help='Documents publicly downloadable from eCommerce product page.')


class WebsiteMenu(models.Model):
    _inherit = 'website.menu'

    dr_highlight_menu = fields.Selection([('solid', 'Solid'), ('soft', 'Soft')], string='Highlight Menu', compute='_compute_dr_highlight_menu')

    def _compute_dr_highlight_menu(self):
        for menu in self:
            menu.dr_highlight_menu = ''
