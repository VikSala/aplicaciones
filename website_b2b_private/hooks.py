from odoo import api, SUPERUSER_ID


def post_init_hook(env):
    """Enable free signup and ensure the canonical blocking pricelist.

    Pricelist creation is also executed from XML data on every upgrade; this
    hook keeps first-install behaviour explicit and idempotent.
    """
    env["website"].sudo().search([]).write({"auth_signup_uninvited": "b2c"})
    env["product.pricelist"].sudo().b2b_ensure_blocking_pricelists()
