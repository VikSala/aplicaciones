import json
import logging
import re
import unicodedata
import time
from math import ceil

import requests

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    optima_sendcloud_to_post_number = fields.Char(
        string="Sendcloud Post Number",
        copy=False,
    )
    optima_sendcloud_resolution_cache = fields.Json(
        string="Caché temporal de resolución Sendcloud",
        copy=False,
        default=dict,
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

    def _optima_sendcloud_cache_get(self, bucket, key, ttl=1800):
        """Return a short-lived per-order Sendcloud cache entry.

        Shipping method ids are volatile, so cached API-derived identities are
        intentionally kept for at most 30 minutes. A prewarm request may collect
        cache writes in memory until all remote I/O has finished; consult that
        collector first so the same request can immediately reuse its own work.
        """
        self.ensure_one()
        collector = self.env.context.get("optima_sendcloud_cache_collector")
        if isinstance(collector, dict):
            bucket_values = collector.get(bucket) or {}
            if key in bucket_values:
                return bucket_values[key]

        cache = self.optima_sendcloud_resolution_cache or {}
        data = cache.get(bucket) if isinstance(cache, dict) else {}
        entry = data.get(key) if isinstance(data, dict) else None
        if not isinstance(entry, dict):
            return False
        try:
            age = time.time() - float(entry.get("ts") or 0.0)
        except (TypeError, ValueError):
            return False
        if age < 0 or age > ttl:
            return False
        return entry.get("value")

    def _optima_sendcloud_cache_merge(self, entries):
        """Merge one or more cache entries with a very short row lock.

        Prewarming can overlap a real ``set_point`` request. Remote Sendcloud I/O
        therefore happens before this method; only the final JSON merge is locked.
        Refreshing the field after ``FOR UPDATE`` prevents two concurrent warm-ups
        from overwriting each other's freshly-created cache buckets.
        """
        self.ensure_one()
        if not isinstance(entries, dict) or not any(entries.values()):
            return

        self.env.cr.execute(
            "SELECT id FROM %s WHERE id = %%s FOR UPDATE" % self._table,
            [self.id],
        )
        self.invalidate_recordset(["optima_sendcloud_resolution_cache"])
        cache = dict(self.optima_sendcloud_resolution_cache or {})
        now = time.time()
        for bucket, values in entries.items():
            if not isinstance(values, dict) or not values:
                continue
            data = dict(cache.get(bucket) or {})
            fresh = {}
            for existing_key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                try:
                    if 0 <= now - float(entry.get("ts") or 0.0) <= 3600:
                        fresh[existing_key] = entry
                except (TypeError, ValueError):
                    continue
            for key, value in values.items():
                fresh[key] = {"ts": now, "value": value}
            if len(fresh) > 24:
                fresh = dict(
                    sorted(
                        fresh.items(),
                        key=lambda item: float(item[1].get("ts") or 0.0),
                        reverse=True,
                    )[:24]
                )
            cache[bucket] = fresh
        self.write({"optima_sendcloud_resolution_cache": cache})

    def _optima_sendcloud_cache_put(self, bucket, key, value):
        self.ensure_one()
        collector = self.env.context.get("optima_sendcloud_cache_collector")
        if isinstance(collector, dict):
            collector.setdefault(bucket, {})[key] = value
            return
        self._optima_sendcloud_cache_merge({bucket: {key: value}})

    def _optima_sendcloud_products_cache_key(self, integration, point, package):
        """Cache key for Shipping Products, intentionally independent of carrier.

        Sendcloud filters this request by route, parcel and service-point last mile;
        the selected Correos/InPost/etc. carrier is not one of its request inputs.
        Keeping this cache carrier-neutral lets the first point of a second carrier
        reuse the same expensive package compatibility query.
        """
        self.ensure_one()
        return "|".join([
            str(integration.id or 0),
            str(point.get("country_code") or "").strip().upper(),
            str(point.get("zip_code") or "").strip().upper(),
            self._optima_pickup_address_fingerprint(),
            self._optima_pickup_logistics_fingerprint(package),
        ])

    def _optima_sendcloud_validation_cache_key(self, integration, point, package):
        self.ensure_one()
        carrier = self._optima_sendcloud_canonical_carrier(point.get("carrier_code") or "")
        return "|".join([
            str(integration.id or 0),
            carrier,
            str(point.get("zip_code") or "").strip().upper(),
            self._optima_pickup_address_fingerprint(),
            self._optima_pickup_logistics_fingerprint(package),
        ])

    @staticmethod
    def _optima_sendcloud_canonical_carrier(value):
        token = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
        # Normalize both raw API codes and longer synchronized Odoo labels.
        # InPost ES historically appears under both InPost and Mondial Relay
        # identifiers depending on the Sendcloud dataset/version.
        if "mondialrelay" in token or "inpost" in token:
            return "inpost_es"
        if "correosexpress" in token:
            return "correos_express"
        if token == "correos" or token.endswith("correos"):
            return "correos"
        return token

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

        package = self._optima_pickup_package_profile()
        package_weight = float(package.get("weight_kg") or 0.0) if package.get("success") else 0.0

        return {
            "code": "sendcloud",
            "name": "Sendcloud",
            "sequence": 10,
            "selector": "unified_map",
            "config": {
                "api_key": integration.public_key,
                "integration_id": integration.id,
                "country": partner.country_id.code.lower(),
                "postal_code": partner.zip or "",
                "city": partner.city or "",
                "language": lang,
                "post_number": self.optima_sendcloud_to_post_number or "",
                "weight_kg": package_weight,
                "default_query": (partner.zip or self._optima_pickup_default_search_query() or "").strip(),
                # Frontend map cache is valid only while both destination and
                # parcel profile remain unchanged. No personal data are exposed
                # in this token; both values are SHA-256 fingerprints.
                "cache_token": "%s:%s" % (
                    self._optima_pickup_address_fingerprint(),
                    self._optima_pickup_logistics_fingerprint(),
                ),
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

    def _optima_sendcloud_servicepoints_api_get(self, integration, params=None):
        """Fetch public service-point data without exposing Sendcloud secrets."""
        self.ensure_one()
        public_key = str(getattr(integration, "public_key", "") or "")
        secret_key = self._optima_sendcloud_secret_key(integration)
        if not public_key or not secret_key:
            return {
                "success": False,
                "message": _(
                    "La integración Sendcloud no tiene disponibles las credenciales necesarias para buscar puntos."
                ),
            }
        try:
            response = requests.get(
                "https://servicepoints.sendcloud.sc/api/v2/service-points",
                params=params or {},
                auth=(public_key, secret_key),
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=(3, 6),
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            _logger.warning("Optima pickup: Sendcloud service point search failed: %s", exc)
            return {
                "success": False,
                "message": _(
                    "No se han podido buscar puntos Sendcloud en este momento. Inténtalo de nuevo."
                ),
            }
        except ValueError:
            return {
                "success": False,
                "message": _("Sendcloud ha devuelto una respuesta no válida al buscar puntos."),
            }
        return {"success": True, "points": payload if isinstance(payload, list) else []}

    def _optima_sendcloud_method_lead_time_hours(self, api_method, destination_country):
        """Extract the route-specific lead time from a Shipping Products method."""
        self.ensure_one()
        lead = (api_method or {}).get("lead_time_hours")
        if isinstance(lead, (int, float)):
            return max(int(lead), 0)
        if not isinstance(lead, dict):
            return 0
        origin = self._optima_sendcloud_origin_data().get("country_code") or ""
        destination = (destination_country or "").upper()
        origin_value = lead.get(origin) or lead.get(origin.lower())
        if isinstance(origin_value, (int, float)):
            return max(int(origin_value), 0)
        if isinstance(origin_value, dict):
            value = origin_value.get(destination) or origin_value.get(destination.lower())
            if isinstance(value, (int, float)):
                return max(int(value), 0)
        # Be tolerant if an API variant returns a single nested numeric value.
        values = []
        for value in lead.values():
            if isinstance(value, (int, float)):
                values.append(int(value))
            elif isinstance(value, dict):
                values.extend(int(v) for v in value.values() if isinstance(v, (int, float)))
        return max(min(values), 0) if values else 0

    def _optima_sendcloud_map_quote(self, carriers, point_carrier_code, package):
        """Return an immediate, lightweight *display* quote for map browsing.

        Phase 5 must keep point discovery fast and resilient.  The map therefore
        uses only already-synchronised Odoo route prices and weight brackets; it
        deliberately does *not* call Shipping Products before rendering markers.
        Exact weight + dimensions + service-point compatibility are still checked
        by the proven authoritative resolver after the customer chooses a point.
        """
        self.ensure_one()
        package_weight = float(package.get("weight_kg") or 0.0)
        scored = [
            (self._optima_sendcloud_carrier_match_score(carrier, point_carrier_code), carrier)
            for carrier in carriers
        ]
        best_point_score = max((score for score, _carrier in scored), default=0)
        point_carriers = self.env["delivery.carrier"]
        if best_point_score:
            for score, carrier in scored:
                if score == best_point_score:
                    point_carriers |= carrier
        if not point_carriers:
            return {"compatible": False}

        candidates = []
        for carrier in point_carriers:
            if not self._optima_sendcloud_weight_matches(carrier, package_weight):
                continue
            route_found, route_price, _route = self._optima_sendcloud_route_price(carrier)
            candidates.append(
                {
                    "carrier": carrier,
                    "price": route_price if route_found else None,
                }
            )
        if not candidates:
            return {"compatible": False}

        priced = [item for item in candidates if item["price"] is not None]
        selected = min(
            priced or candidates,
            key=lambda item: (
                item["price"] if item["price"] is not None else 10**9,
                item["carrier"].sequence,
                item["carrier"].id,
            ),
        )
        return {
            "compatible": True,
            "price": selected.get("price"),
            "currency": self.currency_id.name or "EUR",
            "method_name": selected["carrier"].display_name,
            "carrier_name": self._optima_sendcloud_display_carrier_name(
                point_carrier_code, selected["carrier"]
            ),
            # Lead time is intentionally not allowed to delay map discovery.
            # A future provider can supply it without changing the core UI.
            "lead_time_hours": 0,
            "estimated": True,
        }

    @staticmethod
    def _optima_sendcloud_display_carrier_name(code, carrier=False):
        """Derive a compact customer-facing carrier label."""
        value = str(code or "").strip()
        aliases = {
            "inpost_es": "InPost",
            "inpost": "InPost",
            "inpost_iberia": "InPost",
            "mondial_relay": "InPost",
            "mondialrelay": "InPost",
            "correos": "Correos",
            "correos_express": "Correos Express",
            "correosexpress": "Correos Express",
            "ups": "UPS",
            "gls": "GLS",
            "fedex": "FedEx",
            "dhl": "DHL",
            "dpd": "DPD",
        }
        token = value.lower().replace("-", "_").replace(" ", "_")
        if token in aliases:
            return aliases[token]
        if value:
            return value.replace("_", " ").title()
        return carrier.display_name if carrier else "Sendcloud"

    @staticmethod
    def _optima_sendcloud_marker_metadata(carrier_code):
        token = str(carrier_code or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "inpost_es": "inpost",
            "inpost": "inpost",
            "inpost_iberia": "inpost",
            "mondial_relay": "inpost",
            "mondialrelay": "inpost",
            "correos": "correos",
            "correos_express": "correos_express",
            "correosexpress": "correos_express",
            "ups": "ups",
            "gls": "gls",
            "fedex": "fedex",
            "dhl": "dhl",
            "dpd": "dpd",
        }
        key = aliases.get(token, "default")
        return {
            "marker_icon": "/optima_delivery_pickup_sendcloud/static/src/img/carriers/%s.svg" % key,
            "marker_theme": key,
        }

    def _optima_pickup_search_points(self, provider_codes=None, query=None, radius_m=5000):
        result = super()._optima_pickup_search_points(
            provider_codes=provider_codes, query=query, radius_m=radius_m
        )
        result = dict(result or {})
        result.setdefault("points", [])
        result.setdefault("errors", [])
        if provider_codes and "sendcloud" not in provider_codes:
            return result

        self.ensure_one()
        package = self._optima_pickup_package_profile()
        if not package.get("success"):
            result["errors"].append(
                {"provider_code": "sendcloud", "message": package.get("message") or _("Datos logísticos incompletos.")}
            )
            return result

        carriers = self._optima_pickup_get_provider_carriers().get(
            "sendcloud", self.env["delivery.carrier"]
        )
        integration = self._optima_sendcloud_pickup_integration(carriers)
        if not integration:
            result["errors"].append(
                {"provider_code": "sendcloud", "message": _("No hay una integración Sendcloud activa para buscar puntos.")}
            )
            return result
        carriers = carriers.filtered(lambda carrier: carrier.sendcloud_integration_id == integration)

        partner = self.partner_shipping_id or self.partner_id
        destination_country = (partner.country_id.code or "").upper()
        if not destination_country:
            result["errors"].append(
                {"provider_code": "sendcloud", "message": _("Falta el país de entrega para buscar puntos Sendcloud.")}
            )
            return result

        # Fast-path discovery: one remote request only.  The Service Points API
        # already filters by destination/address/radius/weight.  We avoid the
        # previous Shipping Products call here because it doubled checkout wait
        # time and could make /search_points hit reverse-proxy timeouts. Exact
        # dimensional compatibility remains fail-closed in set_point.
        params = {
            "country": destination_country,
            "address": (query or partner.zip or self._optima_pickup_default_search_query()).strip(),
            "radius": min(max(int(radius_m or 5000), 500), 50000),
            "weight": max(float(package.get("weight_kg") or 0.0), 0.001),
        }
        search_result = self._optima_sendcloud_servicepoints_api_get(integration, params=params)
        if not search_result.get("success"):
            result["errors"].append(
                {"provider_code": "sendcloud", "message": search_result.get("message") or _("No se han podido buscar puntos Sendcloud.")}
            )
            return result

        public_points = []
        quote_cache = {}
        for raw in search_result.get("points") or []:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            if raw.get("open_upcoming_week") is False:
                continue
            carrier_code = str(raw.get("carrier") or "")
            if carrier_code not in quote_cache:
                quote_cache[carrier_code] = self._optima_sendcloud_map_quote(
                    carriers, carrier_code, package
                )
            quote = quote_cache[carrier_code]
            # Discovery must represent every service point returned by Sendcloud.
            # A missing local display quote is not proof that the point is unusable;
            # exact package/method validation happens only after customer selection.
            try:
                latitude = float(raw.get("latitude") or 0.0)
                longitude = float(raw.get("longitude") or 0.0)
            except (TypeError, ValueError):
                continue
            if not latitude or not longitude:
                continue
            try:
                distance_m = max(float(raw.get("distance") or 0.0), 0.0)
            except (TypeError, ValueError):
                distance_m = 0.0

            marker_meta = self._optima_sendcloud_marker_metadata(carrier_code)
            raw_point = {
                "id": raw.get("id"),
                "name": raw.get("name") or "",
                "street": raw.get("street") or "",
                "house_number": raw.get("house_number") or "",
                "postal_code": raw.get("postal_code") or "",
                "city": raw.get("city") or "",
                "country": raw.get("country") or destination_country,
                "carrier": carrier_code,
                "carrier_name": quote.get("carrier_name") or self._optima_sendcloud_display_carrier_name(carrier_code),
                "latitude": latitude,
                "longitude": longitude,
                "general_shop_type": raw.get("general_shop_type") or "",
                "formatted_opening_times": raw.get("formatted_opening_times") or {},
                "open_tomorrow": bool(raw.get("open_tomorrow")),
                "open_upcoming_week": raw.get("open_upcoming_week") is not False,
            }
            public_points.append(
                {
                    "key": "sendcloud:%s" % raw.get("id"),
                    "provider_code": "sendcloud",
                    "provider_name": "Sendcloud",
                    "id": str(raw.get("id")),
                    "name": raw.get("name") or "",
                    "street": " ".join(
                        str(value).strip()
                        for value in (raw.get("street"), raw.get("house_number"))
                        if value not in (None, "")
                    ),
                    "zip_code": str(raw.get("postal_code") or ""),
                    "city": raw.get("city") or "",
                    "country_code": raw.get("country") or destination_country,
                    "carrier_code": carrier_code,
                    "carrier_name": quote.get("carrier_name") or self._optima_sendcloud_display_carrier_name(carrier_code),
                    "latitude": latitude,
                    "longitude": longitude,
                    "distance_m": distance_m,
                    "shop_type": raw.get("general_shop_type") or raw.get("shop_type") or "",
                    "opening_times": raw.get("formatted_opening_times") or {},
                    "open_tomorrow": bool(raw.get("open_tomorrow")),
                    "quote": {
                        "price": quote.get("price"),
                        "currency": quote.get("currency") or self.currency_id.name or "EUR",
                        "method_name": quote.get("method_name") or "",
                        "lead_time_hours": quote.get("lead_time_hours") or 0,
                        "estimated": True,
                    },
                    **marker_meta,
                    "raw_point": raw_point,
                    "extra": {},
                }
            )

        public_points.sort(
            key=lambda point: (
                point.get("distance_m") or 10**12,
                point.get("quote", {}).get("price")
                if point.get("quote", {}).get("price") is not None
                else 10**12,
                point.get("name") or "",
            )
        )
        result["points"].extend(public_points[:100])
        return result

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
                _("Faltan datos obligatorios del punto Sendcloud: %s") % ", ".join(missing)
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
        point_family = self._optima_sendcloud_canonical_carrier(point_carrier_code)
        if not point_token:
            return 0
        score = 0
        for token in self._optima_sendcloud_carrier_tokens(carrier):
            token_family = self._optima_sendcloud_canonical_carrier(token)
            if point_family and token_family == point_family:
                score = max(score, 110)
            elif token == point_token:
                score = max(score, 100)
            elif point_token in token or token in point_token:
                score = max(score, 60)
        return score

    def _optima_sendcloud_order_weight(self):
        """Return the estimated order weight in kg for Sendcloud bracket matching."""
        self.ensure_one()
        getter = getattr(self, "_get_estimated_weight", None)
        if getter:
            try:
                return max(float(getter() or 0.0), 0.0)
            except (TypeError, ValueError):
                pass
        weight = 0.0
        for line in self.order_line.filtered(lambda line: not line.is_delivery):
            if not line.product_id:
                continue
            weight += (line.product_id.weight or 0.0) * line.product_uom_qty
        return max(float(weight), 0.0)

    @staticmethod
    def _optima_sendcloud_numeric_field(record, exact_names, contains=()):
        for name in exact_names:
            if name in record._fields:
                try:
                    value = record[name]
                    if value is not False and value is not None:
                        return float(value)
                except (TypeError, ValueError, Exception):
                    continue
        for name, field in record._fields.items():
            lname = name.lower()
            if field.type not in ("float", "integer", "monetary"):
                continue
            if all(token in lname for token in contains):
                try:
                    value = record[name]
                    if value is not False and value is not None:
                        return float(value)
                except (TypeError, ValueError, Exception):
                    continue
        return None

    def _optima_sendcloud_weight_matches(self, carrier, weight):
        """Match Sendcloud's own min/max method bracket before rating.

        This prevents all 0-1 / 1-2 / 2-5 kg variants of one carrier from
        being treated as equivalent just because they share the same carrier
        code (for example ``inpost_es``).
        """
        minimum = self._optima_sendcloud_numeric_field(
            carrier,
            ("sendcloud_min_weight", "min_weight"),
            ("min", "weight"),
        )
        maximum = self._optima_sendcloud_numeric_field(
            carrier,
            ("sendcloud_max_weight", "max_weight"),
            ("max", "weight"),
        )
        if minimum is not None and weight < minimum:
            return False
        if maximum not in (None, 0.0) and weight > maximum:
            return False
        return True

    @staticmethod
    def _optima_sendcloud_secret_key(integration):
        """Read the API secret without exposing it outside the server.

        OCA series have used the conventional ``secret_key`` name.  The small
        fallback keeps this adapter tolerant of compatible forks while never
        logging or returning the credential.
        """
        if not integration:
            return ""
        for name in ("secret_key", "api_secret", "secret"):
            if name not in integration._fields:
                continue
            try:
                value = integration[name]
            except Exception:  # pragma: no cover - defensive for custom fields
                continue
            if value and not getattr(value, "_name", None):
                return str(value)
        for name, field in integration._fields.items():
            if "secret" not in name.lower() or field.type not in ("char", "text"):
                continue
            try:
                value = integration[name]
            except Exception:  # pragma: no cover
                continue
            if value:
                return str(value)
        return ""

    def _optima_sendcloud_api_get(self, integration, endpoint, params=None):
        """Perform one authenticated Sendcloud v2 GET request.

        Validation is deliberately fail-closed: a timeout or API error never
        turns into an apparently valid pickup shipment.
        """
        self.ensure_one()
        public_key = str(getattr(integration, "public_key", "") or "")
        secret_key = self._optima_sendcloud_secret_key(integration)
        if not public_key or not secret_key:
            return {
                "success": False,
                "message": _(
                    "La integración Sendcloud no tiene disponibles la clave pública y secreta necesarias para validar el bulto."
                ),
            }

        url = "https://panel.sendcloud.sc/api/v2/%s" % endpoint.lstrip("/")
        try:
            response = requests.get(
                url,
                params=params or {},
                auth=(public_key, secret_key),
                # Keep checkout requests below common reverse-proxy/worker
                # timeouts. Phase 1 performs a single Shipping Products call;
                # if Sendcloud is slow we fail closed with a controlled message.
                timeout=(3, 6),
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            _logger.warning(
                "Optima pickup: Sendcloud API request failed for %s: %s",
                endpoint,
                exc,
            )
            return {
                "success": False,
                "message": _(
                    "No se ha podido validar el bulto con Sendcloud en este momento. Inténtalo de nuevo."
                ),
            }
        except ValueError:
            _logger.warning(
                "Optima pickup: Sendcloud API returned invalid JSON for %s", endpoint
            )
            return {
                "success": False,
                "message": _(
                    "Sendcloud ha devuelto una respuesta no válida al comprobar el bulto."
                ),
            }
        return {"success": True, "payload": payload}

    def _optima_sendcloud_origin_data(self):
        self.ensure_one()
        warehouse_partner = (
            self.warehouse_id.partner_id if self.warehouse_id else self.company_id.partner_id
        )
        country = (
            warehouse_partner.country_id.code
            or self.company_id.country_id.code
            or ""
        ).upper()
        return {
            "country_code": country,
            "postal_code": (warehouse_partner.zip or "").strip(),
        }

    @staticmethod
    def _optima_sendcloud_package_label(package):
        return _("%.3f kg · %.0f × %.0f × %.0f mm") % (
            package.get("weight_kg", 0.0),
            package.get("length_mm", 0.0),
            package.get("width_mm", 0.0),
            package.get("height_mm", 0.0),
        )

    def _optima_sendcloud_shipping_product_methods(self, integration, point, package):
        """Return methods that Sendcloud accepts for weight + dimensions.

        The Shipping Products endpoint itself performs the dimensional check.
        We ask only for service-point last-mile products and later intersect
        these ids with the methods supported by the exact chosen point.
        """
        self.ensure_one()
        origin = self._optima_sendcloud_origin_data()
        destination_country = (point.get("country_code") or "").upper()
        if not origin["country_code"] or not destination_country:
            return {
                "success": False,
                "message": _(
                    "No se puede validar Sendcloud porque falta el país de origen o destino."
                ),
            }

        cache_key = self._optima_sendcloud_products_cache_key(
            integration, point, package
        )
        cached = self._optima_sendcloud_cache_get("products", cache_key)
        if isinstance(cached, dict) and "methods" in cached:
            methods = {}
            for method in cached.get("methods") or []:
                if not isinstance(method, dict):
                    continue
                try:
                    method_id = int(method.get("id") or 0)
                except (TypeError, ValueError):
                    method_id = 0
                if method_id:
                    methods[method_id] = dict(method)
            _logger.info(
                "Optima pickup: reusing carrier-neutral Shipping Products cache for zip=%s",
                point.get("zip_code") or "",
            )
            return {"success": True, "methods": methods}

        params = {
            "from_country": origin["country_code"],
            "to_country": destination_country,
            "weight": max(int(ceil(float(package["weight_kg"]) * 1000.0)), 1),
            "weight_unit": "gram",
            "length": max(int(ceil(float(package["length_mm"]))), 1),
            "length_unit": "millimeter",
            "width": max(int(ceil(float(package["width_mm"]))), 1),
            "width_unit": "millimeter",
            "height": max(int(ceil(float(package["height_mm"]))), 1),
            "height_unit": "millimeter",
            "last_mile": "service_point",
        }
        if origin["postal_code"]:
            params["from_postal_code"] = origin["postal_code"][:12]
        if point.get("zip_code"):
            params["to_postal_code"] = str(point["zip_code"])[:12]

        result = self._optima_sendcloud_api_get(
            integration, "shipping-products", params=params
        )
        if not result.get("success"):
            return result
        payload = result.get("payload")
        products = payload if isinstance(payload, list) else []
        methods = {}
        for product in products:
            if not isinstance(product, dict):
                continue
            for method in product.get("methods") or []:
                if not isinstance(method, dict) or method.get("id") in (None, False):
                    continue
                try:
                    method_id = int(method["id"])
                except (TypeError, ValueError):
                    continue
                methods[method_id] = method
        self._optima_sendcloud_cache_put(
            "products",
            cache_key,
            {"methods": [dict(method) for method in methods.values()]},
        )
        return {"success": True, "methods": methods}

    def _optima_sendcloud_point_methods(self, integration, point):
        """Return methods Sendcloud says can deliver to this exact point.

        Sendcloud's ``shipping_methods`` endpoint can require the route data for
        zonal carriers.  In Spain this matters for providers such as Correos /
        Correos Express and some locker networks: querying only by
        ``service_point_id`` can legitimately return an empty set even though
        the point itself is valid.  Always send the same origin/destination
        context used by the shipping-products validation.
        """
        self.ensure_one()
        try:
            service_point_id = int(point.get("id") or 0)
        except (TypeError, ValueError):
            service_point_id = 0
        if not service_point_id:
            return {
                "success": False,
                "message": _("El punto Sendcloud no tiene un identificador válido."),
            }

        origin = self._optima_sendcloud_origin_data()
        destination_country = str(point.get("country_code") or "").upper()
        params = {"service_point_id": service_point_id}
        if origin.get("postal_code"):
            params["from_postal_code"] = str(origin["postal_code"])[:12]
        if point.get("zip_code"):
            params["to_postal_code"] = str(point["zip_code"])[:12]
        if destination_country:
            params["to_country"] = destination_country

        def parse_methods(payload):
            if isinstance(payload, dict):
                rows = payload.get("shipping_methods") or payload.get("methods") or []
            elif isinstance(payload, list):
                # Be tolerant of compatible Sendcloud proxies / older responses.
                rows = payload
            else:
                rows = []
            parsed = {}
            for method in rows:
                if not isinstance(method, dict) or method.get("id") in (None, False):
                    continue
                try:
                    method_id = int(method["id"])
                except (TypeError, ValueError):
                    continue
                parsed[method_id] = method
            return parsed

        result = self._optima_sendcloud_api_get(
            integration,
            "shipping_methods",
            params=params,
        )
        if not result.get("success"):
            return result
        methods = parse_methods(result.get("payload"))

        if not methods:
            # Sendcloud documents sender_address as required for zonal carriers.
            # We cannot safely assume an Odoo database field contains the
            # remote sender id across all OCA versions, so retry with the
            # documented special value ``all``.  Safety is preserved because
            # these exact-point methods are later intersected with the
            # Shipping Products result already filtered by the real warehouse
            # country/postcode and by the estimated package.
            all_sender_params = dict(params, sender_address="all")
            retry = self._optima_sendcloud_api_get(
                integration,
                "shipping_methods",
                params=all_sender_params,
            )
            if retry.get("success"):
                methods = parse_methods(retry.get("payload"))
                if methods:
                    _logger.info(
                        "Optima pickup: service point %s required sender_address=all "
                        "to expose zonal Sendcloud methods",
                        service_point_id,
                    )
        return {"success": True, "methods": methods}

    def _optima_sendcloud_compatible_remote_methods(self, product_methods, point_methods):
        """Join package-compatible and point-compatible Sendcloud methods.

        Method ids are the preferred identity.  Sendcloud documents those ids
        as volatile, however, so a strict id intersection is unnecessarily
        brittle when two endpoints are refreshed at slightly different times.
        If there is no id match, accept only an unambiguous normalized-name
        match.  The dimensional properties always come from Shipping Products;
        the exact-point method supplies the current point-compatible identity.
        """
        self.ensure_one()
        product_methods = product_methods or {}
        point_methods = point_methods or {}
        compatible = []
        seen = set()

        for method_id in sorted(set(product_methods) & set(point_methods)):
            merged = dict(point_methods.get(method_id) or {})
            merged.update(product_methods.get(method_id) or {})
            merged["id"] = method_id
            merged["_optima_match"] = "id"
            compatible.append(merged)
            seen.add(method_id)

        if compatible:
            return compatible

        # No direct id intersection.  Retry by exact normalized method name.
        # We intentionally do not use fuzzy carrier-only matching here: a name
        # must identify one package-compatible and one exact-point-compatible
        # method, otherwise validation stays fail-closed.
        product_by_name = {}
        for method in product_methods.values():
            name = self._optima_sendcloud_normalize_token(method.get("name") or "")
            if name:
                product_by_name.setdefault(name, []).append(method)
        point_by_name = {}
        for method in point_methods.values():
            name = self._optima_sendcloud_normalize_token(method.get("name") or "")
            if name:
                point_by_name.setdefault(name, []).append(method)

        for name in sorted(set(product_by_name) & set(point_by_name)):
            products = product_by_name[name]
            points = point_by_name[name]
            if len(products) != 1 or len(points) != 1:
                continue
            product_method = products[0]
            point_method = points[0]
            try:
                point_id = int(point_method.get("id") or 0)
            except (TypeError, ValueError):
                point_id = 0
            merged = dict(point_method)
            merged.update(product_method)
            if point_id:
                # Use the id returned by the exact-point endpoint as the most
                # current identity, while keeping Shipping Products properties.
                merged["id"] = point_id
            merged["_optima_match"] = "name"
            compatible.append(merged)
        return compatible

    def _optima_sendcloud_external_method_ids(self, carrier):
        """Best-effort discovery of Sendcloud's remote shipping-method id."""
        ids = set()

        def add_value(value):
            if value in (None, False, "") or getattr(value, "_name", None):
                return
            try:
                number = int(value)
            except (TypeError, ValueError):
                return
            if number > 0:
                ids.add(number)

        scalar_names = {
            "sendcloud_method_id",
            "sendcloud_shipping_method_id",
            "sendcloud_shipping_method_code",
            "shipping_method_external_id",
        }
        scalar_names.update(
            name
            for name, field in carrier._fields.items()
            if field.type not in ("many2one", "one2many", "many2many")
            and "id" in name.lower()
            and (
                (name.startswith("sendcloud_") and ("method" in name or "shipping" in name))
                or ("external" in name and "method" in name)
            )
        )
        for name in scalar_names:
            if name in carrier._fields and carrier._fields[name].type not in (
                "many2one",
                "one2many",
                "many2many",
            ):
                try:
                    add_value(carrier[name])
                except Exception:  # pragma: no cover
                    pass

        for name, field in carrier._fields.items():
            if field.type != "many2one" or not name.startswith("sendcloud_"):
                continue
            if "method" not in name and "shipping" not in name:
                continue
            if "integration" in name or "carrier" in name:
                continue
            try:
                related = carrier[name]
            except Exception:  # pragma: no cover
                continue
            if not related:
                continue
            for related_name in (
                "sendcloud_id",
                "external_id",
                "shipping_method_id",
                "method_id",
                "remote_id",
            ):
                if related_name not in related._fields:
                    continue
                related_field = related._fields[related_name]
                if related_field.type in ("many2one", "one2many", "many2many"):
                    continue
                try:
                    add_value(related[related_name])
                except Exception:  # pragma: no cover
                    pass
        return ids

    def _optima_sendcloud_local_method_names(self, carrier):
        names = {carrier.name or "", carrier.display_name or ""}
        for field_name, field in carrier._fields.items():
            if field.type != "many2one" or not field_name.startswith("sendcloud_"):
                continue
            if "method" not in field_name and "shipping" not in field_name:
                continue
            if "integration" in field_name or "carrier" in field_name:
                continue
            try:
                related = carrier[field_name]
            except Exception:  # pragma: no cover
                continue
            if not related:
                continue
            for name_field in ("name", "display_name"):
                if name_field in related._fields:
                    try:
                        value = related[name_field]
                    except Exception:  # pragma: no cover
                        continue
                    if value and not getattr(value, "_name", None):
                        names.add(str(value))
        normalized = set()
        for value in names:
            token = self._optima_sendcloud_normalize_token(value)
            if not token:
                continue
            normalized.add(token)
            if token.startswith("sendcloud"):
                normalized.add(token[len("sendcloud") :])
        return {name for name in normalized if name}

    def _optima_sendcloud_api_method_match_score(self, carrier, api_method):
        try:
            api_id = int(api_method.get("id") or 0)
        except (TypeError, ValueError):
            api_id = 0
        if api_id and api_id in self._optima_sendcloud_external_method_ids(carrier):
            return 1000

        api_name = self._optima_sendcloud_normalize_token(api_method.get("name") or "")
        if not api_name:
            return 0
        best = 0
        for local_name in self._optima_sendcloud_local_method_names(carrier):
            if local_name == api_name:
                best = max(best, 900)
            elif min(len(local_name), len(api_name)) >= 12 and (
                local_name in api_name or api_name in local_name
            ):
                best = max(best, 700)
        return best

    def _optima_pickup_validate_package(self, provider_code=False, point=False):
        """Validate one parcel with one bounded Sendcloud API request.

        The hosted picker already returns an enabled Sendcloud service point and
        its carrier code. For Phase 1 we therefore use Shipping Products as the
        authoritative dimensional/weight filter, then require the returned
        method to map to a synchronized Odoo PUDO method of that *same* point
        carrier. This avoids the previous second/third ``shipping_methods``
        requests that could make checkout exceed proxy/worker timeouts while
        keeping the dimensional validation fail-closed.
        """
        validation = super()._optima_pickup_validate_package(provider_code, point)
        if provider_code != "sendcloud" or not validation.get("success"):
            return validation

        self.ensure_one()
        package = validation["package"]
        carriers = self._optima_pickup_get_provider_carriers().get(
            "sendcloud", self.env["delivery.carrier"]
        )
        integration = self._optima_sendcloud_pickup_integration(carriers)
        if not integration:
            return {
                **validation,
                "success": False,
                "message": _(
                    "No hay una integración Sendcloud activa con Service Points para validar el bulto."
                ),
            }

        if integration:
            carriers = carriers.filtered(
                lambda carrier: carrier.sendcloud_integration_id == integration
            )

        point = point or {}
        point_carrier_code = point.get("carrier_code") or ""
        scored = [
            (self._optima_sendcloud_carrier_match_score(carrier, point_carrier_code), carrier)
            for carrier in carriers
        ]
        best_point_score = max((score for score, _carrier in scored), default=0)
        point_carriers = self.env["delivery.carrier"]
        if best_point_score:
            for score, carrier in scored:
                if score == best_point_score:
                    point_carriers |= carrier
        if not point_carriers:
            return {
                **validation,
                "success": False,
                "message": _(
                    "El punto pertenece a un transportista Sendcloud que no tiene un método PUDO sincronizado en Odoo."
                ),
            }

        cache_key = self._optima_sendcloud_validation_cache_key(integration, point, package)
        cached_validation = self._optima_sendcloud_cache_get("validation", cache_key)
        package_weight = float(package.get("weight_kg") or 0.0)
        compatible_methods = []
        compatible_ids = []
        if isinstance(cached_validation, dict) and cached_validation.get("methods"):
            compatible_methods = [
                dict(method) for method in cached_validation.get("methods") or []
                if isinstance(method, dict)
            ]
            compatible_ids = [
                int(method.get("id")) for method in compatible_methods
                if str(method.get("id") or "").isdigit()
            ]
            _logger.info(
                "Optima pickup: reusing Sendcloud package/method validation for carrier=%s zip=%s",
                point_carrier_code,
                point.get("zip_code") or "",
            )
        else:
            product_result = self._optima_sendcloud_shipping_product_methods(
                integration, point, package
            )
            if not product_result.get("success"):
                return {**validation, **product_result, "package": package}
            product_methods = product_result.get("methods") or {}
            if not product_methods:
                return {
                    **validation,
                    "success": False,
                    "message": _(
                        "El bulto estimado (%s) no cumple los límites de ningún método de punto de recogida disponible en Sendcloud."
                    ) % self._optima_sendcloud_package_label(package),
                }

            for api_method in product_methods.values():
                best_method_score = 0
                for carrier in point_carriers:
                    if not self._optima_sendcloud_weight_matches(carrier, package_weight):
                        continue
                    best_method_score = max(
                        best_method_score,
                        self._optima_sendcloud_api_method_match_score(carrier, api_method),
                    )
                if not best_method_score:
                    continue
                method = dict(api_method)
                method["_optima_match_score"] = best_method_score
                compatible_methods.append(method)
                try:
                    method_id = int(api_method.get("id") or 0)
                except (TypeError, ValueError):
                    method_id = 0
                if method_id:
                    compatible_ids.append(method_id)
            if compatible_methods:
                self._optima_sendcloud_cache_put(
                    "validation", cache_key, {"methods": compatible_methods}
                )

        if not compatible_methods:
            _logger.warning(
                "Optima pickup: Shipping Products returned package-compatible methods %s, "
                "but none maps to point carrier %s / local methods %s",
                sorted(product_methods),
                point_carrier_code,
                point_carriers.mapped("display_name"),
            )
            return {
                **validation,
                "success": False,
                "message": _(
                    "El punto seleccionado no tiene un método sincronizado compatible con el bulto estimado (%s)."
                ) % self._optima_sendcloud_package_label(package),
            }

        return {
            **validation,
            "success": True,
            "message": False,
            "sendcloud_integration_id": integration.id,
            "sendcloud_point_carrier_score": best_point_score,
            "sendcloud_compatible_method_ids": sorted(set(compatible_ids)),
            "sendcloud_compatible_methods": compatible_methods,
        }

    @staticmethod
    def _optima_sendcloud_country_value(value):
        if not value:
            return ""
        if getattr(value, "_name", None):
            for name in ("code", "iso_2", "country_code"):
                if name in value._fields:
                    code = value[name]
                    if code and not getattr(code, "_name", None):
                        return str(code).upper()
            return ""
        text = str(value).strip().upper()
        return text if len(text) == 2 else ""

    def _optima_sendcloud_line_country(self, line, role):
        """Extract origin/destination ISO2 from an OCA Sendcloud route line."""
        exact = {
            "from": (
                "from_iso_2", "from_country_code", "from_country_id", "from_country",
                "country_from_id", "country_from", "origin_country_id", "origin_country_code",
            ),
            "to": (
                "to_iso_2", "to_country_code", "to_country_id", "to_country",
                "country_to_id", "country_to", "destination_country_id", "destination_country_code",
            ),
        }[role]
        for name in exact:
            if name in line._fields:
                code = self._optima_sendcloud_country_value(line[name])
                if code:
                    return code
        role_tokens = (role,) if role == "from" else ("to", "destination")
        for name in line._fields:
            lname = name.lower()
            if not ("country" in lname or "iso" in lname):
                continue
            if not any(token in lname for token in role_tokens):
                continue
            code = self._optima_sendcloud_country_value(line[name])
            if code:
                return code
        return ""

    def _optima_sendcloud_route_price(self, carrier):
        """Return the synced Sendcloud price for the matching country route.

        ``delivery_sendcloud_oca`` stores prices per shipping route (the rows
        displayed in the Sendcloud method under From Country / To Country /
        Price).  ``rate_shipment`` can legitimately return the delivery
        product's 0.00 price in this checkout context, so the pickup adapter
        first consumes the synced route price that belongs to the technical
        method itself.

        The connector's internal relation names have changed between series,
        therefore this helper discovers Sendcloud route relations by model
        metadata instead of depending on one private OCA field name.
        """
        self.ensure_one()
        partner = self.partner_shipping_id or self.partner_id
        destination = (partner.country_id.code or "").upper()
        warehouse_partner = self.warehouse_id.partner_id if self.warehouse_id else self.company_id.partner_id
        origin = (warehouse_partner.country_id.code or self.company_id.country_id.code or "").upper()

        roots = [carrier]
        for name, field in carrier._fields.items():
            if field.type != "many2one" or not name.startswith("sendcloud_"):
                continue
            try:
                related = carrier[name]
            except Exception:
                continue
            if related and related not in roots:
                roots.append(related)

        seen = set()
        candidates = []
        for root in roots:
            for name, field in root._fields.items():
                if field.type not in ("one2many", "many2many"):
                    continue
                lname = name.lower()
                comodel = (field.comodel_name or "").lower()
                if "sendcloud" not in lname and "sendcloud" not in comodel and "country" not in lname:
                    continue
                try:
                    lines = root[name]
                except Exception:
                    continue
                for line in lines:
                    key = (line._name, line.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    price = self._optima_sendcloud_numeric_field(
                        line,
                        ("price", "sendcloud_price"),
                        ("price",),
                    )
                    if price is None:
                        continue
                    from_code = self._optima_sendcloud_line_country(line, "from")
                    to_code = self._optima_sendcloud_line_country(line, "to")
                    # A route row must at least identify the destination.  When
                    # origin is present, require it too.
                    if destination and to_code and to_code != destination:
                        continue
                    if origin and from_code and from_code != origin:
                        continue
                    if destination and not to_code:
                        continue
                    candidates.append((price, line, from_code, to_code))

        if not candidates:
            return False, 0.0, False
        # There should normally be one ES->ES row.  If a connector variant has
        # duplicates, use the lowest synchronized amount.
        price, line, _from, _to = min(candidates, key=lambda item: (item[0], item[1].id))
        return True, max(float(price), 0.0), line

    def _optima_sendcloud_remote_method_price(self, integration, api_method, package, point):
        """Fallback to Sendcloud Shipping Price for a validated method.

        This is only used when the synchronized Odoo route has no usable price.
        Zonal context (origin/destination postal codes) is always included. Results
        are cached per method/carrier/postcode/package for 30 minutes so switching
        between two points of the same service does not repeat the price lookup.
        """
        self.ensure_one()
        try:
            method_id = int((api_method or {}).get("id") or 0)
        except (TypeError, ValueError):
            method_id = 0
        if not method_id:
            return False
        origin = self._optima_sendcloud_origin_data()
        destination_country = str(point.get("country_code") or "").upper()
        key = "|".join([
            str(integration.id or 0),
            str(method_id),
            self._optima_sendcloud_canonical_carrier(point.get("carrier_code") or ""),
            str(point.get("zip_code") or "").strip().upper(),
            self._optima_pickup_address_fingerprint(),
            self._optima_pickup_logistics_fingerprint(package),
        ])
        cached = self._optima_sendcloud_cache_get("price", key)
        if isinstance(cached, dict) and cached.get("price") is not None:
            return cached

        params = {
            "shipping_method_id": method_id,
            "from_country": origin.get("country_code") or "",
            "to_country": destination_country,
            "weight": max(int(ceil(float(package.get("weight_kg") or 0.0) * 1000.0)), 1),
            "weight_unit": "gram",
        }
        if origin.get("postal_code"):
            params["from_postal_code"] = str(origin["postal_code"])[:12]
        if point.get("zip_code"):
            params["to_postal_code"] = str(point["zip_code"])[:12]
        if not params["from_country"] or not params["to_country"]:
            return False

        result = self._optima_sendcloud_api_get(integration, "shipping-price", params=params)
        if not result.get("success"):
            return False
        payload = result.get("payload")
        rows = payload if isinstance(payload, list) else []
        selected = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_country = str(row.get("to_country") or "").upper()
            if destination_country and row_country and row_country != destination_country:
                continue
            try:
                price = float(row.get("price"))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            currency = str(row.get("currency") or self.currency_id.name or "EUR").upper()
            selected = {"price": price, "currency": currency}
            break
        if not selected:
            return False

        if selected["currency"] != (self.currency_id.name or "").upper():
            source_currency = self.env["res.currency"].search(
                [("name", "=", selected["currency"])], limit=1
            )
            if not source_currency:
                return False
            order_date = fields.Date.to_date(self.date_order) if self.date_order else fields.Date.context_today(self)
            selected["price"] = source_currency._convert(
                selected["price"], self.currency_id, self.company_id, order_date
            )
            selected["currency"] = self.currency_id.name

        self._optima_sendcloud_cache_put("price", key, selected)
        return selected

    @staticmethod
    def _optima_sendcloud_dimension_to_mm(value, unit):
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        factor = {
            "millimeter": 1.0,
            "millimetre": 1.0,
            "mm": 1.0,
            "centimeter": 10.0,
            "centimetre": 10.0,
            "cm": 10.0,
            "meter": 1000.0,
            "metre": 1000.0,
            "m": 1000.0,
        }.get(str(unit or "millimeter").strip().lower(), 1.0)
        return max(number * factor, 0.0)

    def _optima_sendcloud_method_limits_snapshot(self, api_method):
        """Normalize Sendcloud method constraints into the core snapshot schema."""
        method = api_method if isinstance(api_method, dict) else {}
        properties = method.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        dimensions = properties.get("max_dimensions")
        dimensions = dimensions if isinstance(dimensions, dict) else {}
        unit = dimensions.get("unit") or "millimeter"

        try:
            min_weight_kg = max(float(properties.get("min_weight") or 0.0) / 1000.0, 0.0)
        except (TypeError, ValueError):
            min_weight_kg = 0.0
        try:
            max_weight_kg = max(float(properties.get("max_weight") or 0.0) / 1000.0, 0.0)
        except (TypeError, ValueError):
            max_weight_kg = 0.0

        snapshot = {
            "provider": "sendcloud",
            "source": "shipping-products",
            "remote_method_id": method.get("id") or False,
            "remote_method_name": method.get("name") or "",
            "min_weight_kg": min_weight_kg,
            "max_weight_kg": max_weight_kg,
            "max_length_mm": self._optima_sendcloud_dimension_to_mm(
                dimensions.get("length"), unit
            ),
            "max_width_mm": self._optima_sendcloud_dimension_to_mm(
                dimensions.get("width"), unit
            ),
            "max_height_mm": self._optima_sendcloud_dimension_to_mm(
                dimensions.get("height"), unit
            ),
        }
        # A method can be valid even when Sendcloud omits numeric properties.
        # Return a snapshot anyway so the back office can distinguish
        # "validated but not numerically reported" from "never validated".
        return snapshot

    def _optima_pickup_resolve_delivery(self, provider_code, normalized, raw_point, extra):
        if provider_code != "sendcloud":
            return super()._optima_pickup_resolve_delivery(
                provider_code, normalized, raw_point, extra
            )

        self.ensure_one()
        validation = (extra or {}).get("_optima_package_validation") or {}
        package = validation.get("package") or self._optima_pickup_package_profile()
        compatible_api_methods = validation.get("sendcloud_compatible_methods") or []
        if not validation.get("success") or not compatible_api_methods:
            return {
                "success": False,
                "message": validation.get("message")
                or _("No se ha podido validar el bulto con Sendcloud."),
            }

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
        point_scored = [
            (self._optima_sendcloud_carrier_match_score(carrier, point_carrier_code), carrier)
            for carrier in carriers
        ]
        best_point_score = max((score for score, _carrier in point_scored), default=0)
        point_carriers = self.env["delivery.carrier"]
        if best_point_score:
            for score, carrier in point_scored:
                if score == best_point_score:
                    point_carriers |= carrier
        if not point_carriers:
            return {
                "success": False,
                "message": _(
                    "No encuentro un método PUDO sincronizado para el transportista del punto seleccionado."
                ),
            }

        # From this point onward only methods belonging to the selected point's
        # carrier are eligible. A remote method from another carrier can never
        # win merely because its id/name mapping is stronger.
        carriers = point_carriers
        package_weight = float(package.get("weight_kg") or 0.0)
        candidates = []
        for carrier in carriers.sorted(lambda item: (item.sequence, item.id)):
            # Local synchronized bracket remains a secondary sanity check.  The
            # Sendcloud API has already filtered the package by weight/dimensions.
            if not self._optima_sendcloud_weight_matches(carrier, package_weight):
                continue
            method_score = 0
            matched_api_method = False
            for api_method in compatible_api_methods:
                score = self._optima_sendcloud_api_method_match_score(carrier, api_method)
                if score > method_score:
                    method_score = score
                    matched_api_method = api_method
            if not method_score:
                continue
            point_score = self._optima_sendcloud_carrier_match_score(
                carrier, point_carrier_code
            )
            candidates.append(
                {
                    "carrier": carrier,
                    "method_score": method_score,
                    "point_score": point_score,
                    "api_method": matched_api_method,
                }
            )

        if not candidates:
            _logger.warning(
                "Optima pickup: Sendcloud returned compatible remote methods %s but none maps "
                "unambiguously to a synchronized Odoo PUDO method. Point carrier=%s, locals=%s",
                [m.get("id") for m in compatible_api_methods],
                point_carrier_code,
                carriers.mapped("display_name"),
            )
            return {
                "success": False,
                "message": _(
                    "Sendcloud tiene un método compatible, pero no se puede vincular con un método PUDO sincronizado en Odoo. Sincroniza los métodos Sendcloud."
                ),
            }

        # Keep only the strongest remote-method mapping.  Carrier-code affinity
        # breaks ties but can never rescue a method whose API identity did not
        # match; this avoids selecting another service that happens to share a
        # carrier and weight bracket.
        best_method_score = max(item["method_score"] for item in candidates)
        candidates = [
            item for item in candidates if item["method_score"] == best_method_score
        ]
        best_point_score = max(item["point_score"] for item in candidates)
        if best_point_score:
            candidates = [
                item for item in candidates if item["point_score"] == best_point_score
            ]

        successful_rates = []
        errors = []
        for item in candidates:
            carrier = item["carrier"]
            route_found, route_price, route_line = self._optima_sendcloud_route_price(carrier)
            if route_found:
                successful_rates.append(
                    {
                        **item,
                        "price": route_price,
                        "warning": "",
                        "source": "sendcloud_route",
                        "route_line": route_line,
                    }
                )
                continue

            remote_price = False
            if integration:
                remote_price = self._optima_sendcloud_remote_method_price(
                    integration, item.get("api_method") or {}, package, normalized
                )
            if remote_price:
                successful_rates.append(
                    {
                        **item,
                        "price": float(remote_price["price"]),
                        "warning": "",
                        "source": "sendcloud_shipping_price",
                        "route_line": False,
                    }
                )
                continue

            if self.env.context.get("optima_pickup_prewarm"):
                # Prewarming must stay bounded. Route prices and the dedicated
                # shipping-price endpoint cover the fast path; the legacy
                # rate_shipment fallback remains available to authoritative
                # set_point resolution if those two sources cannot price it.
                continue

            try:
                rate = carrier.with_context(optima_pickup_force_rate=True).rate_shipment(
                    self.with_context(optima_pickup_force_rate=True)
                )
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
            if price <= 0:
                continue
            successful_rates.append(
                {
                    **item,
                    "price": price,
                    "warning": rate.get("warning_message") or "",
                    "source": "rate_shipment",
                    "route_line": False,
                }
            )

        if not successful_rates:
            diagnostic = errors[0] if errors else ""
            _logger.warning(
                "Optima pickup: no positive Sendcloud route/rate after API package validation. "
                "Point carrier=%s, weight=%.3f kg, methods=%s, error=%s",
                point_carrier_code,
                package_weight,
                [item["carrier"].display_name for item in candidates],
                diagnostic,
            )
            return {
                "success": False,
                "message": _(
                    "El bulto es compatible, pero no encuentro una tarifa Sendcloud válida para el método sincronizado."
                ),
            }

        selected = min(
            successful_rates,
            key=lambda item: (
                item["price"],
                item["carrier"].sequence,
                item["carrier"].id,
            ),
        )
        message = selected["warning"] or ""
        if (
            message
            and self.sendcloud_service_point_address
            and "requires a service point" in str(message).lower()
        ):
            _logger.info(
                "Optima pickup: ignoring Sendcloud service-point warning for already selected point %s: %s",
                normalized.get("id"),
                message,
            )
            message = ""

        _logger.info(
            "Optima pickup: validated package %.3fkg %.0fx%.0fx%.0fmm; resolved point %s "
            "(%s) to %s / Sendcloud method %s at %.2f %s via %s",
            package_weight,
            package.get("length_mm", 0.0),
            package.get("width_mm", 0.0),
            package.get("height_mm", 0.0),
            normalized.get("id"),
            point_carrier_code,
            selected["carrier"].display_name,
            (selected.get("api_method") or {}).get("id"),
            selected["price"],
            self.currency_id.name,
            selected.get("source"),
        )
        return {
            "success": True,
            "carrier": selected["carrier"],
            "price": selected["price"],
            "message": message,
            "method_limits": self._optima_sendcloud_method_limits_snapshot(
                selected.get("api_method") or {}
            ),
        }

    def _optima_pickup_prewarm_point(self, provider_code, point, extra=None):
        """Warm Sendcloud compatibility/rating caches without changing checkout.

        The customer naturally previews a map card before confirming it. We use
        that think-time to run the same Shipping Products + price resolution in
        advance. Cache writes are collected in memory and merged only after all
        remote calls finish, so a concurrent real selection is never held behind
        a Sendcloud network request.
        """
        if provider_code != "sendcloud":
            return super()._optima_pickup_prewarm_point(provider_code, point, extra)

        self.ensure_one()
        try:
            normalized = self._optima_pickup_prepare_point(
                provider_code, point, extra or {}
            )
        except ValidationError as exc:
            return {"success": False, "prepared": False, "message": str(exc)}

        collector = {}
        warm_order = self.with_context(
            optima_sendcloud_cache_collector=collector,
            optima_pickup_prewarm=True,
        )
        validation = warm_order._optima_pickup_validate_package(
            provider_code=provider_code, point=normalized
        ) or {}
        resolution = {}
        if validation.get("success"):
            resolve_extra = dict(extra or {})
            resolve_extra["_optima_package_validation"] = validation
            resolution = warm_order._optima_pickup_resolve_delivery(
                provider_code, normalized, point, resolve_extra
            ) or {}

        # Commit all warmed buckets at once, after Sendcloud I/O has completed.
        # This keeps the sale-order row lock extremely short and makes concurrent
        # prewarm/set_point requests safe.
        if collector:
            self._optima_sendcloud_cache_merge(collector)

        prepared = bool(
            validation.get("success")
            and (resolution.get("success") or collector)
        )
        return {
            "success": bool(validation.get("success")),
            "prepared": prepared,
            "message": resolution.get("message") or validation.get("message") or False,
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

    def _optima_delivery_provider_sync_picking(self, picking):
        """Bridge the checkout Sendcloud service point to the stock shipment."""
        result = super()._optima_delivery_provider_sync_picking(picking)
        self.ensure_one()
        if (
            self.optima_pickup_mode
            and self.optima_pickup_provider_code == "sendcloud"
            and picking.picking_type_id.code == "outgoing"
        ):
            picking._optima_sendcloud_sync_service_point_from_sale()
        return result

    def _optima_pickup_after_clear(self):
        super()._optima_pickup_after_clear()
        self.write(
            {
                "sendcloud_service_point_address": False,
                "optima_sendcloud_to_post_number": False,
                "optima_sendcloud_resolution_cache": {},
            }
        )
