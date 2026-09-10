from collections import defaultdict
import hashlib
import json
import logging
from math import ceil

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..utils.package import estimate_single_package


_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Resumen genérico de expedición. Estos campos no dependen de pickup y
    # permanecen visibles en cualquier presupuesto/pedido. Los límites se
    # guardan como snapshot del método que los proporcionó para que un pedido
    # confirmado conserve la referencia operativa usada al resolverlo.
    optima_delivery_method_id = fields.Many2one(
        "delivery.carrier",
        string="Método de entrega seleccionado",
        related="carrier_id",
        readonly=True,
    )
    optima_delivery_method_limits_carrier_id = fields.Many2one(
        "delivery.carrier",
        string="Método asociado al snapshot de límites",
        copy=False,
        readonly=True,
        ondelete="set null",
    )
    optima_delivery_method_limits_snapshot = fields.Json(
        string="Snapshot de límites del método",
        copy=False,
        readonly=True,
    )
    optima_delivery_method_limits = fields.Text(
        string="Límites del método seleccionado",
        compute="_compute_optima_delivery_method_limits",
    )
    optima_delivery_packaging_suggested = fields.Char(
        string="Embalaje sugerido",
        compute="_compute_optima_pickup_logistics",
    )

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

    # Resultado genérico de la resolución del método de entrega. El core no
    # sabe cómo calcularlo; cada adaptador implementa el hook correspondiente.
    optima_pickup_resolved = fields.Boolean(
        string="Pickup resuelto",
        copy=False,
    )
    optima_pickup_delivery_carrier_id = fields.Many2one(
        "delivery.carrier",
        string="Método de entrega pickup",
        copy=False,
        ondelete="set null",
    )
    optima_pickup_delivery_price = fields.Monetary(
        string="Precio pickup",
        currency_field="currency_id",
        copy=False,
    )
    optima_pickup_resolution_message = fields.Char(
        string="Diagnóstico pickup",
        copy=False,
    )
    optima_pickup_resolved_logistics_fingerprint = fields.Char(
        string="Huella logística validada",
        copy=False,
        readonly=True,
    )
    optima_pickup_resolved_address_fingerprint = fields.Char(
        string="Huella de dirección validada",
        copy=False,
        readonly=True,
    )

    # Snapshot calculado de la logística del carrito. Se mantiene genérico y
    # no depende de Sendcloud: los adaptadores reciben este perfil y deciden
    # si un servicio concreto lo acepta. V1 siempre representa un único bulto.
    optima_pickup_logistics_ready = fields.Boolean(
        string="Datos logísticos completos",
        compute="_compute_optima_pickup_logistics",
    )
    optima_pickup_package_weight_kg = fields.Float(
        string="Peso estimado del bulto",
        compute="_compute_optima_pickup_logistics",
        digits=(16, 3),
    )
    optima_pickup_package_length_mm = fields.Float(
        string="Lado mayor estimado",
        compute="_compute_optima_pickup_logistics",
        digits=(16, 2),
    )
    optima_pickup_package_width_mm = fields.Float(
        string="Segundo lado estimado",
        compute="_compute_optima_pickup_logistics",
        digits=(16, 2),
    )
    optima_pickup_package_height_mm = fields.Float(
        string="Tercer lado estimado",
        compute="_compute_optima_pickup_logistics",
        digits=(16, 2),
    )
    optima_pickup_package_unit_count = fields.Integer(
        string="Unidades físicas estimadas",
        compute="_compute_optima_pickup_logistics",
    )
    optima_pickup_package_strategy = fields.Char(
        string="Estrategia de embalaje",
        compute="_compute_optima_pickup_logistics",
    )
    optima_pickup_logistics_message = fields.Char(
        string="Diagnóstico logístico",
        compute="_compute_optima_pickup_logistics",
    )

    @staticmethod
    def _optima_delivery_format_number(value, decimals=0):
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            number = 0.0
        if decimals:
            text = (f"{number:.{decimals}f}").rstrip("0").rstrip(".")
            return text or "0"
        return str(int(round(number)))

    @api.depends(
        "carrier_id",
        "optima_delivery_method_limits_carrier_id",
        "optima_delivery_method_limits_snapshot",
    )
    def _compute_optima_delivery_method_limits(self):
        for order in self:
            carrier = order.carrier_id
            snapshot = order.optima_delivery_method_limits_snapshot or {}
            snapshot_carrier = order.optima_delivery_method_limits_carrier_id

            if not carrier:
                order.optima_delivery_method_limits = _(
                    "Sin método de entrega seleccionado."
                )
                continue
            if not snapshot or snapshot_carrier != carrier:
                order.optima_delivery_method_limits = _(
                    "No hay límites registrados por el conector para este método."
                )
                continue

            def snapshot_number(name):
                try:
                    return max(float(snapshot.get(name) or 0.0), 0.0)
                except (TypeError, ValueError):
                    return 0.0

            parts = []
            min_weight = snapshot_number("min_weight_kg")
            max_weight = snapshot_number("max_weight_kg")
            max_length = snapshot_number("max_length_mm")
            max_width = snapshot_number("max_width_mm")
            max_height = snapshot_number("max_height_mm")

            if max_length > 0 and max_width > 0 and max_height > 0:
                parts.append(
                    _("Máx. %(l)s × %(w)s × %(h)s mm")
                    % {
                        "l": order._optima_delivery_format_number(max_length),
                        "w": order._optima_delivery_format_number(max_width),
                        "h": order._optima_delivery_format_number(max_height),
                    }
                )
            if max_weight > 0:
                parts.append(
                    _("peso máx. %(weight)s kg")
                    % {
                        "weight": order._optima_delivery_format_number(max_weight, 3)
                    }
                )
            if min_weight > 0:
                parts.append(
                    _("peso mín. %(weight)s kg")
                    % {
                        "weight": order._optima_delivery_format_number(min_weight, 3)
                    }
                )

            order.optima_delivery_method_limits = (
                " · ".join(parts)
                if parts
                else _(
                    "El conector ha validado el método, pero no ha informado límites numéricos."
                )
            )

    @api.depends(
        "order_line.product_id",
        "order_line.product_uom",
        "order_line.product_uom_qty",
        "order_line.is_delivery",
        "order_line.product_id.weight",
        "order_line.product_id.shipping_length_mm",
        "order_line.product_id.shipping_width_mm",
        "order_line.product_id.shipping_height_mm",
    )
    def _compute_optima_pickup_logistics(self):
        for order in self:
            profile = order._optima_pickup_package_profile()
            order.optima_pickup_logistics_ready = profile["success"]
            order.optima_pickup_package_weight_kg = profile["weight_kg"]
            order.optima_pickup_package_length_mm = profile["length_mm"]
            order.optima_pickup_package_width_mm = profile["width_mm"]
            order.optima_pickup_package_height_mm = profile["height_mm"]
            order.optima_pickup_package_unit_count = profile["unit_count"]
            order.optima_pickup_package_strategy = profile.get("packing_description") or False
            order.optima_pickup_logistics_message = profile["message"] or False
            if profile["success"]:
                order.optima_delivery_packaging_suggested = (
                    _("%(l)s × %(w)s × %(h)s mm · %(weight)s kg · %(units)s ud.")
                    % {
                        "l": order._optima_delivery_format_number(profile["length_mm"]),
                        "w": order._optima_delivery_format_number(profile["width_mm"]),
                        "h": order._optima_delivery_format_number(profile["height_mm"]),
                        "weight": order._optima_delivery_format_number(profile["weight_kg"], 3),
                        "units": profile["unit_count"],
                    }
                )
            else:
                order.optima_delivery_packaging_suggested = _(
                    "No disponible: %s"
                ) % (profile["message"] or _("datos logísticos incompletos"))

    def _optima_pickup_physical_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: not line.is_delivery
            and line.product_id
            and line.product_uom_qty > 0
            and getattr(line.product_id, "type", False) != "service"
        )

    def _optima_pickup_line_base_quantity(self, line):
        """Quantity expressed in the product's base UoM.

        Dimensions are defined for one base unit of the product. Converting
        first avoids silently treating e.g. a dozen as one physical item.
        """
        qty = max(float(line.product_uom_qty or 0.0), 0.0)
        if not qty or not line.product_id:
            return 0.0
        try:
            if line.product_uom and line.product_id.uom_id:
                qty = line.product_uom._compute_quantity(qty, line.product_id.uom_id)
        except Exception:
            # A malformed/custom UoM must not crash checkout. Keep the sale
            # quantity and fail conservatively later if data are inconsistent.
            pass
        return max(float(qty or 0.0), 0.0)

    @staticmethod
    def _optima_pickup_product_label(product):
        return product.display_name or product.name or str(product.id)

    def _optima_pickup_package_profile(self):
        """Build a conservative one-parcel profile from the current order.

        Weight uses the exact converted quantity. Dimensions use ``ceil`` of
        that quantity so a fractional quantity can never make a physical unit
        artificially smaller. Volume is deliberately not used.
        """
        self.ensure_one()
        lines = self._optima_pickup_physical_lines()
        if not lines:
            return {
                "success": False,
                "weight_kg": 0.0,
                "length_mm": 0.0,
                "width_mm": 0.0,
                "height_mm": 0.0,
                "unit_count": 0,
                "missing_weight": [],
                "missing_dimensions": [],
                "message": _("El pedido no contiene productos físicos que se puedan enviar a un punto de recogida."),
            }

        missing_weight = []
        missing_dimensions = []
        weight_kg = 0.0
        items = []

        for line in lines:
            product = line.product_id
            qty = self._optima_pickup_line_base_quantity(line)
            if qty <= 0:
                continue
            label = self._optima_pickup_product_label(product)

            unit_weight = float(product.weight or 0.0)
            if unit_weight <= 0:
                missing_weight.append(label)
            else:
                weight_kg += unit_weight * qty

            dims = (
                float(product.shipping_length_mm or 0.0),
                float(product.shipping_width_mm or 0.0),
                float(product.shipping_height_mm or 0.0),
            )
            if min(dims) <= 0:
                missing_dimensions.append(label)
            else:
                items.append(
                    {
                        "length_mm": dims[0],
                        "width_mm": dims[1],
                        "height_mm": dims[2],
                        "quantity": int(ceil(qty)),
                        "group_key": product.id,
                    }
                )

        def short_list(values):
            values = list(dict.fromkeys(values))
            if len(values) <= 3:
                return ", ".join(values)
            return ", ".join(values[:3]) + (_(" y %s más") % (len(values) - 3))

        problems = []
        if missing_weight:
            problems.append(_("falta peso en: %s") % short_list(missing_weight))
        if missing_dimensions:
            problems.append(_("faltan dimensiones en: %s") % short_list(missing_dimensions))
        if problems:
            return {
                "success": False,
                "weight_kg": max(weight_kg, 0.0),
                "length_mm": 0.0,
                "width_mm": 0.0,
                "height_mm": 0.0,
                "unit_count": sum(int(ceil(self._optima_pickup_line_base_quantity(line))) for line in lines),
                "missing_weight": missing_weight,
                "missing_dimensions": missing_dimensions,
                "message": _("No se puede validar el punto de recogida porque %s.") % "; ".join(problems),
            }

        try:
            package = estimate_single_package(items)
        except (TypeError, ValueError):
            return {
                "success": False,
                "weight_kg": max(weight_kg, 0.0),
                "length_mm": 0.0,
                "width_mm": 0.0,
                "height_mm": 0.0,
                "unit_count": 0,
                "missing_weight": [],
                "missing_dimensions": [],
                "message": _("No se han podido calcular de forma segura las dimensiones del bulto."),
            }

        if weight_kg <= 0 or not package["unit_count"]:
            return {
                "success": False,
                "weight_kg": max(weight_kg, 0.0),
                "length_mm": package["length_mm"],
                "width_mm": package["width_mm"],
                "height_mm": package["height_mm"],
                "unit_count": package["unit_count"],
                "missing_weight": [],
                "missing_dimensions": [],
                "message": _("El peso o la cantidad física calculada para el pedido no son válidos."),
            }

        if package.get("strategy") == "identical_grid":
            grid = package.get("grid") or (1, 1, package["unit_count"])
            packing_description = _(
                "Producto homogéneo: optimización exacta de filas/capas %s × %s × %s"
            ) % (grid[0], grid[1], grid[2])
        elif package.get("strategy") == "mixed_conservative":
            packing_description = _(
                "Carrito mixto: agrupación conservadora de %s bloques de producto"
            ) % package.get("group_count", 0)
        else:
            packing_description = False

        return {
            "success": True,
            "weight_kg": weight_kg,
            "length_mm": package["length_mm"],
            "width_mm": package["width_mm"],
            "height_mm": package["height_mm"],
            "unit_count": package["unit_count"],
            "packing_strategy": package.get("strategy"),
            "packing_description": packing_description,
            "missing_weight": [],
            "missing_dimensions": [],
            "message": False,
        }

    def _optima_pickup_validate_package(self, provider_code=False, point=False):
        """Generic pre-provider validation hook.

        Adapters may extend this method, but every provider starts from a
        complete one-parcel profile. Keeping this in the core makes the same
        product/UoM rules reusable by Sendcloud, UPS, GLS, etc.
        """
        self.ensure_one()
        profile = self._optima_pickup_package_profile()
        return {
            "success": bool(profile["success"]),
            "message": profile["message"] or False,
            "package": profile,
        }


    @staticmethod
    def _optima_pickup_hash_payload(payload):
        encoded = json.dumps(
            payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _optima_pickup_logistics_fingerprint(self, profile=None):
        """Stable signature of the physical parcel relevant to carrier checks.

        We intentionally fingerprint the resulting parcel rather than sale prices:
        pickup compatibility/rating in the current architecture depends on weight,
        dimensions and physical-unit count. A delivery line is excluded by the
        package profile itself.
        """
        self.ensure_one()
        profile = profile or self._optima_pickup_package_profile()
        payload = {
            "success": bool(profile.get("success")),
            "weight_kg": round(float(profile.get("weight_kg") or 0.0), 6),
            "length_mm": round(float(profile.get("length_mm") or 0.0), 3),
            "width_mm": round(float(profile.get("width_mm") or 0.0), 3),
            "height_mm": round(float(profile.get("height_mm") or 0.0), 3),
            "unit_count": int(profile.get("unit_count") or 0),
            "missing_weight": sorted(profile.get("missing_weight") or []),
            "missing_dimensions": sorted(profile.get("missing_dimensions") or []),
        }
        return self._optima_pickup_hash_payload(payload)

    def _optima_pickup_address_fingerprint(self):
        """Stable signature of the delivery destination used to choose a point.

        This catches both switching to another delivery partner and editing the
        current partner in-place (same partner id, different street/zip/city).
        """
        self.ensure_one()
        partner = self.partner_shipping_id or self.partner_id
        if not partner:
            return self._optima_pickup_hash_payload({"partner": False})

        def clean(value):
            return " ".join(str(value or "").strip().lower().split())

        payload = {
            "partner_id": partner.id,
            "street": clean(partner.street),
            "street2": clean(partner.street2),
            "zip": clean(partner.zip),
            "city": clean(partner.city),
            "state": clean(partner.state_id.code or partner.state_id.name),
            "country": clean(partner.country_id.code),
        }
        return self._optima_pickup_hash_payload(payload)

    def _optima_pickup_invalidate_for_address_change(self):
        """Discard a pickup point chosen for a different delivery address."""
        self.ensure_one()
        if not self.optima_pickup_mode:
            return
        self.with_context(keep_pickup_location=True)._remove_delivery_line()
        self.write({"carrier_id": False})
        self._optima_pickup_clear_selection(keep_mode=True)
        self.write({
            "optima_pickup_resolution_message": _(
                "La dirección de entrega ha cambiado. Selecciona de nuevo un punto de recogida."
            ),
        })

    def _optima_pickup_revalidate_stored_point(self):
        """Re-run package/provider validation without breaking cart edits.

        A transient provider failure may invalidate the delivery price, but it
        must never prevent the customer from changing products or quantities.
        The selected point remains visible so the customer understands what must
        be revalidated/reselected.
        """
        self.ensure_one()
        if not (self.optima_pickup_mode and self.optima_pickup_external_id):
            return self._optima_pickup_resolution_payload()
        try:
            return self._optima_pickup_resolve_stored_point()
        except Exception as exc:  # pragma: no cover - last-resort checkout safety
            _logger.exception(
                "Optima pickup: unexpected error revalidating sale order %s", self.id
            )
            self._optima_pickup_clear_resolution(remove_delivery_line=True)
            self.write({
                "optima_pickup_resolution_message": _(
                    "El carrito ha cambiado y no se ha podido revalidar el punto de recogida. "
                    "Vuelve a seleccionar el punto o inténtalo de nuevo."
                ),
            })
            return self._optima_pickup_resolution_payload()

    def _optima_pickup_ensure_current_state(self):
        """Fail-safe for changes that bypass normal website hooks.

        Standard website cart updates and address updates are handled eagerly
        below. This guard protects checkout/payment against custom modules or
        direct writes that changed the cart/address without using those hooks.
        """
        self.ensure_one()
        if not (
            self.optima_pickup_mode
            and self.optima_pickup_external_id
            and self.optima_pickup_resolved
        ):
            return

        current_address = self._optima_pickup_address_fingerprint()
        validated_address = self.optima_pickup_resolved_address_fingerprint or ""
        if validated_address and validated_address != current_address:
            self._optima_pickup_invalidate_for_address_change()
            return

        current_logistics = self._optima_pickup_logistics_fingerprint()
        validated_logistics = self.optima_pickup_resolved_logistics_fingerprint or ""
        # Missing fingerprints are expected on orders resolved by pre-Phase-3
        # versions: revalidate them once rather than trusting stale data.
        if (
            not validated_address
            or not validated_logistics
            or validated_logistics != current_logistics
        ):
            self._optima_pickup_revalidate_stored_point()

    def _update_address(self, partner_id, fnames=None):
        """A pickup point is tied to the address from which it was searched.

        Odoo calls this method both when switching delivery addresses and after
        editing the current address in-place. Clear the old point *before* the
        native carrier refresh so website_sale cannot silently keep/reselect the
        technical pickup carrier for the new destination.
        """
        shipping_changed = bool(
            fnames
            and "partner_shipping_id" in fnames
            and self.optima_pickup_mode
            and self.optima_pickup_external_id
        )
        if shipping_changed:
            self._optima_pickup_invalidate_for_address_change()
        return super()._update_address(partner_id, fnames)

    def _cart_update(self, product_id, line_id=None, add_qty=0, set_qty=0, **kwargs):
        """Automatically revalidate pickup after a physical cart change.

        Phase 3 keeps the customer's selected point when products/quantities
        change, but recalculates package compatibility and price. If the same
        point is no longer valid, it remains visible as unresolved and checkout
        confirmation stays blocked. Emptying the cart still clears pickup fully.
        """
        self.ensure_one()
        had_selected_point = bool(
            self.optima_pickup_mode and self.optima_pickup_external_id
        )
        before_signature = (
            self._optima_pickup_logistics_fingerprint() if had_selected_point else False
        )

        result = super()._cart_update(
            product_id, line_id=line_id, add_qty=add_qty, set_qty=set_qty, **kwargs
        )

        if self.optima_pickup_mode and not self._has_deliverable_products():
            self.with_context(keep_pickup_location=True)._remove_delivery_line()
            self.write({"carrier_id": False})
            self._optima_pickup_clear_selection(keep_mode=False)
            return result

        if had_selected_point and self.optima_pickup_mode and self.optima_pickup_external_id:
            after_signature = self._optima_pickup_logistics_fingerprint()
            if before_signature != after_signature:
                self._optima_pickup_revalidate_stored_point()
        return result

    def _get_preferred_delivery_method(self, available_delivery_methods):
        """Keep pickup ownership of the checkout while selected or resolving.

        Once pickup mode is active Odoo must not silently fall back to the first
        standard website carrier while the point is being resolved.  A resolved
        pickup keeps its concrete carrier; a pending pickup intentionally
        returns an empty carrier recordset so no standard method is auto-picked.
        """
        self.ensure_one()
        if self.optima_pickup_mode:
            if self.optima_pickup_resolved and self.optima_pickup_delivery_carrier_id:
                return self.optima_pickup_delivery_carrier_id
            return self.env["delivery.carrier"]
        return super()._get_preferred_delivery_method(available_delivery_methods)

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

    def _optima_pickup_default_search_query(self):
        """Return a human-friendly destination query for provider searches."""
        self.ensure_one()
        partner = self.partner_shipping_id or self.partner_id
        parts = [
            (partner.street or "").strip(),
            " ".join(part for part in ((partner.zip or "").strip(), (partner.city or "").strip()) if part),
        ]
        return ", ".join(part for part in parts if part)

    def _optima_pickup_search_points(self, provider_codes=None, query=None, radius_m=5000):
        """Generic multi-provider point discovery hook.

        Every adapter extends this method, calls ``super()`` and appends its
        normalized public point dictionaries.  The core therefore owns one
        frontend map while provider credentials and API details stay entirely
        server-side.
        """
        self.ensure_one()
        return {"points": [], "errors": []}

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

    def _optima_pickup_resolve_delivery(self, provider_code, normalized, raw_point, extra):
        """Adapter hook: resolve point -> concrete delivery carrier + price.

        Expected success payload::

            {
                "success": True,
                "carrier": delivery.carrier record,
                "price": 4.95,
                "message": "optional diagnostic/warning",
                "method_limits": {
                    "provider": "provider_code",
                    "min_weight_kg": 0.0,
                    "max_weight_kg": 10.0,
                    "max_length_mm": 600.0,
                    "max_width_mm": 400.0,
                    "max_height_mm": 300.0,
                },
            }

        The default implementation deliberately leaves the selection pending.
        """
        self.ensure_one()
        return {
            "success": False,
            "message": _("El proveedor todavía no implementa el cálculo del método de entrega."),
        }

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

    def _optima_pickup_resolution_payload(self):
        self.ensure_one()
        carrier = self.optima_pickup_delivery_carrier_id
        return {
            "success": bool(self.optima_pickup_resolved and carrier),
            "carrier_id": carrier.id or False,
            "carrier_name": carrier.display_name if carrier else "",
            "price": self.optima_pickup_delivery_price or 0.0,
            "currency": self.currency_id.name or "EUR",
            "message": self.optima_pickup_resolution_message or "",
        }

    def _optima_pickup_force_visible(self):
        """Development hook: keep the generic pickup option visible.

        Intentionally True for the current development phase. Eligibility by
        destination, weight and dimensions will be added later without changing
        the provider/checkout architecture.
        """
        self.ensure_one()
        return True

    def _optima_pickup_checkout_values(self):
        self.ensure_one()
        self._optima_pickup_ensure_current_state()
        providers = self._optima_pickup_get_providers()
        resolution = self._optima_pickup_resolution_payload()
        return {
            "optima_pickup_available": bool(providers) or self._optima_pickup_force_visible(),
            "optima_pickup_selected": bool(self.optima_pickup_mode),
            "optima_pickup_provider_codes": [provider["code"] for provider in providers],
            "optima_pickup_point": self._optima_pickup_selected_point(),
            "optima_pickup_resolved": resolution["success"],
            "optima_pickup_price": resolution["price"],
            "optima_pickup_currency": resolution["currency"],
            "optima_pickup_delivery_carrier_name": resolution["carrier_name"],
            "optima_pickup_resolution_message": resolution["message"],
        }

    def _optima_pickup_clear_resolution(self, remove_delivery_line=False):
        self.ensure_one()
        if remove_delivery_line:
            # Clearing only the carrier/rate must never erase the point itself.
            # website_sale._remove_delivery_line() normally clears
            # pickup_location_data unless this context flag is present.
            self.with_context(keep_pickup_location=True)._remove_delivery_line()
            self.write({"carrier_id": False})
        self.write(
            {
                "optima_pickup_resolved": False,
                "optima_pickup_delivery_carrier_id": False,
                "optima_pickup_delivery_price": 0.0,
                "optima_pickup_resolution_message": False,
                "optima_delivery_method_limits_carrier_id": False,
                "optima_delivery_method_limits_snapshot": False,
                "optima_pickup_resolved_logistics_fingerprint": False,
                "optima_pickup_resolved_address_fingerprint": False,
            }
        )

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
                "optima_pickup_resolved": False,
                "optima_pickup_delivery_carrier_id": False,
                "optima_pickup_delivery_price": 0.0,
                "optima_pickup_resolution_message": False,
                "optima_delivery_method_limits_carrier_id": False,
                "optima_delivery_method_limits_snapshot": False,
                "optima_pickup_resolved_logistics_fingerprint": False,
                "optima_pickup_resolved_address_fingerprint": False,
            }
        )
        self._optima_pickup_after_clear()

    def _optima_pickup_apply_resolution(self, provider_code, normalized, raw_point, extra):
        """Resolve first, mutate the delivery line only after a valid result.

        The previous implementation removed the current delivery line before
        package/provider validation.  If the new point could not be resolved,
        checkout was left halfway through the transition and the order summary
        could temporarily lose its shipping line.  By validating and rating
        first, unexpected failures roll back cleanly and a successful change is
        applied atomically.
        """
        self.ensure_one()

        def fail(message):
            self._optima_pickup_clear_resolution(remove_delivery_line=True)
            self.write({"optima_pickup_resolution_message": message})
            return self._optima_pickup_resolution_payload()

        validation = self._optima_pickup_validate_package(
            provider_code=provider_code, point=normalized
        ) or {}
        if not validation.get("success"):
            return fail(
                validation.get("message")
                or _("El pedido no cumple los requisitos logísticos del punto de recogida.")
            )

        # Provider validation can attach server-side data (for example the
        # Sendcloud method ids that passed weight/dimension checks). Keep that
        # data out of the browser payload and pass it only to the resolver.
        resolve_extra = dict(extra or {})
        resolve_extra["_optima_package_validation"] = validation
        resolution = self._optima_pickup_resolve_delivery(
            provider_code, normalized, raw_point, resolve_extra
        ) or {}
        if not resolution.get("success"):
            return fail(
                resolution.get("message")
                or _("No se ha podido calcular un método de entrega para este punto.")
            )

        carrier = resolution.get("carrier")
        if not carrier or carrier._name != "delivery.carrier" or len(carrier) != 1:
            return fail(_("El proveedor devolvió un método de entrega no válido."))

        try:
            price = float(resolution.get("price", 0.0))
        except (TypeError, ValueError):
            price = -1.0
        if price < 0:
            return fail(_("El proveedor devolvió un precio de entrega no válido."))

        # Only now replace the old delivery line.  If anything above raises an
        # unexpected exception, the request transaction rolls back without
        # destroying a previously valid checkout state.
        self._optima_pickup_clear_resolution(remove_delivery_line=True)
        self.with_context(keep_pickup_location=True).set_delivery_line(carrier, price)
        method_limits = resolution.get("method_limits")
        if not isinstance(method_limits, dict):
            method_limits = {}
        self.write(
            {
                "carrier_id": carrier.id,
                "optima_pickup_resolved": True,
                "optima_pickup_delivery_carrier_id": carrier.id,
                "optima_pickup_delivery_price": price,
                "optima_pickup_resolution_message": resolution.get("message") or False,
                "optima_delivery_method_limits_carrier_id": (
                    carrier.id if method_limits else False
                ),
                "optima_delivery_method_limits_snapshot": method_limits or False,
                "optima_pickup_resolved_logistics_fingerprint": self._optima_pickup_logistics_fingerprint(),
                "optima_pickup_resolved_address_fingerprint": self._optima_pickup_address_fingerprint(),
            }
        )
        return self._optima_pickup_resolution_payload()

    def _optima_pickup_store_point(self, provider_code, raw_point, extra=None, resolve=True):
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
        if resolve:
            resolution = self._optima_pickup_apply_resolution(
                provider_code, normalized, raw_point, extra
            )
        else:
            resolution = self._optima_pickup_resolution_payload()
        return {
            "point": self._optima_pickup_selected_point(),
            "resolution": resolution,
        }

    def _optima_pickup_resolve_stored_point(self):
        """Resolve the point already persisted on the order.

        This separates the fast 'store selection' step from the potentially
        slower carrier API validation/rating step used by website checkout.
        """
        self.ensure_one()
        if not self.optima_pickup_mode or not self.optima_pickup_external_id:
            self._optima_pickup_clear_resolution(remove_delivery_line=True)
            self.write({
                "optima_pickup_resolution_message": _("No hay un punto de recogida seleccionado."),
            })
            return self._optima_pickup_resolution_payload()

        provider_code = self.optima_pickup_provider_code or ""
        normalized = self._optima_pickup_selected_point()
        raw_point = self.optima_pickup_raw_data or {}
        if not isinstance(raw_point, dict):
            raw_point = {}
        return self._optima_pickup_apply_resolution(
            provider_code, normalized, raw_point, {}
        )

    def _optima_delivery_confirmation_guard(self):
        """Final no-I/O guard before confirming a pickup sale order.

        Checkout/provider validation has already happened before payment. At
        confirmation time we deliberately do not call a remote API again: a
        transient provider outage must not turn a successful payment callback
        into a half-confirmed order. Instead, we verify that the exact local
        state validated at checkout is still present.
        """
        self.ensure_one()
        if not self.optima_pickup_mode:
            return
        if not self.optima_pickup_external_id:
            raise ValidationError(_(
                "El pedido está en modo punto de recogida pero no tiene un punto seleccionado."
            ))
        if not (
            self.optima_pickup_resolved
            and self.optima_pickup_delivery_carrier_id
            and self.carrier_id
        ):
            raise ValidationError(_(
                "El punto de recogida no tiene un método de entrega validado."
            ))
        if self.carrier_id != self.optima_pickup_delivery_carrier_id:
            raise ValidationError(_(
                "El método de entrega ya no coincide con el método validado para el punto de recogida."
            ))
        if not isinstance(self.pickup_location_data, dict) or not self.pickup_location_data:
            raise ValidationError(_(
                "Faltan los datos estándar de la ubicación de recogida en el pedido."
            ))

        profile = self._optima_pickup_package_profile()
        if not profile.get("success"):
            raise ValidationError(
                profile.get("message")
                or _("El pedido ya no tiene datos logísticos válidos para la expedición.")
            )

        validated_logistics = self.optima_pickup_resolved_logistics_fingerprint or ""
        validated_address = self.optima_pickup_resolved_address_fingerprint or ""
        if not validated_logistics or validated_logistics != self._optima_pickup_logistics_fingerprint():
            raise ValidationError(_(
                "El contenido del pedido ha cambiado desde la última validación del punto de recogida. "
                "Vuelve al checkout para recalcular el envío."
            ))
        if not validated_address or validated_address != self._optima_pickup_address_fingerprint():
            raise ValidationError(_(
                "La dirección de entrega ha cambiado desde la última validación del punto de recogida. "
                "Vuelve al checkout y selecciona de nuevo el punto."
            ))

    def _optima_delivery_picking_snapshot_vals(self):
        """Build the operational snapshot copied to outgoing pickings."""
        self.ensure_one()
        profile = self._optima_pickup_package_profile()
        method = self.carrier_id
        return {
            "optima_delivery_snapshot_ready": bool(method and profile.get("success")),
            "optima_delivery_method_snapshot_id": method.id or False,
            "optima_delivery_method_name_snapshot": method.display_name if method else False,
            "optima_delivery_expected_packaging": (
                self.optima_delivery_packaging_suggested or False
            ),
            "optima_delivery_method_limits_text": self.optima_delivery_method_limits or False,
            "optima_delivery_method_limits_snapshot": (
                self.optima_delivery_method_limits_snapshot or False
            ),
            "optima_delivery_package_weight_kg": profile.get("weight_kg", 0.0),
            "optima_delivery_package_length_mm": profile.get("length_mm", 0.0),
            "optima_delivery_package_width_mm": profile.get("width_mm", 0.0),
            "optima_delivery_package_height_mm": profile.get("height_mm", 0.0),
            "optima_delivery_package_unit_count": profile.get("unit_count", 0),
            "optima_delivery_pickup_mode": bool(self.optima_pickup_mode),
            "optima_delivery_pickup_provider_code": self.optima_pickup_provider_code or False,
            "optima_delivery_pickup_external_id": self.optima_pickup_external_id or False,
            "optima_delivery_pickup_carrier_code": self.optima_pickup_carrier_code or False,
            "optima_delivery_pickup_name": self.optima_pickup_name or False,
            "optima_delivery_pickup_street": self.optima_pickup_street or False,
            "optima_delivery_pickup_zip": self.optima_pickup_zip or False,
            "optima_delivery_pickup_city": self.optima_pickup_city or False,
            "optima_delivery_pickup_country_code": self.optima_pickup_country_code or False,
        }

    def _optima_delivery_provider_sync_picking(self, picking):
        """Adapter hook to copy provider-specific shipment data to a picking."""
        self.ensure_one()
        picking.ensure_one()
        return None

    def _optima_delivery_sync_pickings(self):
        """Copy checkout delivery decisions to newly-created outgoing pickings."""
        for order in self:
            vals = order._optima_delivery_picking_snapshot_vals()
            pickings = order.picking_ids.filtered(
                lambda picking: picking.state != "cancel"
                and picking.picking_type_id.code == "outgoing"
            )
            for picking in pickings:
                picking_vals = dict(vals)
                # The selected pickup carrier is authoritative for the shipment.
                # For ordinary deliveries we leave Odoo's native carrier
                # propagation untouched and only copy the informational snapshot.
                if order.optima_pickup_mode and order.carrier_id:
                    picking_vals["carrier_id"] = order.carrier_id.id
                picking.write(picking_vals)
                order._optima_delivery_provider_sync_picking(picking)

    def _action_confirm(self):
        """Protect pickup confirmation and prepare warehouse shipment data."""
        for order in self:
            order._optima_delivery_confirmation_guard()
        result = super()._action_confirm()
        self._optima_delivery_sync_pickings()
        return result

    def _check_cart_is_ready_to_be_paid(self):
        self.ensure_one()
        self._optima_pickup_ensure_current_state()
        if self.optima_pickup_mode and not (
            self.optima_pickup_resolved and self.optima_pickup_delivery_carrier_id
        ):
            raise ValidationError(_(
                "El punto de recogida todavía no tiene un método y precio de entrega válidos."
            ))
        return super()._check_cart_is_ready_to_be_paid()
