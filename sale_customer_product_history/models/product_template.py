# models/product_template.py
from odoo import models
from odoo.http import request


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _get_sales_prices(self, website):
        res = super()._get_sales_prices(website)

        if not website or website.is_public_user():
            return res

        partner = request.env.user.partner_id.commercial_partner_id
        SaleLine = request.env['sale.order.line'].sudo()

        for product_template in self:
            product = product_template.product_variant_id

            history_price = SaleLine._get_last_customer_history_price(
                partner,
                product
            )

            if history_price:
                res[product_template.id]['price_reduce'] = history_price
                res[product_template.id]['price_reduce_taxexcl'] = history_price
                res[product_template.id]['price_reduce_taxinc'] = history_price
                res[product_template.id]['base_price'] = history_price

        return res

    def _get_combination_info(
        self,
        combination=False,
        product_id=False,
        add_qty=1,
        parent_combination=False,
        only_template=False,
        **kwargs
    ):
        res = super()._get_combination_info(
            combination=combination,
            product_id=product_id,
            add_qty=add_qty,
            parent_combination=parent_combination,
            only_template=only_template,
            **kwargs
        )

        website = getattr(request, 'website', False)
        if not website or website.is_public_user():
            return res

        partner = request.env.user.partner_id.commercial_partner_id
        product = request.env['product.product'].sudo().browse(res.get('product_id'))

        if product and product.exists():
            history_price = request.env['sale.order.line']._get_last_customer_history_price(
                partner,
                product
            )
            if history_price:
                res['price'] = history_price
                res['list_price'] = history_price
                res['has_discounted_price'] = False

        return res