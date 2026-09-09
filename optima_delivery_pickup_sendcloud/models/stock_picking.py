import json

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    optima_sendcloud_service_point_payload_snapshot = fields.Text(
        string="Datos Sendcloud del punto",
        copy=True,
        readonly=True,
    )
    optima_sendcloud_post_number_snapshot = fields.Char(
        string="Sendcloud Post Number",
        copy=True,
        readonly=True,
    )
    optima_sendcloud_service_point_synced = fields.Boolean(
        string="Datos Sendcloud preparados",
        copy=True,
        readonly=True,
    )

    @staticmethod
    def _optima_sendcloud_json_payload(value):
        """Return (dict, json_text) for a sale-order Sendcloud payload."""
        if isinstance(value, dict):
            payload = value
            return payload, json.dumps(payload)
        if isinstance(value, str) and value.strip():
            try:
                payload = json.loads(value)
            except (TypeError, ValueError):
                return {}, value
            return payload if isinstance(payload, dict) else {}, value
        return {}, ""

    @staticmethod
    def _optima_sendcloud_field_is_writable(field):
        # A stored/plain field is safe to set. A computed/related field without
        # inverse is intentionally left to the OCA connector itself.
        return not field.compute or bool(field.inverse)

    def _optima_sendcloud_write_oca_field(self, vals, name, payload, payload_text):
        """Populate known OCA-compatible service-point fields when present.

        delivery_sendcloud_oca has evolved between series. We do not redefine
        any of its fields; instead we only synchronize a field if that exact
        field exists and is writable in the installed version.
        """
        field = self._fields.get(name)
        if not field or not self._optima_sendcloud_field_is_writable(field):
            return
        if field.type == "json":
            vals[name] = payload
        elif field.type in ("char", "text"):
            vals[name] = payload_text

    def _optima_sendcloud_sync_service_point_from_sale(self):
        """Copy the website-selected Sendcloud point into the outgoing picking."""
        self.ensure_one()
        sale = self.sale_id
        if not sale or self.optima_delivery_pickup_provider_code != "sendcloud":
            return False

        source = False
        if "sendcloud_service_point_address" in sale._fields:
            source = sale.sendcloud_service_point_address
        payload, payload_text = self._optima_sendcloud_json_payload(source)

        # Fallback to the provider raw snapshot. This should normally not be
        # needed because the website adapter already keeps the OCA sale field
        # synchronized, but it makes the shipping bridge self-healing.
        if not payload_text:
            raw = sale.optima_pickup_raw_data or {}
            if isinstance(raw, dict):
                payload = dict(raw)
                payload_text = json.dumps(payload)

        if not payload_text:
            self.write({
                "optima_sendcloud_service_point_payload_snapshot": False,
                "optima_sendcloud_post_number_snapshot": False,
                "optima_sendcloud_service_point_synced": False,
            })
            return False

        point_id = str(
            payload.get("id")
            or payload.get("service_point_id")
            or sale.optima_pickup_external_id
            or ""
        )
        expected_id = str(sale.optima_pickup_external_id or "")
        if expected_id and point_id and expected_id != point_id:
            raise ValidationError(_(
                "Los datos Sendcloud del albarán no corresponden al punto de recogida confirmado."
            ))

        post_number = str(
            payload.get("post_number")
            or sale.optima_sendcloud_to_post_number
            or ""
        )
        if post_number and isinstance(payload, dict) and not payload.get("post_number"):
            payload = dict(payload)
            payload["post_number"] = post_number
            payload_text = json.dumps(payload)

        vals = {
            "optima_sendcloud_service_point_payload_snapshot": payload_text,
            "optima_sendcloud_post_number_snapshot": post_number or False,
            "optima_sendcloud_service_point_synced": True,
        }

        # The common OCA field name is synchronized if the installed 18.0
        # connector exposes it on stock.picking. Compatible forks using a JSON
        # variant are supported as well.
        self._optima_sendcloud_write_oca_field(
            vals,
            "sendcloud_service_point_address",
            payload,
            payload_text,
        )
        self._optima_sendcloud_write_oca_field(
            vals,
            "sendcloud_service_point_data",
            payload,
            payload_text,
        )

        # Some connector revisions expose primitive service-point/post-number
        # fields instead of a single payload. Only write type-compatible fields.
        id_field = self._fields.get("sendcloud_service_point_id")
        if id_field and self._optima_sendcloud_field_is_writable(id_field) and point_id:
            if id_field.type in ("char", "text"):
                vals["sendcloud_service_point_id"] = point_id
            elif id_field.type == "integer" and point_id.isdigit():
                vals["sendcloud_service_point_id"] = int(point_id)

        for field_name in ("sendcloud_to_post_number", "sendcloud_post_number"):
            field = self._fields.get(field_name)
            if (
                field
                and self._optima_sendcloud_field_is_writable(field)
                and field.type in ("char", "text")
            ):
                vals[field_name] = post_number or False

        self.write(vals)
        return True

    def _optima_delivery_provider_preflight(self):
        self.ensure_one()
        result = super()._optima_delivery_provider_preflight()
        if self.optima_delivery_pickup_provider_code != "sendcloud":
            return result
        if not self.carrier_id or self.carrier_id.delivery_type != "sendcloud":
            raise ValidationError(_(
                "El punto confirmado es Sendcloud pero el albarán no usa un método Sendcloud."
            ))
        if not self.sale_id:
            raise ValidationError(_(
                "No se puede recuperar el pedido de venta para preparar el punto Sendcloud."
            ))
        if not self._optima_sendcloud_sync_service_point_from_sale():
            raise ValidationError(_(
                "Faltan los datos Sendcloud del punto de recogida. No se enviará el albarán al transportista."
            ))
        return result
