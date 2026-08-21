from odoo import api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _signup_create_user(self, values):
        """Assign the blocking tariff only to *free* website signups.

        Invitation/token signups already contain ``partner_id`` and are not
        changed here. This avoids unexpectedly blocking customers explicitly
        invited by an administrator.
        """
        is_free_signup = not values.get("partner_id")
        new_user = super()._signup_create_user(values)

        if not is_free_signup:
            return new_user

        user_sudo = new_user.sudo()
        company = user_sudo.company_id or self.env.company
        blocking_pricelist = self.env["product.pricelist"].sudo()._get_b2b_blocking_pricelist(
            company=company,
            create_if_missing=True,
        )

        # In Odoo 18 the effective partner pricelist is computed from the
        # company-dependent specific_property_product_pricelist. Writing the
        # specific field is therefore the safest way to force the assignment.
        partner = user_sudo.partner_id.sudo().with_company(company)
        partner.write({"specific_property_product_pricelist": blocking_pricelist.id})
        partner.invalidate_recordset(["property_product_pricelist"])

        return new_user
