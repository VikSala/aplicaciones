import math
import unicodedata

from odoo import _, api, fields, models


def _norm_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.upper().strip().split())


class OptimaGlsTariffBook(models.Model):
    _name = "optima.gls.tariff.book"
    _description = "Optima GLS Tariff Book"
    _order = "code desc, id desc"

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    template_version = fields.Char()
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref("base.EUR", raise_if_not_found=False),
    )
    source_filename = fields.Char(readonly=True)
    source_hash = fields.Char(readonly=True)
    imported_at = fields.Datetime(readonly=True)
    active = fields.Boolean(default=True)
    service_ids = fields.One2many("optima.gls.tariff.service", "book_id", string="Services")
    postal_ids = fields.One2many("optima.gls.tariff.postal", "book_id", string="Postal master")
    border_ids = fields.One2many("optima.gls.tariff.border", "book_id", string="Bordering provinces")

    _sql_constraints = [
        ("optima_gls_tariff_book_code_uniq", "unique(code)", "GLS tariff book code must be unique."),
    ]


class OptimaGlsTariffPostal(models.Model):
    _name = "optima.gls.tariff.postal"
    _description = "Optima GLS Postal Province Master"
    _order = "postal_prefix"

    book_id = fields.Many2one("optima.gls.tariff.book", required=True, ondelete="cascade", index=True)
    postal_prefix = fields.Char(required=True, index=True)
    province = fields.Char(required=True)
    source = fields.Char()

    _sql_constraints = [
        (
            "optima_gls_tariff_postal_uniq",
            "unique(book_id, postal_prefix)",
            "Postal prefix must be unique inside a GLS tariff book.",
        ),
    ]


class OptimaGlsTariffBorder(models.Model):
    _name = "optima.gls.tariff.border"
    _description = "Optima GLS Bordering Province Rule"
    _order = "origin_province, destination_province"

    book_id = fields.Many2one("optima.gls.tariff.book", required=True, ondelete="cascade", index=True)
    origin_province = fields.Char(required=True)
    destination_province = fields.Char(required=True)
    source = fields.Char()
    confirmed_by_gls = fields.Boolean(default=False)
    notes = fields.Char()


class OptimaGlsTariffService(models.Model):
    _name = "optima.gls.tariff.service"
    _description = "Optima GLS Tariff Service"
    _order = "valid_from desc, code"

    book_id = fields.Many2one("optima.gls.tariff.book", required=True, ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="book_id.currency_id", store=True, readonly=True)
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    valid_from = fields.Date(required=True)
    valid_to = fields.Date(required=True)
    gls_service_hint = fields.Char()
    gls_shiptime_hint = fields.Char()
    volumetric_factor_kg_m3 = fields.Float(default=167.0, digits=(16, 4))
    mono_parcel = fields.Boolean(default=False)
    max_packages = fields.Integer(default=1)
    zone_mode = fields.Selection(
        [
            ("EXPLICIT_RULES", "Explicit rules"),
            ("AUTO_BORDERING_PROVINCES", "Same / bordering / rest"),
            ("EXPLICIT_MATRIX", "Explicit matrix"),
        ],
        required=True,
        default="EXPLICIT_RULES",
    )
    origin_postal_code = fields.Char()
    origin_province = fields.Char()
    additional_kg_rounding = fields.Selection(
        [("CEIL", "Round additional kilograms up"), ("EXACT", "Exact additional kilograms")],
        required=True,
        default="CEIL",
    )
    surcharge_mode = fields.Selection(
        [("ADD_ON_BASE", "Add all surcharges on base price")],
        required=True,
        default="ADD_ON_BASE",
    )
    active = fields.Boolean(default=True)
    notes = fields.Text()

    rate_ids = fields.One2many("optima.gls.tariff.rate", "service_id", string="Rates")
    surcharge_ids = fields.One2many("optima.gls.tariff.surcharge", "service_id", string="Surcharges")
    zone_ids = fields.One2many("optima.gls.tariff.zone", "service_id", string="Zone rules")
    limit_ids = fields.One2many("optima.gls.tariff.limit", "service_id", string="Limits")

    _sql_constraints = [
        (
            "optima_gls_tariff_service_uniq",
            "unique(book_id, code)",
            "Service code must be unique inside a GLS tariff book.",
        ),
    ]

    def _date_for_order(self, order):
        self.ensure_one()
        # Use the current commercial year for checkout pricing. A web cart can
        # have an old date_order after sitting open for days/weeks, which must
        # not force an obsolete or not-yet-started exact-date interpretation.
        return fields.Date.context_today(order)

    @staticmethod
    def _period_overlaps_year(valid_from, valid_to, on_date):
        """Return True when a dated rule belongs to the active tariff year."""
        year_start = on_date.replace(month=1, day=1)
        year_end = on_date.replace(month=12, day=31)
        return (not valid_from or valid_from <= year_end) and (not valid_to or valid_to >= year_start)

    def _postal_province(self, postal_code):
        self.ensure_one()
        digits = "".join(char for char in str(postal_code or "") if char.isdigit())
        if len(digits) < 2:
            return ""
        row = self.book_id.postal_ids.filtered(lambda rec: rec.postal_prefix == digits[:2])[:1]
        return row.province if row else ""

    def _origin_province_for_order(self, order):
        self.ensure_one()
        # The tariff contract is tied to the GLS origin agency, not necessarily
        # to the physical warehouse selected on a particular Odoo order.  When
        # the template declares the contractual origin province, prefer it.
        if self.origin_province:
            return self.origin_province
        warehouse = getattr(order, "warehouse_id", False)
        partner = warehouse.partner_id if warehouse and warehouse.partner_id else order.company_id.partner_id
        return self._postal_province(partner.zip) or ""

    def _explicit_zone(self, order, country_code, postal_code, origin_province, destination_province):
        self.ensure_one()
        rules = self.zone_ids.sorted(lambda rec: (rec.sequence, rec.id))
        for rule in rules:
            if rule.country_code and rule.country_code.upper() != country_code:
                continue
            if rule.rule_type == "POSTAL_PREFIX":
                prefix = str(rule.postal_prefix or "").strip()
                if prefix and str(postal_code or "").startswith(prefix):
                    return rule.zone_code
            elif rule.rule_type == "COUNTRY":
                return rule.zone_code
            elif rule.rule_type == "EXPLICIT_MATRIX":
                if (
                    (not rule.origin_province or _norm_text(rule.origin_province) == _norm_text(origin_province))
                    and (
                        not rule.destination_province
                        or _norm_text(rule.destination_province) == _norm_text(destination_province)
                    )
                ):
                    return rule.zone_code
        return ""

    def _resolve_zone(self, order):
        self.ensure_one()
        partner = order.partner_shipping_id or order.partner_id
        country_code = (partner.country_id.code or "").upper()
        postal_code = str(partner.zip or "").strip()
        destination_province = self._postal_province(postal_code)
        origin_province = self._origin_province_for_order(order)

        explicit = self._explicit_zone(
            order, country_code, postal_code, origin_province, destination_province
        )
        if explicit:
            return explicit

        if self.zone_mode == "AUTO_BORDERING_PROVINCES" and country_code == "ES":
            if not destination_province:
                return ""
            if _norm_text(origin_province) == _norm_text(destination_province):
                return "PROVINCIAL"
            border = self.book_id.border_ids.filtered(
                lambda rec: _norm_text(rec.origin_province) == _norm_text(origin_province)
                and _norm_text(rec.destination_province) == _norm_text(destination_province)
            )[:1]
            if border:
                return "REGIONAL"
            # At this point explicit island/Ceuta/Melilla rules have already had
            # priority. Remaining Spanish destinations are treated as mainland.
            return "RESTO_ES"

        return ""

    def _default_limit(self):
        self.ensure_one()
        return self.limit_ids.filtered("enforced_by_default")[:1]

    def _validate_package_limits(self, profile):
        self.ensure_one()
        limit = self._default_limit()
        if not limit:
            return {"success": True, "limit": False}

        weight = float(profile.get("weight_kg") or 0.0)
        dims_mm = [
            float(profile.get("length_mm") or 0.0),
            float(profile.get("width_mm") or 0.0),
            float(profile.get("height_mm") or 0.0),
        ]
        dims_cm = [value / 10.0 for value in dims_mm]
        if limit.max_weight_kg and weight > limit.max_weight_kg + 1e-9:
            return {
                "success": False,
                "message": _("GLS %(service)s admite como máximo %(weight)s kg para este tipo de bulto.")
                % {"service": self.name, "weight": limit.max_weight_kg},
                "limit": limit,
            }
        if limit.max_sum_sides_cm and sum(dims_cm) > limit.max_sum_sides_cm + 1e-9:
            return {
                "success": False,
                "message": _("GLS %(service)s admite como máximo %(size)s cm en la suma de los tres lados.")
                % {"service": self.name, "size": limit.max_sum_sides_cm},
                "limit": limit,
            }
        if limit.max_length_girth_cm:
            ordered = sorted(dims_cm, reverse=True)
            length_girth = ordered[0] + 2.0 * (ordered[1] + ordered[2])
            if length_girth > limit.max_length_girth_cm + 1e-9:
                return {
                    "success": False,
                    "message": _("GLS %(service)s admite como máximo %(size)s cm de longitud + perímetro.")
                    % {"service": self.name, "size": limit.max_length_girth_cm},
                    "limit": limit,
                }
        if limit.max_side_cm and max(dims_cm or [0.0]) > limit.max_side_cm + 1e-9:
            return {
                "success": False,
                "message": _("GLS %(service)s admite un lado máximo de %(size)s cm.")
                % {"service": self.name, "size": limit.max_side_cm},
                "limit": limit,
            }
        return {"success": True, "limit": limit}

    def _rate_for_weight(self, zone_code, chargeable_weight):
        self.ensure_one()
        rates = self.rate_ids.filtered(lambda rec: rec.zone_code == zone_code).sorted(
            lambda rec: (rec.weight_to_kg, rec.id)
        )
        if not rates:
            return False
        for rate in rates:
            if chargeable_weight <= rate.weight_to_kg + 1e-9:
                return {
                    "base_price": rate.price,
                    "rate": rate,
                    "additional_kg": 0.0,
                }
        last = rates[-1]
        if not last.additional_kg_price:
            return False
        extra = max(chargeable_weight - last.weight_to_kg, 0.0)
        if self.additional_kg_rounding == "CEIL":
            extra = float(math.ceil(max(extra - 1e-9, 0.0)))
        return {
            "base_price": last.price + (extra * last.additional_kg_price),
            "rate": last,
            "additional_kg": extra,
        }

    def _active_surcharges(self, on_date):
        self.ensure_one()
        return self.surcharge_ids.filtered(
            lambda rec: rec.active
            and self._period_overlaps_year(rec.valid_from, rec.valid_to, on_date)
        )

    def _method_limits_payload(self):
        self.ensure_one()
        limit = self._default_limit()
        if not limit:
            return {
                "provider": "gls",
                "min_weight_kg": 0.0,
                "max_weight_kg": 0.0,
                "max_length_mm": 0.0,
                "max_width_mm": 0.0,
                "max_height_mm": 0.0,
            }
        # The generic Optima snapshot has rectangular fields only. Preserve the
        # useful weight limit there; GLS-specific sum/girth constraints remain
        # enforced by this service before the price is returned.
        return {
            "provider": "gls",
            "min_weight_kg": 0.0,
            "max_weight_kg": limit.max_weight_kg or 0.0,
            "max_length_mm": (limit.max_side_cm or 0.0) * 10.0,
            "max_width_mm": (limit.max_side_cm or 0.0) * 10.0,
            "max_height_mm": (limit.max_side_cm or 0.0) * 10.0,
            "max_sum_sides_cm": limit.max_sum_sides_cm or 0.0,
            "max_length_girth_cm": limit.max_length_girth_cm or 0.0,
            "package_type": limit.package_type or "",
        }

    def rate_order(self, order):
        self.ensure_one()
        on_date = self._date_for_order(order)
        if (
            not self.active
            or not self.book_id.active
            or not self._period_overlaps_year(self.valid_from, self.valid_to, on_date)
        ):
            return {
                "success": False,
                "error_message": _("La tarifa GLS no pertenece al año tarifario vigente."),
            }

        profile = order._optima_pickup_package_profile()
        if not profile.get("success"):
            return {"success": False, "error_message": profile.get("message") or _("No se puede calcular el bulto GLS.")}

        limit_check = self._validate_package_limits(profile)
        if not limit_check.get("success"):
            return {"success": False, "error_message": limit_check.get("message")}

        zone_code = self._resolve_zone(order)
        if not zone_code or zone_code == "UNSUPPORTED":
            return {
                "success": False,
                "error_message": _("La plantilla GLS no tiene una zona tarifaria válida para este destino."),
            }

        weight_real = float(profile.get("weight_kg") or 0.0)
        volume_m3 = (
            float(profile.get("length_mm") or 0.0)
            * float(profile.get("width_mm") or 0.0)
            * float(profile.get("height_mm") or 0.0)
            / 1_000_000_000.0
        )
        weight_vol = volume_m3 * float(self.volumetric_factor_kg_m3 or 0.0)
        chargeable_weight = max(weight_real, weight_vol)

        rate = self._rate_for_weight(zone_code, chargeable_weight)
        if not rate:
            return {
                "success": False,
                "error_message": _("No hay tramo GLS para la zona %(zone)s y %(weight).3f kg facturables.")
                % {"zone": zone_code, "weight": chargeable_weight},
            }

        base_price = float(rate["base_price"] or 0.0)
        percent_total = 0.0
        fixed_total = 0.0
        for surcharge in self._active_surcharges(on_date):
            if surcharge.kind == "PERCENT":
                percent_total += float(surcharge.value or 0.0)
            elif surcharge.kind == "FIXED":
                fixed_total += float(surcharge.value or 0.0)
        total = base_price + (base_price * percent_total / 100.0) + fixed_total

        target_currency = order.currency_id
        if self.currency_id and target_currency and self.currency_id != target_currency:
            total = self.currency_id._convert(
                total,
                target_currency,
                order.company_id,
                on_date,
            )

        return {
            "success": True,
            "price": max(total, 0.0),
            "error_message": False,
            "warning_message": False,
            "zone_code": zone_code,
            "weight_real_kg": weight_real,
            "weight_volumetric_kg": weight_vol,
            "weight_chargeable_kg": chargeable_weight,
            "base_price": base_price,
            "surcharge_percent": percent_total,
            "surcharge_fixed": fixed_total,
            "tariff_book": self.book_id.code,
            "tariff_service": self.code,
            "method_limits": self._method_limits_payload(),
        }


class OptimaGlsTariffRate(models.Model):
    _name = "optima.gls.tariff.rate"
    _description = "Optima GLS Tariff Rate"
    _order = "zone_code, weight_to_kg"

    service_id = fields.Many2one("optima.gls.tariff.service", required=True, ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="service_id.currency_id", store=True, readonly=True)
    zone_code = fields.Char(required=True, index=True)
    weight_to_kg = fields.Float(required=True, digits=(16, 3))
    price = fields.Monetary(required=True, currency_field="currency_id")
    additional_kg_price = fields.Monetary(currency_field="currency_id")
    notes = fields.Char()


class OptimaGlsTariffSurcharge(models.Model):
    _name = "optima.gls.tariff.surcharge"
    _description = "Optima GLS Tariff Surcharge"
    _order = "code"

    service_id = fields.Many2one("optima.gls.tariff.service", required=True, ondelete="cascade", index=True)
    code = fields.Char(required=True)
    kind = fields.Selection([("PERCENT", "Percent"), ("FIXED", "Fixed")], required=True, default="PERCENT")
    value = fields.Float(required=True, digits=(16, 4))
    apply_mode = fields.Selection([("ADD_ON_BASE", "Add on base")], required=True, default="ADD_ON_BASE")
    valid_from = fields.Date()
    valid_to = fields.Date()
    active = fields.Boolean(default=True)
    notes = fields.Char()


class OptimaGlsTariffZone(models.Model):
    _name = "optima.gls.tariff.zone"
    _description = "Optima GLS Tariff Zone Rule"
    _order = "sequence, id"

    service_id = fields.Many2one("optima.gls.tariff.service", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=100)
    rule_type = fields.Selection(
        [
            ("POSTAL_PREFIX", "Postal prefix"),
            ("COUNTRY", "Country"),
            ("EXPLICIT_MATRIX", "Explicit matrix"),
        ],
        required=True,
    )
    country_code = fields.Char()
    postal_prefix = fields.Char()
    origin_province = fields.Char()
    destination_province = fields.Char()
    zone_code = fields.Char(required=True)
    notes = fields.Char()


class OptimaGlsTariffLimit(models.Model):
    _name = "optima.gls.tariff.limit"
    _description = "Optima GLS Tariff Limit"
    _order = "enforced_by_default desc, id"

    service_id = fields.Many2one("optima.gls.tariff.service", required=True, ondelete="cascade", index=True)
    package_type = fields.Char(required=True)
    max_weight_kg = fields.Float(digits=(16, 3))
    max_sum_sides_cm = fields.Float(digits=(16, 2))
    max_length_girth_cm = fields.Float(digits=(16, 2))
    max_side_cm = fields.Float(digits=(16, 2))
    enforced_by_default = fields.Boolean(default=False)
    notes = fields.Char()
