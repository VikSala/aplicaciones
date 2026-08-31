from odoo import fields, models


class ProductWishlistList(models.Model):
    _name = "product.wishlist.list"
    _description = "Lista de favoritos del portal"
    _order = "sequence, id"

    name = fields.Char(string="Nombre", required=True)
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one(
        "res.partner",
        string="Cliente",
        required=True,
        index=True,
        ondelete="cascade",
    )
    website_id = fields.Many2one(
        "website",
        string="Sitio web",
        required=True,
        index=True,
        ondelete="cascade",
    )
    wish_ids = fields.Many2many(
        "product.wishlist",
        "product_wishlist_list_rel",
        "list_id",
        "wish_id",
        string="Productos favoritos",
        copy=False,
    )

    _sql_constraints = [
        (
            "product_wishlist_list_name_partner_website_unique",
            "unique(name, partner_id, website_id)",
            "Ya existe una lista con ese nombre para este cliente.",
        ),
    ]
