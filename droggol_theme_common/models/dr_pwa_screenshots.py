# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

from odoo import fields, models


class PWAScreenshots(models.Model):
    _name = 'dr.pwa.screenshots'
    _description = 'PWA Screenshots'
    _order = 'sequence,id'

    website_id = fields.Many2one('website')
    sequence = fields.Integer()
    name = fields.Char(required=True)
    image = fields.Binary()
    sizes = fields.Char()
    form_factor = fields.Selection([
        ('narrow', 'Narrow'),
        ('wide', 'Wide'),
    ], string='Form Factor', default='narrow', required=True)
