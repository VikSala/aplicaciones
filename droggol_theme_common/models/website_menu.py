# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

from odoo import api, fields, models


class WebsiteMenu(models.Model):
    _inherit = 'website.menu'

    dr_menu_label_id = fields.Many2one('dr.website.menu.label', string='Label')
    dr_is_highlight_menu = fields.Boolean('Is Highlight Menu?')
    dr_highlight_menu_bg_color = fields.Char('Hightlight Background Color', default='#000000')
    dr_highlight_menu_text_color = fields.Char('Hightlight Text Color', default='#FFFFFF')
    dr_menu_visible_on = fields.Selection([
        ('all', 'All Devices'), ('desktop', 'Only Desktop')
    ], string='Menu Visible On', default='all', required=True)
