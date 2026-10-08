import math

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DeliveryOnTimeTariffRule(models.Model):
    _name = "delivery.ontime.tariff.rule"
    _description = "OnTime Tariff Rate"
    _order = "service, zone, weight_to, id"
    _sql_constraints = [
        (
            "ontime_tariff_unique_bracket",
            "unique(carrier_id, service, zone, weight_to)",
            "An OnTime tariff can only contain one rate per carrier, service, zone and weight bracket.",
        ),
    ]

    active = fields.Boolean(default=True)
    carrier_id = fields.Many2one(
        "delivery.carrier",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="carrier_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )
    service = fields.Selection(
        [
            ("economy_24_48", "XS ECONOMY 24-48h"),
            ("xs_24", "XS 24h"),
        ],
        required=True,
        default="economy_24_48",
        index=True,
    )
    zone = fields.Selection(
        [
            ("PROVINCIAL", "Provincial"),
            ("REGIONAL", "Regional"),
            ("IBERIA", "Iberia"),
            ("CEUTA", "Ceuta"),
            ("MELILLA", "Melilla"),
            ("BALEARES_MAYORES", "Baleares mayores"),
            ("BALEARES_MENORES", "Baleares menores"),
            ("CANARIAS_MAYORES", "Canarias mayores"),
            ("CANARIAS_MENORES", "Canarias menores"),
        ],
        required=True,
        index=True,
    )
    weight_to = fields.Float(
        string="Weight To (kg)",
        required=True,
        digits=(16, 3),
    )
    price = fields.Monetary(
        string="Price",
        required=True,
        currency_field="currency_id",
    )
    extra_kg_price = fields.Monetary(
        string="Additional kg",
        currency_field="currency_id",
        help="Price per additional started kilogram above the highest available tariff bracket.",
    )

    @api.constrains("weight_to", "price", "extra_kg_price")
    def _check_values(self):
        for rate in self:
            if rate.weight_to <= 0:
                raise ValidationError(_("OnTime tariff weight must be greater than zero."))
            if rate.price < 0 or rate.extra_kg_price < 0:
                raise ValidationError(_("OnTime tariff prices cannot be negative."))

    @api.model
    def compute_group_price(self, rates, billable_weight):
        """Return a contract price for one service/zone rate group.

        The PDF uses ceiling brackets (1, 3, 5, 10... kg). If the weight is
        above the last bracket, the last price plus the PDF's "Kg Adicional"
        is used, rounding each started additional kilogram up.
        """
        rates = rates.filtered("active").sorted(lambda rec: (rec.weight_to, rec.id))
        if not rates or billable_weight <= 0:
            return False

        epsilon = 1e-9
        bracket = rates.filtered(lambda rec: rec.weight_to + epsilon >= billable_weight)[:1]
        if bracket:
            return bracket.price

        last = rates[-1]
        if not last.extra_kg_price:
            return False
        additional_weight = max(billable_weight - last.weight_to, 0.0)
        additional_kg = math.ceil(additional_weight - 1e-12)
        return last.price + additional_kg * last.extra_kg_price
