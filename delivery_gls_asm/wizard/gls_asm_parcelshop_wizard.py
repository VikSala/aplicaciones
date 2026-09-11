# Copyright 2026 Optima
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


class GlsAsmParcelshopSearchWizard(models.TransientModel):
    _name = "gls.asm.parcelshop.search.wizard"
    _description = "GLS ParcelShop Search"

    carrier_id = fields.Many2one(
        "delivery.carrier",
        string="GLS Carrier",
        required=True,
        readonly=True,
    )
    zip_code = fields.Char(string="Postal Code", required=True)
    country_code = fields.Char(string="Country Code", required=True, default="ES", size=2)
    distance = fields.Integer(string="Radius (km)", required=True, default=30)
    max_results = fields.Integer(string="Maximum Results", required=True, default=10)
    parcelshop_type = fields.Selection(
        [
            ("ALL", "All"),
            ("SHOP", "Shop"),
            ("SHOPINSHOP", "Shop in Shop"),
            ("LOCKER", "Locker"),
        ],
        string="Point Type",
        default="ALL",
    )
    line_ids = fields.One2many(
        "gls.asm.parcelshop.search.line",
        "wizard_id",
        string="ParcelShops",
        readonly=True,
    )

    def action_search(self):
        self.ensure_one()
        if not self.carrier_id:
            raise UserError(_("Select a GLS carrier."))
        shops = self.carrier_id._gls_parcelshop_search(
            zip_code=self.zip_code,
            country_code=self.country_code,
            distance=self.distance,
            max_results=self.max_results,
            parcelshop_type=(
                None if self.parcelshop_type == "ALL" else self.parcelshop_type
            ),
        )
        commands = [(5, 0, 0)]
        commands.extend(
            (0, 0, shop)
            for shop in shops
        )
        self.write({"line_ids": commands})
        return {
            "type": "ir.actions.act_window",
            "name": _("Search GLS ParcelShops"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class GlsAsmParcelshopSearchLine(models.TransientModel):
    _name = "gls.asm.parcelshop.search.line"
    _description = "GLS ParcelShop Search Result"
    _order = "distance, id"

    wizard_id = fields.Many2one(
        "gls.asm.parcelshop.search.wizard",
        required=True,
        ondelete="cascade",
    )
    parcelshop_id = fields.Char(string="ParcelShop ID", readonly=True)
    shop_type = fields.Char(string="Type", readonly=True)
    name = fields.Char(string="Name", readonly=True)
    address = fields.Char(string="Address", readonly=True)
    street = fields.Char(string="Street", readonly=True)
    zip_code = fields.Char(string="Postal Code", readonly=True)
    city = fields.Char(string="City", readonly=True)
    country_code = fields.Char(string="Country", readonly=True)
    latitude = fields.Float(string="Latitude", digits=(10, 6), readonly=True)
    longitude = fields.Float(string="Longitude", digits=(10, 6), readonly=True)
    distance = fields.Float(string="Distance (km)", digits=(10, 3), readonly=True)
    opening_hours = fields.Text(string="Opening Hours", readonly=True)
