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
        """Prepare OCA fields from the immutable confirmed Sendcloud snapshot.

        At order confirmation the snapshot does not exist yet, so it is created
        once from the sale order. On later ``send_to_shipper`` preflights the
        already-confirmed picking snapshot is authoritative and is never replaced
        from mutable sale-order fields.
        """
        self.ensure_one()
        sale = self.sale_id
        if not sale or self.optima_delivery_pickup_provider_code != "sendcloud":
            return False

        snapshot_text = self.optima_sendcloud_service_point_payload_snapshot or ""
        snapshot_payload, parsed_snapshot_text = self._optima_sendcloud_json_payload(
            snapshot_text
        )
        using_confirmed_snapshot = bool(
            self.optima_sendcloud_service_point_synced and snapshot_text
        )

        if using_confirmed_snapshot:
            if not snapshot_payload:
                raise ValidationError(_(
                    "El snapshot Sendcloud confirmado del albarán no contiene datos válidos."
                ))
            payload = dict(snapshot_payload)
            payload_text = parsed_snapshot_text
        else:
            source = False
            if "sendcloud_service_point_address" in sale._fields:
                source = sale.sendcloud_service_point_address
            payload, payload_text = self._optima_sendcloud_json_payload(source)

            # Backfill for pickings created before the provider snapshot existed.
            if not payload:
                raw = sale.optima_pickup_raw_data or {}
                if isinstance(raw, dict):
                    payload = dict(raw)
                    payload_text = json.dumps(payload)

        if not payload or not payload_text:
            if not using_confirmed_snapshot:
                self.write({
                    "optima_sendcloud_service_point_payload_snapshot": False,
                    "optima_sendcloud_post_number_snapshot": False,
                    "optima_sendcloud_service_point_synced": False,
                })
            return False

        point_id = str(
            payload.get("id")
            or payload.get("service_point_id")
            or ""
        )
        expected_id = str(self.optima_delivery_pickup_external_id or "")
        if not expected_id and not using_confirmed_snapshot:
            expected_id = str(sale.optima_pickup_external_id or "")
        if not point_id or (expected_id and expected_id != point_id):
            raise ValidationError(_(
                "Los datos Sendcloud del albarán no corresponden al punto de recogida confirmado."
            ))

        # When backfilling from the sale order, ensure the mutable sale record
        # still refers to the same point captured by the generic picking snapshot.
        if not using_confirmed_snapshot:
            sale_point_id = str(sale.optima_pickup_external_id or "")
            if expected_id and sale_point_id and sale_point_id != expected_id:
                raise ValidationError(_(
                    "El punto Sendcloud del pedido cambió después de confirmar el albarán."
                ))

        # The provider payload and the generic picking snapshot are two
        # independent immutable views of the same confirmed point. Require them
        # to agree before exposing the data to the carrier connector. This also
        # catches coordinated edits to the picking destination + generic fields.
        raw_country = payload.get("country") or payload.get("country_code") or ""
        if isinstance(raw_country, dict):
            raw_country = raw_country.get("iso_2") or raw_country.get("code") or ""
        payload_street = " ".join(
            str(value).strip()
            for value in (payload.get("street"), payload.get("house_number"))
            if value not in (None, "")
        )
        snapshot_checks = (
            (payload_street, self.optima_delivery_pickup_street),
            (payload.get("postal_code") or payload.get("zip_code"), self.optima_delivery_pickup_zip),
            (payload.get("city"), self.optima_delivery_pickup_city),
            (raw_country, self.optima_delivery_pickup_country_code),
            (payload.get("carrier") or payload.get("carrier_code"), self.optima_delivery_pickup_carrier_code),
        )
        for actual, expected in snapshot_checks:
            if expected and self._optima_normalized_text(actual) != self._optima_normalized_text(expected):
                raise ValidationError(_(
                    "El snapshot Sendcloud del albarán ya no coincide con el punto de recogida confirmado."
                ))

        post_number = str(
            payload.get("post_number")
            or (self.optima_sendcloud_post_number_snapshot if using_confirmed_snapshot else False)
            or (sale.optima_sendcloud_to_post_number if not using_confirmed_snapshot else False)
            or ""
        )
        if post_number and not payload.get("post_number"):
            payload = dict(payload)
            payload["post_number"] = post_number
            payload_text = json.dumps(payload)

        vals = {
            "optima_sendcloud_service_point_payload_snapshot": payload_text,
            "optima_sendcloud_post_number_snapshot": post_number or False,
            "optima_sendcloud_service_point_synced": True,
        }

        # Re-apply the immutable snapshot to the fields consumed by the installed
        # OCA connector. This self-heals accidental edits on connector fields
        # without ever consulting mutable sale-order point data again.
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

        id_field = self._fields.get("sendcloud_service_point_id")
        if id_field and self._optima_sendcloud_field_is_writable(id_field):
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
