from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


B2B_BLOCKING_PRICELIST_NAME = "B2B - SIN VERIFICAR"
B2B_BLOCKING_FIXED_PRICE = 1000.0


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    is_b2b_blocking_pricelist = fields.Boolean(
        string="Tarifa bloqueadora B2B",
        help=(
            "Marca esta lista de precios como la tarifa usada para clientes "
            "B2B registrados que todavía no han sido verificados."
        ),
        copy=False,
    )

    @api.constrains("is_b2b_blocking_pricelist", "company_id")
    def _check_single_b2b_blocking_pricelist_per_company(self):
        for pricelist in self.filtered("is_b2b_blocking_pricelist"):
            domain = [
                ("is_b2b_blocking_pricelist", "=", True),
                ("id", "!=", pricelist.id),
                ("company_id", "=", pricelist.company_id.id or False),
            ]
            if self.sudo().search_count(domain):
                company_name = pricelist.company_id.display_name or _("Compartida")
                raise ValidationError(
                    _(
                        "Solo puede existir una tarifa bloqueadora B2B por empresa. "
                        "Ya existe otra para: %s"
                    )
                    % company_name
                )

    @api.model
    def _ensure_b2b_blocking_rule(self, pricelist):
        """Ensure the canonical unrestricted global rule at EUR/company currency 1000.

        The lookup is deliberately done on the existing pricelist and global
        scope so module upgrades update the same rule instead of inserting a
        new one on every run.
        """
        pricelist = pricelist.sudo()
        Item = self.env["product.pricelist.item"].sudo().with_company(
            pricelist.company_id or self.env.company
        )

        global_items = Item.search(
            [
                ("pricelist_id", "=", pricelist.id),
                ("applied_on", "=", "3_global"),
            ],
            order="id asc",
        )

        # Reuse the first global rule if one already exists. This also upgrades
        # the old 0/1 EUR rule from previous module versions to 1000.
        rule = global_items[:1]
        vals = {
            "applied_on": "3_global",
            "compute_price": "fixed",
            "fixed_price": B2B_BLOCKING_FIXED_PRICE,
            "min_quantity": 0.0,
            "date_start": False,
            "date_end": False,
        }
        if rule:
            rule.write(vals)
        else:
            vals["pricelist_id"] = pricelist.id
            rule = Item.create(vals)

        # Duplicate global rules on the blocking tariff can make the effective
        # price ambiguous. Keep the oldest/canonical one only.
        duplicates = global_items - rule
        if duplicates:
            duplicates.unlink()

        return rule

    @api.model
    def _get_b2b_blocking_pricelist(self, company=None, create_if_missing=False):
        """Return the canonical B2B blocking pricelist for ``company``.

        The canonical record is resolved by exact name first. This is
        intentional: module upgrades must reuse ``B2B - SIN VERIFICAR`` instead
        of creating another record just because its boolean flag was changed.
        """
        company = company or self.env.company
        company = self.env["res.company"].sudo().browse(company.id)
        Pricelist = self.sudo().with_company(company).with_context(active_test=False)

        # 1) Exact name is the primary identity requested for this tariff.
        pricelist = Pricelist.search(
            [
                ("name", "=", B2B_BLOCKING_PRICELIST_NAME),
                ("company_id", "=", company.id),
            ],
            order="id asc",
            limit=1,
        )

        # 2) Backwards compatibility: reuse an old flagged blocking tariff if
        # it exists under another name instead of creating a duplicate.
        if not pricelist:
            pricelist = Pricelist.search(
                [
                    ("is_b2b_blocking_pricelist", "=", True),
                    ("company_id", "=", company.id),
                ],
                order="id asc",
                limit=1,
            )

        if not pricelist and not create_if_missing:
            return pricelist

        if not pricelist:
            pricelist = Pricelist.create(
                {
                    "name": B2B_BLOCKING_PRICELIST_NAME,
                    "company_id": company.id,
                    "currency_id": company.currency_id.id,
                    "is_b2b_blocking_pricelist": True,
                }
            )
        else:
            # The canonical named pricelist wins. Unmark any stale blocker for
            # the same company first so the SQL/Python constraint cannot clash.
            other_blockers = Pricelist.search(
                [
                    ("is_b2b_blocking_pricelist", "=", True),
                    ("company_id", "=", company.id),
                    ("id", "!=", pricelist.id),
                ]
            )
            if other_blockers:
                other_blockers.write({"is_b2b_blocking_pricelist": False})

            pricelist.write(
                {
                    "name": B2B_BLOCKING_PRICELIST_NAME,
                    "company_id": company.id,
                    "currency_id": company.currency_id.id,
                    "is_b2b_blocking_pricelist": True,
                    "active": True,
                }
            )

        self._ensure_b2b_blocking_rule(pricelist)
        return pricelist

    @api.model
    def b2b_ensure_blocking_pricelists(self):
        """Idempotent install/upgrade entry point loaded from XML data."""
        Company = self.env["res.company"].sudo()
        for company in Company.search([]):
            self._get_b2b_blocking_pricelist(
                company=company,
                create_if_missing=True,
            )
        return True
