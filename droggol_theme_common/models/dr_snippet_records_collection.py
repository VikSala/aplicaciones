# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

from odoo import fields, models


class DrSnippetRecordsCollection(models.Model):
    _name = 'dr.snippet.records.collection'
    _description = 'Snippet Records Collection'

    name = fields.Char('Name')
    dr_res_model = fields.Selection([
        ('product.template', 'Product'),
        ('product.product', 'Variant'),
        ('product.public.category', 'category'),
        ('product.attribute.value', 'Brand')
    ], string='Model')

    product_ids = fields.Many2many('product.template', string='Product')
    product_variant_ids = fields.Many2many('product.product', string='Product Variant')
    category_ids = fields.Many2many('product.public.category', string='Category')
    brand_ids = fields.Many2many('product.attribute.value', string='Brand')
    website_id = fields.Many2one('website', string='Website')

    def _dr_get_related_field(self, model):
        data = {'product.template': 'product_ids', 'product.product': 'product_variant_ids', 'product.public.category': 'category_ids', 'product.attribute.value': 'brand_ids'}
        return data.get(model)