# -*- coding: utf-8 -*-
##############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Vishnu KP (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from odoo import models


class SaleOrderLine(models.Model):
    """ Model is inherited to add a new function to order line """
    _inherit = 'sale.order.line'

    def get_product_history_data(self):
        """ Returns the product history data """
        values = []
        customer_id = self.order_id.partner_id
        customer_order = self.env['sale.order'].search(
            [('partner_id', '=', customer_id.id),
             ('state', 'in', ('sale', 'done'))])
        for order in customer_order:
            for line in order.order_line:
                if line.product_id == self.product_id:
                    values.append((0, 0, {'sale_order_id': order.id,
                                          'history_price': line.price_unit,
                                          'history_qty': line.product_uom_qty,
                                          'history_total': order.amount_total
                                          }))
        history_id = self.env['product.sale.order.history'].create({
            'product_id': self.product_id.id,
            'product_sale_history_ids': values})
        return {
            'name': 'Customer Product Sales History',
            'view_mode': 'form',
            'res_model': 'product.sale.order.history',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'res_id': history_id.id
        }


    def _get_current_pricelist_price_unit(self):
        """Return the current pricelist final unit price for this sale line.

        The value is calculated independently from ``price_unit`` so a line
        previously overwritten with a historical customer price can still be
        compared against the current pricelist.
        """
        self.ensure_one()

        if not self.product_id or not self.order_id.pricelist_id:
            return self.price_unit

        line = self.with_company(self.company_id)

        # Precio de tarifa calculado sobre la variante real (flujo normal de venta).
        variant_pricelist_price = line._get_pricelist_price()

        # En website_sale el autocomplete puede calcular la tarifa sobre
        # product.template mientras la ficha trabaja con product.product.
        # Para mantener la misma regla conservadora también en el carrito,
        # comprobamos el precio de tarifa a nivel template y nunca permitimos
        # que una discrepancia template/variant rebaje el precio cobrado.
        template_pricelist_price = line.order_id.pricelist_id._get_product_price(
            line.product_id.product_tmpl_id,
            line.product_uom_qty or 1.0,
            uom=line.product_uom,
            date=line.order_id.date_order,
        )

        pricelist_price = max(
            variant_pricelist_price,
            template_pricelist_price,
        )

        product_taxes = line.product_id.taxes_id._filter_taxes_by_company(
            line.company_id
        )

        return line.product_id._get_tax_included_unit_price_from_price(
            pricelist_price,
            product_taxes=product_taxes,
            fiscal_position=line.order_id.fiscal_position_id,
        )


    def _get_last_customer_history_price(self, partner, product):
        if not partner or not product:
            return False

        orders = self.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.commercial_partner_id.id),
            ('state', 'in', ['sale', 'done']),
            ('order_line.product_id', '=', product.id),
        ], order='date_order desc, id desc', limit=1)

        if not orders:
            return False

        line = orders.order_line.filtered(
            lambda l: l.product_id.id == product.id and l.price_unit > 0
        )[:1]

        return line.price_unit if line else False