# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

import datetime
import random
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from odoo import Command, api, fields, models


class ProductTemplate(models.Model):
    _name = "product.template"
    _inherit = ['product.template', 'dr.products.mixin']

    dr_label_id = fields.Many2one('dr.product.label', string='Label')

    dr_product_tab_ids = fields.Many2many('dr.website.content', 'product_template_tab_rel', 'product_template_id', 'tab_id', string='Product Tabs')
    dr_product_offer_ids = fields.Many2many('dr.website.content', 'product_template_offer_rel', 'product_template_id', 'offer_id', string='Product Info')

    dr_brand_value_id = fields.Many2one('product.attribute.value', compute='_compute_dr_brand_value_id', inverse='_inverse_dr_brand_value_id', search='_search_dr_brand_value_id', string='Brand')
    dr_brand_attribute_ids = fields.Many2many('product.attribute', compute='_compute_dr_brand_attribute_ids')

    dr_free_qty = fields.Float('Free To Use Quantity', compute='_compute_dr_free_qty', search='_search_dr_free_qty', compute_sudo=False, digits='Product Unit of Measure')

    dr_ptav_ids = fields.One2many('product.template.attribute.value', 'product_tmpl_id')

    def _search_dr_brand_value_id(self, operator, value):
        if operator in ['in', 'not in']:
            return [('attribute_line_ids.value_ids', operator, value)]
        elif operator in ['ilike', 'not ilike', '=', '!=']:
            brand_attribute_id = self._get_brand_attribute()
            values = self.env['product.attribute.value'].search([('name', operator, value), ('attribute_id', 'in', brand_attribute_id.ids)])
            return [('attribute_line_ids.value_ids', 'in', values.ids)]
        # Does not support other cases
        return []

    def _compute_dr_brand_value_id(self):
        for product in self:
            brand_lines = product.attribute_line_ids.filtered(lambda x: x.attribute_id.dr_is_brand)
            product.dr_brand_value_id = self.env['product.attribute.value']
            if brand_lines:
                product.dr_brand_value_id = brand_lines[0].value_ids[0]

    def _inverse_dr_brand_value_id(self):
        brand_value_id = self.dr_brand_value_id
        for product in self:
            brand_lines = product.attribute_line_ids.filtered(lambda x: x.attribute_id.dr_is_brand)
            brand_line = brand_lines and brand_lines[0]
            if brand_line and brand_value_id:
                brand_line.value_ids = brand_value_id
            elif brand_line and not brand_value_id:
                brand_line.unlink()
            elif brand_value_id:
                product.attribute_line_ids = [Command.create({
                    'attribute_id': brand_value_id.attribute_id.id,
                    'value_ids': [Command.set(brand_value_id.ids)],
                })]

    def _compute_dr_brand_attribute_ids(self):
        attributes = self._get_brand_attribute()
        for product in self:
            product.dr_brand_attribute_ids = attributes

    def _get_brand_attribute(self):
        return self.env['product.attribute'].search([('dr_is_brand', '=', True)])

    @api.depends('product_variant_ids.free_qty')
    def _compute_dr_free_qty(self):
        res = self._compute_dr_free_qty_quantities_dict()
        for template in self:
            template.dr_free_qty = res[template.id]['free_qty']

    def _compute_dr_free_qty_quantities_dict(self):
        website = self.env['website'].get_current_website()
        variants_available = {
            p['id']: p for p in self.sudo().with_context(warehouse_id=website.warehouse_id.id).product_variant_ids.read(['free_qty'])
        }
        prod_available = {}
        for template in self:
            free_qty = 0
            for p in template.product_variant_ids:
                free_qty += variants_available[p.id]['free_qty']
            prod_available[template.id] = {
                'free_qty': free_qty,
            }
        return prod_available

    def _search_dr_free_qty(self, operator, value):
        website = self.env['website'].get_current_website()
        domain = [('free_qty', operator, value)]
        product_variant_query = self.env['product.product'].sudo().with_context(warehouse_id=website.warehouse_id.id)._search(domain)
        return [('product_variant_ids', 'in', product_variant_query)]

    def get_content_product_info(self):
        self.ensure_one()
        website_id = self.env['website'].get_current_website()
        return self.dr_product_offer_ids | website_id.dr_product_info_ids

    def get_content_product_tabs(self):
        self.ensure_one()
        website_id = self.env['website'].get_current_website()
        return self.dr_product_tab_ids | website_id.dr_product_tab_ids

    def get_recent_sold_qty(self):
        website_id = self.env['website'].get_current_website()
        config = website_id._get_dr_theme_config('json_product_recent_sales')
        if website_id and config.get('enabled'):
            if config.get('mode') == 'real':
                domain = [
                    ('product_tmpl_id', 'in', self.ids),
                    ('state', '=', 'sale'),
                    ('company_id', '=', self.env.company.id),
                    ('website_id', '=', website_id.id),
                    ('date', '>=', fields.Datetime.now() - relativedelta(hours=config.get('duration', 24))),
                ]
                return {
                    product.id: int(qty) if (qty % 1) == 0 else qty
                    for product, qty in self.env['sale.report'].sudo()._read_group(
                        domain=domain,
                        groupby=['product_tmpl_id'],
                        aggregates=['product_uom_qty:sum'],
                    )
                }
            else:
                return {product_id.id: self._get_random_number(config.get('fake_min_threshold', 1), config.get('fake_max_threshold', 15), product_id.id) for product_id in self}
        return {product_id.id: 0 for product_id in self}

    def get_product_view_count(self):
        website_id = self.env['website'].get_current_website()
        config = website_id._get_dr_theme_config('json_product_view_count')
        if website_id and config.get('enabled'):
            if config.get('mode') == 'real':
                results = self.env['website.track'].sudo()._read_group([
                    ('product_id', 'in', self.product_variant_ids.ids),
                    ('visit_datetime', '>', fields.datetime.now() - relativedelta(days=1)),
                    ('visitor_id.website_id', '=', website_id.id),
                    ('visitor_id.last_connection_datetime', '>', fields.datetime.now() - relativedelta(minutes=5)),
                ], ['visitor_id'], ['product_id:array_agg'])

                views = defaultdict(lambda: -1)
                for visitor_id, product_ids in results:
                    for product_tmpl_id in self:
                        if set(product_tmpl_id.product_variant_ids.ids).intersection(product_ids):
                            views[product_tmpl_id.id] += 1
                return views
            else:
                return {product_id.id: self._get_random_number(config.get('fake_min_threshold', 1), config.get('fake_max_threshold', 8), product_id.id, 'per_minute') for product_id in self}
        return {product_id.id: 0 for product_id in self}

    @api.model
    def _get_random_number(self, min_value=1, max_value=10, unique_int=0, duration='per_hour'):
        total_seed = None
        current_date = datetime.datetime.now()
        if duration == 'per_day':
            total_seed = current_date.month + current_date.day
        if duration == 'per_hour':
            total_seed = current_date.hour + current_date.month + current_date.day
        if duration == 'per_minute':
            total_seed = current_date.hour + current_date.month + current_date.day + current_date.minute
        if total_seed and unique_int:
            total_seed += unique_int
        random.seed(total_seed)
        result = random.randint(min_value, max_value)
        random.seed()
        return result

    @api.model
    def _search_get_detail(self, website, order, options):
        res = super()._search_get_detail(website, order, options)
        # Hide out of stock
        if options.get('hide_out_of_stock'):
            res['base_domain'].append(['|', '|', ('is_storable', '=', False), ('allow_out_of_stock_order', '=', True), '&', ('dr_free_qty', '>', 0), ('allow_out_of_stock_order', '=', False)])
        # Rating
        ratings = options.get('rating')
        if ratings:
            result = self.env['rating.rating'].sudo().read_group([('res_model', '=', 'product.template')], ['rating:avg'], groupby=['res_id'], lazy=False)
            rating_product_ids = []
            for rating in ratings:
                rating_product_ids.extend([item['res_id'] for item in result if item['rating'] >= int(rating)])
            if rating_product_ids:
                res['base_domain'].append([('id', 'in', rating_product_ids)])
            else:
                res['base_domain'].append([('id', 'in', [])])
        return res

    def _get_image_size_based_grid(self, columns, view_mode):
        if view_mode == 'list':
            return 'image_1024'
        if columns <= 2:
            return 'image_1024'
        return 'image_512'

    def _get_product_preview_swatches(self, limit=3):
        swatches = []
        for ptav in self.dr_ptav_ids:
            if ptav.ptav_active and ptav.ptav_product_variant_ids:
                vals = {'id': ptav.id, 'name': ptav.name, 'preview_image': '/web/image/product.product/%s' % ptav.ptav_product_variant_ids.ids[0]}
                if ptav.dr_thumb_image:
                    vals.update({'type': 'image', 'value': '/web/image/product.template.attribute.value/%s/dr_thumb_image' % ptav.id})
                    swatches.append(vals)
                elif ptav.image:
                    vals.update({'type': 'image', 'value': '/web/image/product.template.attribute.value/%s/image' % ptav.id})
                    swatches.append(vals)
                elif ptav.html_color:
                    vals.update({'type': 'color', 'value': ptav.html_color})
                    swatches.append(vals)
        return {'swatches': swatches[:limit], 'more': len(swatches) - limit}

    def _get_combination_info(self, combination=False, product_id=False, add_qty=1.0, parent_combination=False, only_template=False):
        combination_info = super()._get_combination_info(combination=combination, product_id=product_id, add_qty=add_qty, parent_combination=parent_combination, only_template=only_template)
        website = self.env['website'].get_current_website()
        website_has_theme_prime = website._dr_website_has_theme_prime()
        if website and website_has_theme_prime:
            combination_info['has_b2b_access'] = website._dr_has_b2b_access()
            if combination_info['product_id']:
                product_variant_id = self.env['product.product'].browse(combination_info['product_id'])
                # Product Price Offer
                combination_info['product_price_offer'] = product_variant_id._get_product_pricelist_offer()
                # Bulk Price
                if website._get_dr_theme_config('bool_show_bulk_price') and combination_info.get('has_b2b_access') and combination_info.get('is_combination_possible'):
                    ProductTemplate = self.env['product.template']
                    IrQwebFieldFloat = self.env['ir.qweb.field.float']
                    IrQwebFieldMonetary = self.env['ir.qweb.field.monetary']

                    bulk_price = []
                    all_rule_ids = website.pricelist_id._get_applicable_rules(product_variant_id, fields.Datetime.now()).filtered(lambda x: x.min_quantity)
                    applicable_rule_ids = self.env['product.pricelist.item']
                    for rule in all_rule_ids:
                        if not applicable_rule_ids.filtered(lambda x: x.min_quantity == rule.min_quantity):
                            applicable_rule_ids += rule

                    for rule_id in applicable_rule_ids.sorted(lambda x: x.min_quantity):
                        price = rule_id._compute_price(product_variant_id, rule_id.min_quantity, product_variant_id.uom_id, fields.Datetime.now(), website.currency_id)
                        price = ProductTemplate._apply_taxes_to_price(price, website.currency_id, combination_info['product_taxes'], combination_info['taxes'], product_variant_id)
                        list_price = combination_info.get('list_price')
                        bulk_price.append({
                            'id': rule_id.id,
                            'qty': rule_id.min_quantity,
                            'formatted_qty': IrQwebFieldFloat.value_to_html(rule_id.min_quantity, {'decimal_precision': 'Product Unit of Measure'}), #TO-REMOVE
                            'price': price,
                            'formatted_price': IrQwebFieldMonetary.value_to_html(price, {'display_currency': website.currency_id}),
                            'saving_price': IrQwebFieldMonetary.value_to_html((list_price - price)* rule_id.min_quantity, {'display_currency': website.currency_id}) if rule_id.sudo()._show_discount() else False,
                            'uom_name': product_variant_id.uom_id.name,
                        })
                    combination_info['bulk_price'] = bulk_price
                # Extra fields
                IrUiView = self.env['ir.ui.view']
                combination_info['tp_extra_fields'] = IrUiView._render_template('theme_prime.product_extra_fields', values={'website': website, 'product_variant': product_variant_id, 'product': product_variant_id.product_tmpl_id})
            # Hide price per UoM feature for B2B mode
            if not combination_info.get('has_b2b_access'):
                combination_info['base_unit_price'] = 0
                combination_info['price_extra'] = 0
                combination_info['list_price'] = 0
                combination_info['price'] = 0
        return combination_info


class ProductTemplateAttributeValue(models.Model):
    _inherit = 'product.template.attribute.value'

    def _get_extra_price(self, combination_info):
        if not combination_info.get('has_b2b_access', True):
            return 0.0
        return super()._get_extra_price(combination_info=combination_info)
