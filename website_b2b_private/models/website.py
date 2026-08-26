from odoo import models
from odoo.tools.float_utils import float_is_zero


class Website(models.Model):
    _inherit = "website"

    def b2b_can_purchase(self, user=None):
        """Central B2B authorization rule."""
        self.ensure_one()
        user = user or self.env.user

        if user._is_public():
            return False

        # Backend/internal users must never be locked out by the website B2B
        # restriction. This also keeps website editors/admins usable.
        if user._is_internal():
            return True

        partner = user.partner_id.commercial_partner_id.sudo().with_company(self.company_id)
        pricelist = partner.property_product_pricelist
        return bool(pricelist and not pricelist.is_b2b_blocking_pricelist)

    def b2b_is_blocked(self, user=None):
        self.ensure_one()
        return not self.b2b_can_purchase(user=user)

    def b2b_is_price_unavailable(self, product=None, product_variant=None):
        """Return whether a website product must be treated as having no price.

        Business rule requested for the B2B website:

        * the product template name contains the literal ``VZ``; and
        * the current variant cost (``standard_price``) is zero.

        ``standard_price`` is intentionally read with ``sudo`` *inside* this
        server-side helper. Portal/public users never receive that cost value;
        QWeb and website controllers only consume the resulting boolean.
        """
        self.ensure_one()

        template = self.env["product.template"]
        variant = self.env["product.product"]

        if product_variant:
            variant = product_variant.exists()
            if variant:
                template = variant.product_tmpl_id

        if not template and product:
            if product._name == "product.product":
                variant = product.exists()
                template = variant.product_tmpl_id if variant else template
            elif product._name == "product.template":
                template = product.exists()

        if not template or "VZ" not in (template.name or ""):
            return False

        if not variant:
            # The website product page has a concrete current variant. For a
            # template-level call (e.g. a card), use its website/default variant.
            variant = template.product_variant_id

        if not variant:
            return False

        variant_sudo = variant.sudo().with_company(self.company_id)
        currency = variant_sudo.company_id.currency_id or self.company_id.currency_id
        rounding = currency.rounding if currency else 0.01
        return float_is_zero(variant_sudo.standard_price, precision_rounding=rounding)
