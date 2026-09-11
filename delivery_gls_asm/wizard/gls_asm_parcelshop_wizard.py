# Copyright 2026
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class GlsAsmParcelShopSearchWizard(models.TransientModel):
    _name = "gls.asm.parcelshop.search.wizard"
    _description = "GLS ParcelShop Search"

    carrier_id = fields.Many2one(
        "delivery.carrier", string="Carrier", required=True, readonly=True
    )
    postal_code = fields.Char(
        string="Postal Code",
        required=True,
        help="GLS also accepts a town or a full address in this field.",
    )
    country_id = fields.Many2one(
        "res.country",
        string="Country",
        required=True,
        default=lambda self: self._default_country_id(),
    )
    networks = fields.Char(
        string="ParcelShop Networks",
        required=True,
        default="1",
        help=(
            "Use 1 to search all available networks. GLS also accepts one or more "
            "specific network codes separated by semicolons."
        ),
    )
    line_ids = fields.One2many(
        "gls.asm.parcelshop.search.line", "wizard_id", string="ParcelShops"
    )
    search_done = fields.Boolean(readonly=True)
    result_count = fields.Integer(string="Results", readonly=True)

    @api.model
    def _default_country_id(self):
        country = self.env.ref("base.es", raise_if_not_found=False)
        return country.id if country else False

    def action_search(self):
        self.ensure_one()
        country_code = (self.country_id.code or "").upper()
        if not country_code:
            raise UserError(_("The selected country does not have an ISO code."))

        shops = self.carrier_id.gls_asm_search_parcelshops(
            self.postal_code,
            country_code=country_code,
            networks=self.networks,
        )
        self.line_ids.unlink()
        line_model = self.env["gls.asm.parcelshop.search.line"]
        for sequence, shop in enumerate(shops, start=1):
            values = dict(shop)
            values.update({"wizard_id": self.id, "sequence": sequence})
            line_model.create(values)
        self.write({"search_done": True, "result_count": len(shops)})

        view = self.env.ref("delivery_gls_asm.gls_asm_parcelshop_search_wizard_form")
        return {
            "name": _("GLS ParcelShop Search"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": self._name,
            "view_id": view.id,
            "views": [(view.id, "form")],
            "target": "new",
            "res_id": self.id,
            "context": self.env.context,
        }


class GlsAsmParcelShopSearchLine(models.TransientModel):
    _name = "gls.asm.parcelshop.search.line"
    _description = "GLS ParcelShop Search Result"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    wizard_id = fields.Many2one(
        "gls.asm.parcelshop.search.wizard",
        required=True,
        ondelete="cascade",
    )
    network_id = fields.Char(string="Network")
    code = fields.Char(string="GLS Point Code")
    name = fields.Char(string="Name")
    address = fields.Char(string="Address")
    city = fields.Char(string="City")
    postal_code = fields.Char(string="Postal Code")
    country_code = fields.Char(string="Country")
    latitude = fields.Float(string="Latitude", digits=(16, 7))
    longitude = fields.Float(string="Longitude", digits=(16, 7))
    distance = fields.Char(string="Distance")
    monday_hours = fields.Char(string="Monday")
    tuesday_hours = fields.Char(string="Tuesday")
    wednesday_hours = fields.Char(string="Wednesday")
    thursday_hours = fields.Char(string="Thursday")
    friday_hours = fields.Char(string="Friday")
    saturday_hours = fields.Char(string="Saturday")

    schedule = fields.Text(string="Opening Hours", compute="_compute_schedule")
    full_address = fields.Char(string="Full Address", compute="_compute_full_address")

    @api.depends("address", "city", "postal_code", "country_code")
    def _compute_full_address(self):
        for line in self:
            city_part = " ".join(filter(None, [line.postal_code, line.city]))
            line.full_address = ", ".join(
                filter(None, [line.address, city_part, line.country_code])
            )

    @api.depends(
        "monday_hours",
        "tuesday_hours",
        "wednesday_hours",
        "thursday_hours",
        "friday_hours",
        "saturday_hours",
    )
    def _compute_schedule(self):
        labels = [
            (_("Mon"), "monday_hours"),
            (_("Tue"), "tuesday_hours"),
            (_("Wed"), "wednesday_hours"),
            (_("Thu"), "thursday_hours"),
            (_("Fri"), "friday_hours"),
            (_("Sat"), "saturday_hours"),
        ]
        for line in self:
            line.schedule = "\n".join(
                f"{label}: {getattr(line, field_name)}"
                for label, field_name in labels
                if getattr(line, field_name)
            )
