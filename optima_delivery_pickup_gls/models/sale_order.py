import math
import re
import time

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    optima_gls_parcelshop_cache = fields.Json(
        string="Caché temporal GLS ParcelShop",
        copy=False,
        default=dict,
    )

    def _optima_gls_provider_carriers(self):
        self.ensure_one()
        return self._optima_pickup_get_provider_carriers().get(
            "gls", self.env["delivery.carrier"]
        ).filtered(
            lambda carrier: carrier.delivery_type == "gls_asm"
            and carrier.gls_asm_shiptime == "19"
        )

    def _optima_gls_cache_store(self, shops):
        """Cache canonical points returned server-side by GLS for a short time.

        The browser receives the same points afterwards. set_point can therefore
        verify an exact point id without issuing a second SOAP request in the
        normal map -> select flow.
        """
        self.ensure_one()
        values = {}
        for shop in shops or []:
            if not isinstance(shop, dict):
                continue
            code = str(shop.get("code") or shop.get("id") or "").strip()
            if code:
                values[code] = shop
        self.write(
            {
                "optima_gls_parcelshop_cache": {
                    "ts": time.time(),
                    "points": values,
                }
            }
        )

    def _optima_gls_cache_get(self, code, ttl=900):
        self.ensure_one()
        cache = self.optima_gls_parcelshop_cache or {}
        if not isinstance(cache, dict):
            return False
        try:
            age = time.time() - float(cache.get("ts") or 0.0)
        except (TypeError, ValueError):
            return False
        if age < 0 or age > ttl:
            return False
        points = cache.get("points") or {}
        if not isinstance(points, dict):
            return False
        point = points.get(str(code or "").strip())
        return point if isinstance(point, dict) else False

    @staticmethod
    def _optima_gls_haversine_m(lat1, lon1, lat2, lon2):
        """Great-circle distance in metres between two WGS84 coordinates."""
        radius = 6371008.8
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlambda = math.radians(float(lon2) - float(lon1))
        a = (
            math.sin(dphi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        )
        return radius * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(1.0 - a, 0.0)))

    @staticmethod
    def _optima_gls_distance_token(value):
        """Return ``(number, explicit_scale)`` for the GLS Distancia field.

        GLS' supplied documentation exposes ``Distancia`` but does not state its
        unit. Some service revisions include a suffix while others return only a
        number. Explicit ``m``/``km`` values are honoured directly; unitless
        values are calibrated once for the whole response below.
        """
        if value in (None, False, ""):
            return (None, None)
        raw = str(value).strip().lower().replace(" ", " ")
        match = re.search(r"[-+]?\d[\d.,]*", raw)
        if not match:
            return (None, None)
        token = match.group(0)
        # Spanish responses normally use comma as decimal separator. Be
        # defensive with values that also contain a thousands separator.
        if "," in token and "." in token:
            if token.rfind(",") > token.rfind("."):
                token = token.replace(".", "").replace(",", ".")
            else:
                token = token.replace(",", "")
        elif "," in token:
            token = token.replace(",", ".")
        try:
            number = max(float(token), 0.0)
        except (TypeError, ValueError):
            return (None, None)
        if re.search(r"(?:km|kms|kil[oó]metros?)\.?\s*$", raw):
            return (number, 1000.0)
        if re.search(r"(?:m|mts?|metros?)\.?\s*$", raw):
            return (number, 1.0)
        return (number, None)

    @classmethod
    def _optima_gls_unitless_distance_scale(cls, shops):
        """Infer whether unitless GLS ``Distancia`` values are metres or km.

        The official GLS material delivered with the connector does not define
        the unit. Rather than hard-code an unsafe assumption, compare the scale
        of the numeric distances with the geographic spread of the coordinates
        returned in the same response. With the usual 10-50 nearby points this
        makes metres-vs-kilometres unambiguous and avoids an extra geocoding API.
        """
        values = []
        coords = []
        for shop in shops or []:
            if not isinstance(shop, dict):
                continue
            number, explicit_scale = cls._optima_gls_distance_token(shop.get("distance"))
            if number is not None and explicit_scale is None:
                values.append(number)
            try:
                lat = float(shop.get("latitude") or 0.0)
                lon = float(shop.get("longitude") or 0.0)
            except (TypeError, ValueError):
                continue
            if lat and lon:
                coords.append((lat, lon))
        if not values:
            return 1.0

        max_raw = max(values)
        spread_m = 0.0
        # At most ~50 shops are returned by GLS, so O(n²) here is tiny and gives
        # a much better scale signal than a crude latitude/longitude bounding box.
        for index, (lat1, lon1) in enumerate(coords):
            for lat2, lon2 in coords[index + 1 :]:
                spread_m = max(spread_m, cls._optima_gls_haversine_m(lat1, lon1, lat2, lon2))

        if spread_m > 0.0 and max_raw > 0.0:
            # The farthest point from the search origin is normally of the same
            # order of magnitude as the cloud's diameter. Pick the scale whose
            # order of magnitude best matches that geographic spread.
            target = max(spread_m * 0.75, 1.0)
            scores = {}
            for scale in (1.0, 1000.0):
                estimate = max(max_raw * scale, 1e-9)
                scores[scale] = abs(math.log10(estimate / target))
            return min(scores, key=scores.get)

        # Fallback for a degenerate response with no useful coordinate spread.
        # Nearby-locator APIs commonly return a small decimal when using km and
        # a larger integer when using metres.
        return 1000.0 if max_raw < 100.0 else 1.0

    @classmethod
    def _optima_gls_distances_m(cls, shops):
        """Map GLS shop code to a normalized distance in metres."""
        unitless_scale = cls._optima_gls_unitless_distance_scale(shops)
        result = {}
        for shop in shops or []:
            if not isinstance(shop, dict):
                continue
            code = str(shop.get("code") or shop.get("id") or "").strip()
            if not code:
                continue
            number, explicit_scale = cls._optima_gls_distance_token(shop.get("distance"))
            if number is None:
                continue
            result[code] = max(number * (explicit_scale or unitless_scale), 0.0)
        return result

    @staticmethod
    def _optima_gls_opening_times(shop):
        """Normalize GLS Monday-Saturday strings to the map day format."""
        fields_by_day = (
            "monday_hours",
            "tuesday_hours",
            "wednesday_hours",
            "thursday_hours",
            "friday_hours",
            "saturday_hours",
        )
        result = {}
        for index, field_name in enumerate(fields_by_day):
            value = str((shop or {}).get(field_name) or "").strip()
            result[str(index)] = [value] if value else []
        result["6"] = []
        return result

    def _optima_pickup_provider_descriptor(self, provider_code, carriers):
        if provider_code != "gls":
            return super()._optima_pickup_provider_descriptor(provider_code, carriers)

        self.ensure_one()
        partner = self.partner_shipping_id or self.partner_id
        country = (partner.country_id.code or "ES").upper()
        default_query = self._optima_pickup_default_search_query()
        return {
            "code": "gls",
            "name": "GLS ParcelShop",
            "sequence": 30,
            "config": {
                "country": country,
                "postal_code": partner.zip or "",
                "city": partner.city or "",
                "default_query": default_query,
                "networks": "1",
                "cache_token": "%s:%s:%s" % (
                    country,
                    (partner.zip or "").strip().upper(),
                    (partner.city or "").strip().lower(),
                ),
            },
        }

    def _optima_pickup_search_points(self, provider_codes=None, query=None, radius_m=5000):
        result = super()._optima_pickup_search_points(
            provider_codes=provider_codes, query=query, radius_m=radius_m
        )
        self.ensure_one()

        requested = set(provider_codes or [])
        if requested and "gls" not in requested:
            return result

        carriers = self._optima_gls_provider_carriers()
        if not carriers:
            return result

        partner = self.partner_shipping_id or self.partner_id
        country_code = (partner.country_id.code or "ES").upper()
        search_query = (
            query or partner.zip or self._optima_pickup_default_search_query() or ""
        ).strip()
        if not search_query:
            result["errors"].append(
                {
                    "provider_code": "gls",
                    "message": _(
                        "GLS necesita una dirección, localidad o código postal para buscar ParcelShops."
                    ),
                }
            )
            return result

        try:
            shops = carriers[:1].gls_asm_search_parcelshops(
                search_query,
                country_code=country_code,
                networks="1",
            )
        except Exception as exc:  # provider error must not hide other providers
            result["errors"].append(
                {
                    "provider_code": "gls",
                    "message": _("No se han podido buscar ParcelShops GLS: %s") % exc,
                }
            )
            return result

        shops = [shop for shop in (shops or []) if isinstance(shop, dict)]
        self._optima_gls_cache_store(shops)

        # GetParcelShopProximosV3 does not accept a radius parameter. Normalize
        # the Distancia value returned by GLS and apply the exact radius chosen
        # in our unified map locally. This also gives GLS points a real
        # ``distance_m`` so they sort together with Sendcloud points.
        try:
            selected_radius_m = min(max(int(radius_m or 5000), 500), 50000)
        except (TypeError, ValueError):
            selected_radius_m = 5000
        gls_distances_m = self._optima_gls_distances_m(shops)
        has_distance_data = bool(gls_distances_m)

        public_points = []
        for shop in shops:
            code = str(shop.get("code") or "").strip()
            if not code:
                continue
            try:
                latitude = float(shop.get("latitude") or 0.0)
                longitude = float(shop.get("longitude") or 0.0)
            except (TypeError, ValueError):
                continue
            if not latitude or not longitude:
                continue

            distance_m = gls_distances_m.get(code)
            if has_distance_data:
                # If GLS supplied distances for this response, keep the map's
                # radius strict: a point without a usable distance cannot be
                # proven to be inside the selected radius.
                if distance_m is None or distance_m > selected_radius_m:
                    continue

            raw_point = {
                "id": code,
                "code": code,
                "network_id": str(shop.get("network_id") or ""),
                "name": shop.get("name") or "GLS ParcelShop",
                "street": shop.get("address") or "",
                "address": shop.get("address") or "",
                "postal_code": str(shop.get("postal_code") or ""),
                "city": shop.get("city") or "",
                "country": shop.get("country_code") or country_code,
                "country_code": shop.get("country_code") or country_code,
                "carrier": "gls",
                "carrier_name": "GLS",
                "latitude": latitude,
                "longitude": longitude,
                "distance": shop.get("distance") or "",
                "monday_hours": shop.get("monday_hours") or "",
                "tuesday_hours": shop.get("tuesday_hours") or "",
                "wednesday_hours": shop.get("wednesday_hours") or "",
                "thursday_hours": shop.get("thursday_hours") or "",
                "friday_hours": shop.get("friday_hours") or "",
                "saturday_hours": shop.get("saturday_hours") or "",
            }
            public_points.append(
                {
                    "key": "gls:%s" % code,
                    "provider_code": "gls",
                    "provider_name": "GLS ParcelShop",
                    "id": code,
                    "name": raw_point["name"],
                    "street": raw_point["street"],
                    "zip_code": raw_point["postal_code"],
                    "city": raw_point["city"],
                    "country_code": raw_point["country_code"],
                    "carrier_code": "gls",
                    "carrier_name": "GLS",
                    "latitude": latitude,
                    "longitude": longitude,
                    "distance_m": float(distance_m or 0.0),
                    "shop_type": "parcelshop",
                    "opening_times": self._optima_gls_opening_times(shop),
                    "quote": {
                        "price": None,
                        "currency": self.currency_id.name or "EUR",
                        "method_name": "",
                        "lead_time_hours": 0,
                        "estimated": True,
                    },
                    "marker_icon": "/optima_delivery_pickup_gls/static/src/img/markers/gls.png",
                    "raw_point": raw_point,
                    "extra": {"network_id": raw_point["network_id"]},
                }
            )

        public_points.sort(
            key=lambda point: (
                point.get("distance_m") or 10**12,
                point.get("name") or "",
            )
        )
        result["points"].extend(public_points[:100])
        return result

    def _optima_pickup_prepare_point(self, provider_code, point, extra=None):
        if provider_code != "gls":
            return super()._optima_pickup_prepare_point(provider_code, point, extra)

        self.ensure_one()
        if not isinstance(point, dict):
            raise ValidationError(_("El punto devuelto por GLS no es válido."))

        point_id = str(point.get("id") or point.get("code") or "").strip()
        name = str(point.get("name") or "").strip()
        street = str(point.get("street") or point.get("address") or "").strip()
        postal_code = str(point.get("postal_code") or point.get("zip_code") or "").strip()
        city = str(point.get("city") or "").strip()
        country = str(
            point.get("country")
            or point.get("country_code")
            or (self.partner_shipping_id.country_id.code if self.partner_shipping_id.country_id else "ES")
            or "ES"
        ).strip().upper()
        if not all((point_id, name, street, postal_code, city, country)):
            raise ValidationError(_("El ParcelShop GLS no contiene todos los datos obligatorios."))

        partner = self.partner_shipping_id or self.partner_id
        expected_country = (partner.country_id.code or "").upper()
        if expected_country and country != expected_country:
            raise ValidationError(_("El ParcelShop GLS pertenece a otro país."))

        try:
            latitude = float(point.get("latitude") or point.get("lat") or 0.0)
            longitude = float(
                point.get("longitude") or point.get("lng") or point.get("lon") or 0.0
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("Las coordenadas del ParcelShop GLS no son válidas.")) from exc

        return {
            "id": point_id,
            "name": name,
            "street": street,
            "zip_code": postal_code,
            "city": city,
            "country_code": country,
            "carrier_code": "gls",
            "carrier_name": "GLS",
            "latitude": latitude,
            "longitude": longitude,
        }

    def _optima_gls_authoritative_point(self, point_id, postal_code, country_code):
        self.ensure_one()
        cached = self._optima_gls_cache_get(point_id)
        if cached:
            return cached

        carriers = self._optima_gls_provider_carriers()
        if not carriers:
            return False
        lookup = postal_code or self._optima_pickup_default_search_query()
        shops = carriers[:1].gls_asm_search_parcelshops(
            lookup,
            country_code=country_code or "ES",
            networks="1",
        )
        shops = [shop for shop in (shops or []) if isinstance(shop, dict)]
        self._optima_gls_cache_store(shops)
        for shop in shops:
            if str(shop.get("code") or "").strip() == str(point_id or "").strip():
                return shop
        return False

    def _optima_pickup_verify_point(self, provider_code, normalized, raw_point, extra=None):
        if provider_code != "gls":
            return super()._optima_pickup_verify_point(
                provider_code, normalized, raw_point, extra
            )

        self.ensure_one()
        point_id = str((normalized or {}).get("id") or "").strip()
        try:
            shop = self._optima_gls_authoritative_point(
                point_id,
                (normalized or {}).get("zip_code") or "",
                (normalized or {}).get("country_code") or "ES",
            )
        except Exception as exc:
            return {
                "success": False,
                "message": _("GLS no ha podido verificar el ParcelShop seleccionado: %s") % exc,
            }
        if not shop:
            return {
                "success": False,
                "message": _("GLS ya no devuelve el ParcelShop seleccionado."),
            }

        canonical_raw = {
            "id": str(shop.get("code") or ""),
            "code": str(shop.get("code") or ""),
            "network_id": str(shop.get("network_id") or ""),
            "name": shop.get("name") or "GLS ParcelShop",
            "street": shop.get("address") or "",
            "address": shop.get("address") or "",
            "postal_code": str(shop.get("postal_code") or ""),
            "city": shop.get("city") or "",
            "country": shop.get("country_code") or (normalized or {}).get("country_code") or "ES",
            "country_code": shop.get("country_code") or (normalized or {}).get("country_code") or "ES",
            "carrier": "gls",
            "carrier_name": "GLS",
            "latitude": shop.get("latitude") or 0.0,
            "longitude": shop.get("longitude") or 0.0,
            "distance": shop.get("distance") or "",
            "monday_hours": shop.get("monday_hours") or "",
            "tuesday_hours": shop.get("tuesday_hours") or "",
            "wednesday_hours": shop.get("wednesday_hours") or "",
            "thursday_hours": shop.get("thursday_hours") or "",
            "friday_hours": shop.get("friday_hours") or "",
            "saturday_hours": shop.get("saturday_hours") or "",
        }
        try:
            canonical = self._optima_pickup_prepare_point(
                "gls", canonical_raw, extra or {}
            )
        except ValidationError as exc:
            return {"success": False, "message": str(exc)}
        if str(canonical.get("id") or "") != point_id:
            return {
                "success": False,
                "message": _("El identificador del ParcelShop GLS ha cambiado."),
            }
        return {
            "success": True,
            "normalized": canonical,
            "raw_point": canonical_raw,
        }

    def _optima_pickup_resolve_delivery(self, provider_code, normalized, raw_point, extra):
        if provider_code != "gls":
            return super()._optima_pickup_resolve_delivery(
                provider_code, normalized, raw_point, extra
            )

        self.ensure_one()
        carriers = self._optima_gls_provider_carriers()
        if not carriers:
            return {
                "success": False,
                "message": _(
                    "No hay ningún método GLS ParcelShop (Horario 19) disponible para este pedido."
                ),
            }

        candidates = []
        diagnostics = []
        for carrier in carriers:
            try:
                rate = carrier.with_context(optima_pickup_force_rate=True).rate_shipment(self)
            except Exception as exc:
                diagnostics.append("%s: %s" % (carrier.display_name, exc))
                continue
            if not rate or not rate.get("success"):
                diagnostics.append(
                    "%s: %s"
                    % (
                        carrier.display_name,
                        (rate or {}).get("error_message") or _("sin tarifa"),
                    )
                )
                continue
            try:
                price = max(float(rate.get("price") or 0.0), 0.0)
            except (TypeError, ValueError):
                diagnostics.append("%s: %s" % (carrier.display_name, _("precio no válido")))
                continue
            candidates.append((price, carrier))

        if not candidates:
            return {
                "success": False,
                "message": _("GLS ParcelShop no ha podido calcular el precio de entrega.%s")
                % ((" " + " · ".join(diagnostics)) if diagnostics else ""),
            }

        price, carrier = sorted(candidates, key=lambda item: (item[0], item[1].id))[0]
        return {
            "success": True,
            "carrier": carrier,
            "price": price,
            "message": False,
            "method_limits": {
                "provider": "gls",
                "min_weight_kg": 0.0,
                "max_weight_kg": 0.0,
                "max_length_mm": 0.0,
                "max_width_mm": 0.0,
                "max_height_mm": 0.0,
            },
        }

    def _optima_pickup_prewarm_point(self, provider_code, point, extra=None):
        if provider_code != "gls":
            return super()._optima_pickup_prewarm_point(provider_code, point, extra)
        self.ensure_one()
        point_id = str((point or {}).get("id") or (point or {}).get("code") or "").strip()
        return {
            "success": True,
            "prepared": bool(point_id and self._optima_gls_cache_get(point_id)),
        }

    def _optima_pickup_provider_confirmation_error(self):
        error = super()._optima_pickup_provider_confirmation_error()
        if error or self.optima_pickup_provider_code != "gls":
            return error
        carrier = self.optima_pickup_delivery_carrier_id
        if not carrier or carrier.delivery_type != "gls_asm" or carrier.gls_asm_shiptime != "19":
            return _(
                "El pedido GLS ParcelShop ya no está asociado a un método GLS con Horario 19."
            )
        raw = self.optima_pickup_raw_data or {}
        if not isinstance(raw, dict) or str(raw.get("code") or raw.get("id") or "").strip() != str(
            self.optima_pickup_external_id or ""
        ).strip():
            return _("El snapshot del ParcelShop GLS no coincide con el punto seleccionado.")
        return False

    def _optima_pickup_after_clear(self):
        result = super()._optima_pickup_after_clear()
        if self.optima_pickup_provider_code == "gls" or self.optima_gls_parcelshop_cache:
            self.write({"optima_gls_parcelshop_cache": {}})
        return result
