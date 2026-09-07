from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    optima_pickup_mode = fields.Boolean(
        string="Punto de recogida seleccionado",
        copy=False,
    )
    optima_pickup_provider_code = fields.Char(
        string="Proveedor pickup",
        copy=False,
        index=True,
    )
    optima_pickup_external_id = fields.Char(
        string="ID externo del punto",
        copy=False,
        index=True,
    )
    optima_pickup_carrier_code = fields.Char(string="Código transportista", copy=False)
    optima_pickup_carrier_name = fields.Char(string="Transportista", copy=False)
    optima_pickup_name = fields.Char(string="Punto de recogida", copy=False)
    optima_pickup_street = fields.Char(string="Dirección del punto", copy=False)
    optima_pickup_zip = fields.Char(string="CP del punto", copy=False)
    optima_pickup_city = fields.Char(string="Ciudad del punto", copy=False)
    optima_pickup_country_code = fields.Char(string="País del punto", copy=False)
    optima_pickup_latitude = fields.Float(string="Latitud", digits=(16, 7), copy=False)
    optima_pickup_longitude = fields.Float(string="Longitud", digits=(16, 7), copy=False)
    optima_pickup_raw_data = fields.Json(string="Datos originales del proveedor", copy=False)

    def _optima_pickup_get_provider_carriers(self):
        """Return available pickup carriers grouped by provider code."""
        self.ensure_one()
        grouped = defaultdict(lambda: self.env["delivery.carrier"])
        for carrier in self._get_delivery_methods():
            code = carrier.optima_pickup_provider_code
            if code:
                grouped[code] |= carrier
        return grouped

    def _optima_pickup_provider_descriptor(self, provider_code, carriers):
        """Adapter hook: public checkout configuration for one provider."""
        self.ensure_one()
        return False

    def _optima_pickup_get_providers(self):
        self.ensure_one()
        providers = []
        grouped = self._optima_pickup_get_provider_carriers()
        for code, carriers in grouped.items():
            descriptor = self._optima_pickup_provider_descriptor(code, carriers)
            if descriptor:
                descriptor = dict(descriptor)
                descriptor.setdefault("code", code)
                descriptor.setdefault("name", code)
                descriptor.setdefault("sequence", 100)
                providers.append(descriptor)
        return sorted(providers, key=lambda item: (item.get("sequence", 100), item["code"]))

    def _optima_pickup_prepare_point(self, provider_code, point, extra=None):
        """Adapter hook: validate provider payload and normalize it.

        The returned mapping must contain at least id, name, street, zip_code,
        city and country_code. Returning False means the provider is unknown.
        """
        self.ensure_one()
        return False

    def _optima_pickup_after_store_point(self, provider_code, normalized, raw_point, extra):
        """Adapter hook executed after the generic pickup snapshot is stored."""
        self.ensure_one()
        return None

    def _optima_pickup_after_clear(self):
        """Adapter hook to clear provider-specific fields."""
        self.ensure_one()
        return None

    def _optima_pickup_selected_point(self):
        self.ensure_one()
        if not self.optima_pickup_external_id:
            return {}
        return {
            "id": self.optima_pickup_external_id,
            "provider_code": self.optima_pickup_provider_code or "",
            "carrier_code": self.optima_pickup_carrier_code or "",
            "carrier_name": self.optima_pickup_carrier_name or "",
            "name": self.optima_pickup_name or "",
            "street": self.optima_pickup_street or "",
            "zip_code": self.optima_pickup_zip or "",
            "city": self.optima_pickup_city or "",
            "country_code": self.optima_pickup_country_code or "",
            "latitude": self.optima_pickup_latitude,
            "longitude": self.optima_pickup_longitude,
        }

    def _optima_pickup_checkout_values(self):
        self.ensure_one()
        providers = self._optima_pickup_get_providers()
        return {
            "optima_pickup_available": bool(providers),
            "optima_pickup_selected": bool(self.optima_pickup_mode and providers),
            "optima_pickup_provider_codes": [provider["code"] for provider in providers],
            "optima_pickup_point": self._optima_pickup_selected_point(),
        }

    def _optima_pickup_clear_selection(self, keep_mode=False):
        self.ensure_one()
        self.write(
            {
                "optima_pickup_mode": bool(keep_mode),
                "optima_pickup_provider_code": False,
                "optima_pickup_external_id": False,
                "optima_pickup_carrier_code": False,
                "optima_pickup_carrier_name": False,
                "optima_pickup_name": False,
                "optima_pickup_street": False,
                "optima_pickup_zip": False,
                "optima_pickup_city": False,
                "optima_pickup_country_code": False,
                "optima_pickup_latitude": 0.0,
                "optima_pickup_longitude": 0.0,
                "optima_pickup_raw_data": False,
                "pickup_location_data": False,
            }
        )
        self._optima_pickup_after_clear()

    def _optima_pickup_store_point(self, provider_code, raw_point, extra=None):
        self.ensure_one()
        extra = extra or {}
        normalized = self._optima_pickup_prepare_point(provider_code, raw_point, extra)
        if not normalized:
            raise ValidationError(_("El proveedor de puntos de recogida no está soportado."))

        required = ("id", "name", "street", "zip_code", "city", "country_code")
        missing = [key for key in required if not normalized.get(key)]
        if missing:
            raise ValidationError(
                _(
                    "El punto de recogida no contiene todos los datos obligatorios: %s",
                    ", ".join(missing),
                )
            )

        # Reutilizamos el formato estándar de Odoo. Al confirmar el pedido,
        # delivery.sale_order sabe convertir pickup_location_data en dirección
        # logística sin que el core tenga que reinventar esa parte.
        pickup_location_data = {
            "id": str(normalized["id"]),
            "name": normalized["name"],
            "street": normalized["street"],
            "zip_code": normalized["zip_code"],
            "city": normalized["city"],
            "country_code": normalized["country_code"],
        }
        if normalized.get("state"):
            pickup_location_data["state"] = normalized["state"]
        pickup_location_data.update(
            {
                "provider_code": provider_code,
                "carrier_code": normalized.get("carrier_code") or "",
                "carrier_name": normalized.get("carrier_name") or "",
                "latitude": normalized.get("latitude") or 0.0,
                "longitude": normalized.get("longitude") or 0.0,
            }
        )

        self.write(
            {
                "optima_pickup_mode": True,
                "optima_pickup_provider_code": provider_code,
                "optima_pickup_external_id": str(normalized["id"]),
                "optima_pickup_carrier_code": normalized.get("carrier_code") or False,
                "optima_pickup_carrier_name": normalized.get("carrier_name") or False,
                "optima_pickup_name": normalized["name"],
                "optima_pickup_street": normalized["street"],
                "optima_pickup_zip": normalized["zip_code"],
                "optima_pickup_city": normalized["city"],
                "optima_pickup_country_code": normalized["country_code"],
                "optima_pickup_latitude": normalized.get("latitude") or 0.0,
                "optima_pickup_longitude": normalized.get("longitude") or 0.0,
                "optima_pickup_raw_data": raw_point,
                "pickup_location_data": pickup_location_data,
            }
        )
        self._optima_pickup_after_store_point(provider_code, normalized, raw_point, extra)
        return self._optima_pickup_selected_point()
