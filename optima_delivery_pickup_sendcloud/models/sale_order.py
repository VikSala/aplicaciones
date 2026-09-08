import json
import logging
import re
import unicodedata

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    optima_sendcloud_to_post_number = fields.Char(
        string="Sendcloud Post Number",
        copy=False,
    )

    def _optima_pickup_get_provider_carriers(self):
        """Add technical Sendcloud PUDO methods independently of website_sale."""
        self.ensure_one()
        grouped = super()._optima_pickup_get_provider_carriers()
        Carrier = self.env["delivery.carrier"]
        sendcloud_carriers = Carrier.sudo().search(
            [
                ("active", "=", True),
                ("delivery_type", "=", "sendcloud"),
                ("sendcloud_service_point_required", "=", True),
                *Carrier._check_company_domain(self.company_id),
            ]
        ).filtered(
            lambda carrier: carrier.sendcloud_integration_id
            and carrier.sendcloud_integration_id.active
            and carrier.sendcloud_integration_id.service_point_enabled
        )
        if sendcloud_carriers:
            grouped["sendcloud"] |= sendcloud_carriers
        return grouped

    def _optima_sendcloud_pickup_integration(self, carriers=None):
        self.ensure_one()
        Integration = self.env["sendcloud.integration"].sudo()

        default = self.company_id.sendcloud_default_integration_id
        if default and default.active and default.service_point_enabled and default.public_key:
            return default

        integrations = (carriers or self.env["delivery.carrier"]).mapped(
            "sendcloud_integration_id"
        ).filtered(
            lambda integration: integration.active
            and integration.service_point_enabled
            and integration.public_key
        )
        if integrations:
            return integrations[:1]

        domain = [
            ("active", "=", True),
            ("service_point_enabled", "=", True),
            ("public_key", "!=", False),
        ]
        if "company_id" in Integration._fields:
            domain.append(("company_id", "in", [False, self.company_id.id]))
        return Integration.search(domain, limit=1)

    def _optima_pickup_provider_descriptor(self, provider_code, carriers):
        descriptor = super()._optima_pickup_provider_descriptor(provider_code, carriers)
        if provider_code != "sendcloud":
            return descriptor

        self.ensure_one()
        partner = self.partner_shipping_id or self.partner_id
        integration = self._optima_sendcloud_pickup_integration(carriers)
        if not integration or not partner.country_id.code:
            return False

        lang = (partner.lang or self.env.lang or "en_US").replace("_", "-").lower()
        if lang not in {"en-us", "de-de", "en-gb", "es-es", "fr-fr", "it-it", "nl-nl"}:
            lang = "en-us"

        return {
            "code": "sendcloud",
            "name": "Sendcloud",
            "sequence": 10,
            "selector": "sendcloud_hosted",
            "config": {
                "api_key": integration.public_key,
                "integration_id": integration.id,
                "country": partner.country_id.code.lower(),
                "postal_code": partner.zip or "",
                "city": partner.city or "",
                "language": lang,
                "post_number": self.optima_sendcloud_to_post_number or "",
            },
        }

    def _optima_pickup_get_providers(self):
        self.ensure_one()
        providers = super()._optima_pickup_get_providers()
        if any(provider.get("code") == "sendcloud" for provider in providers):
            return providers

        descriptor = self._optima_pickup_provider_descriptor(
            "sendcloud", self.env["delivery.carrier"]
        )
        if descriptor:
            providers = [*providers, descriptor]
        return sorted(
            providers,
            key=lambda item: (item.get("sequence", 100), item.get("code", "")),
        )

    def _optima_pickup_prepare_point(self, provider_code, point, extra=None):
        if provider_code != "sendcloud":
            return super()._optima_pickup_prepare_point(provider_code, point, extra)

        self.ensure_one()
        extra = extra or {}
        if not isinstance(point, dict):
            raise ValidationError(_("El punto devuelto por Sendcloud no es válido."))
        required = ("id", "name", "postal_code", "city", "carrier")
        missing = [key for key in required if not point.get(key)]
        if missing:
            raise ValidationError(
                _("Faltan datos obligatorios del punto Sendcloud: %s", ", ".join(missing))
            )

        service_point_id = str(point["id"])
        if not service_point_id.isdigit():
            raise ValidationError(_("El identificador del punto Sendcloud no es válido."))

        partner = self.partner_shipping_id or self.partner_id
        expected_country = (partner.country_id.code or "").upper()
        raw_country = point.get("country") or point.get("country_code") or expected_country
        if isinstance(raw_country, dict):
            raw_country = raw_country.get("iso_2") or raw_country.get("code") or expected_country
        country_code = str(raw_country or expected_country).upper()
        if expected_country and country_code and expected_country != country_code:
            raise ValidationError(_("El punto Sendcloud pertenece a otro país."))

        carriers = self._optima_pickup_get_provider_carriers().get(
            "sendcloud", self.env["delivery.carrier"]
        )
        enabled_codes = set()
        for integration in carriers.mapped("sendcloud_integration_id"):
            enabled_codes.update(integration.service_point_carrier_ids.mapped("sendcloud_code"))
        point_carrier = str(point.get("carrier") or "")
        if enabled_codes and point_carrier not in enabled_codes:
            raise ValidationError(_("El transportista del punto no está habilitado en Sendcloud."))

        street = " ".join(
            str(value).strip()
            for value in (point.get("street"), point.get("house_number"))
            if value not in (None, "")
        )
        latitude = point.get("latitude") or point.get("lat") or 0.0
        longitude = point.get("longitude") or point.get("lng") or point.get("lon") or 0.0

        return {
            "id": service_point_id,
            "name": point["name"],
            "street": street or point["name"],
            "zip_code": str(point["postal_code"]),
            "city": point["city"],
            "country_code": country_code,
            "state": point.get("state") or "",
            "carrier_code": point_carrier,
            "carrier_name": point.get("carrier_name") or point_carrier,
            "latitude": float(latitude or 0.0),
            "longitude": float(longitude or 0.0),
        }

    @staticmethod
    def _optima_sendcloud_normalize_token(value):
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(char for char in value if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def _optima_sendcloud_related_tokens(self, record):
        """Collect stable identifiers from a Sendcloud-related record."""
        tokens = set()
        if not record:
            return tokens
        for field_name in (
            "sendcloud_code",
            "code",
            "slug",
            "carrier_code",
            "carrier",
            "name",
            "display_name",
        ):
            if field_name not in record._fields:
                continue
            try:
                value = record[field_name]
            except Exception:  # pragma: no cover - defensive against custom fields
                continue
            if getattr(value, "_name", None):
                for nested_name in ("sendcloud_code", "code", "name", "display_name"):
                    if nested_name in value._fields:
                        nested = value[nested_name]
                        if nested and not getattr(nested, "_name", None):
                            tokens.add(str(nested))
            elif value:
                tokens.add(str(value))
        return tokens

    def _optima_sendcloud_carrier_tokens(self, carrier):
        """Extract identifiers without hard-coding one OCA internal field name.

        delivery_sendcloud_oca has evolved across Odoo versions. We primarily
        use the carrier name and then inspect Sendcloud-related carrier/method
        fields so this adapter remains tolerant of those internal changes.
        """
        tokens = {carrier.display_name or carrier.name or ""}
        for field_name, field in carrier._fields.items():
            if not field_name.startswith("sendcloud_"):
                continue
            if "carrier" not in field_name and "shipping_method" not in field_name:
                continue
            try:
                value = carrier[field_name]
            except Exception:  # pragma: no cover
                continue
            if not value:
                continue
            if field.type in ("char", "selection", "text"):
                tokens.add(str(value))
            elif field.type == "many2one":
                tokens.update(self._optima_sendcloud_related_tokens(value))
        return {self._optima_sendcloud_normalize_token(token) for token in tokens if token}

    def _optima_sendcloud_carrier_match_score(self, carrier, point_carrier_code):
        point_token = self._optima_sendcloud_normalize_token(point_carrier_code)
        if not point_token:
            return 0
        score = 0
        for token in self._optima_sendcloud_carrier_tokens(carrier):
            if token == point_token:
                score = max(score, 100)
            elif point_token in token:
                score = max(score, 60)
        return score

    def _optima_pickup_resolve_delivery(self, provider_code, normalized, raw_point, extra):
        if provider_code != "sendcloud":
            return super()._optima_pickup_resolve_delivery(
                provider_code, normalized, raw_point, extra
            )

        self.ensure_one()
        carriers = self._optima_pickup_get_provider_carriers().get(
            "sendcloud", self.env["delivery.carrier"]
        )
        if not carriers:
            return {
                "success": False,
                "message": _("No se han encontrado métodos PUDO técnicos de Sendcloud."),
            }

        integration = self._optima_sendcloud_pickup_integration(carriers)
        if integration:
            carriers = carriers.filtered(
                lambda carrier: carrier.sendcloud_integration_id == integration
            )

        point_carrier_code = normalized.get("carrier_code") or ""
        scored = [
            (self._optima_sendcloud_carrier_match_score(carrier, point_carrier_code), carrier)
            for carrier in carriers
        ]
        best_score = max((score for score, _carrier in scored), default=0)
        matching = self.env["delivery.carrier"]
        if best_score:
            for score, carrier in scored:
                if score == best_score:
                    matching |= carrier

        if not matching:
            _logger.warning(
                "Optima pickup: no Sendcloud carrier matched service-point carrier %s. Candidates: %s",
                point_carrier_code,
                carriers.mapped("display_name"),
            )
            return {
                "success": False,
                "message": _(
                    "El punto se ha guardado, pero no encuentro un método Sendcloud PUDO del transportista %s.",
                    point_carrier_code or "?",
                ),
            }

        successful_rates = []
        errors = []
        for carrier in matching.sorted(lambda item: (item.sequence, item.id)):
            try:
                rate = carrier.rate_shipment(self)
            except Exception as exc:  # Keep checkout alive; diagnostic is logged server-side.
                _logger.exception(
                    "Optima pickup: error rating Sendcloud carrier %s", carrier.display_name
                )
                errors.append(str(exc))
                continue
            if not isinstance(rate, dict) or not rate.get("success"):
                error = (rate or {}).get("error_message") if isinstance(rate, dict) else ""
                if error:
                    errors.append(str(error))
                continue
            try:
                price = float(rate.get("price", 0.0))
            except (TypeError, ValueError):
                continue
            if price < 0:
                continue
            successful_rates.append(
                {
                    "carrier": carrier,
                    "price": price,
                    "warning": rate.get("warning_message") or "",
                }
            )

        if not successful_rates:
            diagnostic = errors[0] if errors else ""
            _logger.warning(
                "Optima pickup: no rate for Sendcloud point carrier %s. Matching methods: %s. Error: %s",
                point_carrier_code,
                matching.mapped("display_name"),
                diagnostic,
            )
            return {
                "success": False,
                "message": _(
                    "El punto se ha guardado, pero Sendcloud no ha devuelto una tarifa válida para el pedido."
                ),
            }

        # If several weight brackets/methods are valid, choose the lowest real
        # price returned by Odoo/Sendcloud. Restrictions by our own dimensions
        # will be introduced in a later phase as agreed.
        selected = min(
            successful_rates,
            key=lambda item: (item["price"], item["carrier"].sequence, item["carrier"].id),
        )
        message = selected["warning"] or ""
        if selected["price"] == 0.0:
            message = _(
                "Sendcloud ha devuelto 0,00 para este método. Comprueba el Price Check del método si esperabas una tarifa distinta."
            )

        _logger.info(
            "Optima pickup: resolved Sendcloud service point %s (%s) to %s at %.2f %s",
            normalized.get("id"),
            point_carrier_code,
            selected["carrier"].display_name,
            selected["price"],
            self.currency_id.name,
        )
        return {
            "success": True,
            "carrier": selected["carrier"],
            "price": selected["price"],
            "message": message,
        }

    def _optima_pickup_after_store_point(self, provider_code, normalized, raw_point, extra):
        super()._optima_pickup_after_store_point(provider_code, normalized, raw_point, extra)
        if provider_code != "sendcloud":
            return
        point_to_store = dict(raw_point)
        post_number = extra.get("post_number") or ""
        if post_number:
            point_to_store["post_number"] = str(post_number)
        self.write(
            {
                "sendcloud_service_point_address": json.dumps(point_to_store),
                "optima_sendcloud_to_post_number": str(post_number),
            }
        )

    def _optima_pickup_after_clear(self):
        super()._optima_pickup_after_clear()
        self.write(
            {
                "sendcloud_service_point_address": False,
                "optima_sendcloud_to_post_number": False,
            }
        )
