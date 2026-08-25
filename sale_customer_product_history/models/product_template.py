# models/product_template.py
from odoo import models
from odoo.http import request


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _get_b2b_history_product(self, combination_info=None):
        """Return the variant used to look up the customer's last sale price.

        ``website_sale`` calls ``_get_combination_info(only_template=True)`` for
        autocomplete/search results. In that case ``product_id`` is empty, so
        falling back to ``product_variant_id`` is required if we want the same
        historical-price rule in search results and on the product page.
        """
        self.ensure_one()

        product_id = (combination_info or {}).get('product_id')
        if product_id:
            product = self.env['product.product'].sudo().browse(product_id)
            if product.exists():
                return product

        return self.product_variant_id.sudo()

    def _get_sales_prices(self, website):
        res = super()._get_sales_prices(website)

        if not website or website.is_public_user():
            return res

        partner = request.env.user.partner_id.commercial_partner_id
        SaleLine = request.env['sale.order.line'].sudo()

        for product_template in self:
            product = product_template.product_variant_id
            if not product:
                continue

            history_price = SaleLine._get_last_customer_history_price(
                partner,
                product,
            )

            price_values = res.get(product_template.id, {})
            pricelist_price = price_values.get('price_reduce')

            # Regla comercial única:
            # precio web = MAX(último precio vendido, tarifa actual).
            if (
                history_price
                and pricelist_price is not None
                and history_price > pricelist_price
            ):
                price_values['price_reduce'] = history_price
                price_values['price_reduce_taxexcl'] = history_price
                price_values['price_reduce_taxinc'] = history_price
                price_values['base_price'] = history_price

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
        product = self._get_b2b_history_product(res)
        if not product:
            return res

        history_price = request.env['sale.order.line'].sudo()._get_last_customer_history_price(
            partner,
            product,
        )

        # El autocomplete de website_sale usa only_template=True, mientras que
        # la ficha usa la variante real. Algunas tarifas basadas en fórmulas
        # pueden dar resultados distintos entre template y variant. Para no
        # mostrar nunca en la ficha un importe inferior al que la propia tarifa
        # está mostrando en buscador/listados, obtenemos también el cálculo
        # estándar a nivel template y usamos el mayor precio de tarifa.
        template_info = None
        if not only_template:
            template_info = super()._get_combination_info(
                combination=False,
                product_id=False,
                add_qty=add_qty,
                parent_combination=False,
                only_template=True,
                **kwargs
            )

        variant_pricelist_price = res.get('price')
        template_pricelist_price = (
            template_info.get('price')
            if template_info is not None
            else None
        )

        tariff_candidates = [
            price for price in (variant_pricelist_price, template_pricelist_price)
            if price is not None
        ]
        pricelist_price = max(tariff_candidates) if tariff_candidates else None

        # Si el cálculo estándar a nivel template es superior al de la variante,
        # hacemos que la ficha respete ese precio de tarifa. Esto mantiene
        # coherencia con el autocomplete/listados y evita vender por debajo de
        # una subida de tarifa.
        if (
            template_info is not None
            and template_pricelist_price is not None
            and variant_pricelist_price is not None
            and template_pricelist_price > variant_pricelist_price
        ):
            res['price'] = template_pricelist_price
            res['list_price'] = max(
                template_info.get('list_price') or template_pricelist_price,
                template_pricelist_price,
            )
            res['has_discounted_price'] = bool(
                res['list_price'] > res['price']
            )
            if 'compare_list_price' in template_info:
                res['compare_list_price'] = template_info['compare_list_price']
            if res.get('base_unit_name'):
                res['base_unit_price'] = self._get_base_unit_price(res['price'])

        # Finalmente aplicamos la regla de negocio: el histórico solo gana si
        # es SUPERIOR al precio actual de tarifa. Nunca puede impedir una subida.
        if (
            history_price
            and pricelist_price is not None
            and history_price > pricelist_price
        ):
            res['price'] = history_price
            res['list_price'] = history_price
            res['has_discounted_price'] = False
            res['compare_list_price'] = 0
            if res.get('base_unit_name'):
                res['base_unit_price'] = self._get_base_unit_price(history_price)

        return res
