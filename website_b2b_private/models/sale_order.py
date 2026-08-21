from odoo import _, models
from odoo.exceptions import UserError
from odoo.http import request


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _cart_update(self, product_id, line_id=None, add_qty=0, set_qty=0, **kwargs):
        """Hard backend guard for every website cart mutation.

        Odoo's JSON route also uses ``set_qty`` to edit existing lines. The
        product-level add-to-cart check alone is therefore not enough: this
        model guard prevents adding, increasing, decreasing or removing lines
        while the current website user is not B2B-approved.
        """
        self.ensure_one()
        if self.website_id:
            user = request.env.user if request else self.env.user
            website = self.website_id.with_user(user)
            if website.b2b_is_blocked(user=user):
                raise UserError(_(
                    "Tu cuenta B2B todavía no está autorizada para utilizar el carrito."
                ))
        return super()._cart_update(
            product_id,
            line_id=line_id,
            add_qty=add_qty,
            set_qty=set_qty,
            **kwargs,
        )
