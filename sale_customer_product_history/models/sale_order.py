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
                pricelist_price = line._get_current_pricelist_price_unit()

                if history_price > pricelist_price:
                    # El histórico es superior: se usa como precio mínimo.
                    # Quitamos cualquier descuento de tarifa para que el precio
                    # efectivo de la línea sea exactamente el histórico.
                    line.write({
                        'price_unit': history_price,
                        'discount': 0.0,
                    })
                else:
                    # La tarifa actual ya es igual o superior al histórico.
                    # Restauramos el cálculo estándar de Odoo, incluso si la
                    # línea tenía anteriormente un precio histórico manual.
                    standard_line = line.with_context(force_price_recomputation=True)
                    standard_line._compute_price_unit()
                    standard_line._compute_discount()

        return res
