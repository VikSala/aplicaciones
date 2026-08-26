from odoo import _, models
from odoo.exceptions import UserError
from odoo.http import request


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _cart_update(self, product_id, line_id=None, add_qty=0, set_qty=0, **kwargs):
        """Hard backend guard for blocked B2B and price-unavailable products."""
        self.ensure_one()
        if self.website_id:
            user = request.env.user if request else self.env.user
            website = self.website_id.with_user(user)
            if website.b2b_is_blocked(user=user):
                raise UserError(_(
                    "Tu cuenta B2B todavía no está autorizada para utilizar el carrito."
                ))

            product = self.env["product.product"].browse(product_id).exists()
            if (
                product
                and website.b2b_is_price_unavailable(product_variant=product)
                and (add_qty > 0 or set_qty > 0)
            ):
                raise UserError(_(
                    "Este producto no tiene un precio disponible. Contacta con nosotros para solicitar información."
                ))

        return super()._cart_update(
            product_id,
            line_id=line_id,
            add_qty=add_qty,
            set_qty=set_qty,
            **kwargs,
        )
