# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

from odoo import models


class ProductProduct(models.Model):
    _name = 'product.product'
    _inherit = ['product.product', 'dr.products.mixin']
