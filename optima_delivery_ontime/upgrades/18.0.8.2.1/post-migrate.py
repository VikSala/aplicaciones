from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Bind existing OnTime carriers automatically when there is only one active company."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env["res.company"].search([], limit=2)
    if len(companies) != 1:
        return

    carriers = (
        env["delivery.carrier"]
        .with_context(active_test=False)
        .search([
            ("delivery_type", "=", "ontime"),
            ("company_id", "=", False),
        ])
    )
    if carriers:
        carriers.write({"company_id": companies.id})
