# models/sale_order.py
from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _cart_update(self, product_id=None, line_id=None, add_qty=0, set_qty=0, **kwargs):
        res = super()._cart_update(
            product_id=product_id,
            line_id=line_id,
            add_qty=add_qty,
            set_qty=set_qty,
            **kwargs
        )

        if not self.website_id:
            return res

        website = self.website_id

        if website.is_public_user():
            return res

        line = self.env['sale.order.line'].sudo().browse(res.get('line_id'))

        if line and line.exists():
            history_price = line._get_last_customer_history_price(
                self.partner_id,
                line.product_id
            )
            if history_price:
                line.sudo().write({
                    'price_unit': history_price,
                })

        return res