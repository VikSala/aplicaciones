from odoo import models


class Website(models.Model):
    _inherit = "website"

    def b2b_can_purchase(self, user=None):
        """Central B2B authorization rule used by the next phases.

        Phase 1 only creates the rule; it does not yet hide prices, stock or
        cart elements. Those integrations are added incrementally later.
        """
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
