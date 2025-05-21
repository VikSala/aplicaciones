# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

from odoo import fields, models
from odoo.tools.translate import html_translate


class DrWebsiteContent(models.Model):
    _name = 'dr.website.content'
    _description = 'Website Content'
    _inherit = 'dr.cache.mixin'
    _order = 'sequence,id'

    sequence = fields.Integer()
    name = fields.Char(required=True, translate=True)
    content_type = fields.Selection([('tab', 'Product Tab'), ('offer_popup', 'Product Info'), ('attribute_popup', 'Attribute Guide')], default='tab', required=True, string='Type')
    identifier = fields.Char('Label', help="Used for internal purpose to identify your content. Like, In backend display in dropdown)")
    product_info_visibility = fields.Selection([
        ('list', 'List'),
        ('card', 'Card'),
        ('link', 'Link'),
    ], string='Visibility', default='list')
    description = fields.Html(sanitize_attributes=False, translate=html_translate, sanitize_form=False)
    content = fields.Html(sanitize_attributes=False, translate=html_translate, sanitize_form=False)
    popup_style = fields.Selection([('dialog', 'Dialog'), ('sidebar', 'Sidebar')], default='dialog', string='Popup Style')
    image = fields.Image(help='You can upload an image that will be used as icon.', max_width=64, max_height=64)
    icon = fields.Char(default='list')
    active = fields.Boolean(default=True)

    dr_tab_products_ids = fields.Many2many('product.template', 'product_template_tab_rel', 'tab_id', 'product_template_id', string='Tab Products')
    dr_offer_products_ids = fields.Many2many('product.template', 'product_template_offer_rel', 'offer_id', 'product_template_id', string='Offer Products')

    def _compute_display_name(self):
        for content in self:
            name = content.name
            if content.identifier:
                name = f'[{content.identifier}] {name}'
            content.display_name = name

    def open_design_page(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': '/droggol_theme_common/design_content/%s?enable_editor=1' % (self.id),
        }
