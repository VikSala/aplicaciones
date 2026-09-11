from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # Immutable operational snapshot copied from the sale order at confirmation.
    # It gives the warehouse the exact delivery assumptions that were accepted
    # by checkout instead of recomputing them later with possibly changed data.
    optima_delivery_snapshot_ready = fields.Boolean(
        string="Snapshot de entrega preparado",
        copy=True,
        readonly=True,
    )
    optima_delivery_method_snapshot_id = fields.Many2one(
        "delivery.carrier",
        string="Método esperado",
        copy=True,
        readonly=True,
        ondelete="set null",
    )
    optima_delivery_method_name_snapshot = fields.Char(
        string="Método esperado (snapshot)",
        copy=True,
        readonly=True,
    )
    optima_delivery_expected_packaging = fields.Char(
        string="Embalaje esperado",
        copy=True,
        readonly=True,
    )
    optima_delivery_method_limits_text = fields.Text(
        string="Límites del método",
        copy=True,
        readonly=True,
    )
    optima_delivery_method_limits_snapshot = fields.Json(
        string="Snapshot técnico de límites",
        copy=True,
        readonly=True,
    )
    optima_delivery_package_weight_kg = fields.Float(
        string="Peso esperado (kg)",
        digits=(16, 3),
        copy=True,
        readonly=True,
    )
    optima_delivery_package_length_mm = fields.Float(
        string="Largo esperado (mm)",
        digits=(16, 2),
        copy=True,
        readonly=True,
    )
    optima_delivery_package_width_mm = fields.Float(
        string="Ancho esperado (mm)",
        digits=(16, 2),
        copy=True,
        readonly=True,
    )
    optima_delivery_package_height_mm = fields.Float(
        string="Alto esperado (mm)",
        digits=(16, 2),
        copy=True,
        readonly=True,
    )
    optima_delivery_package_unit_count = fields.Integer(
        string="Unidades físicas esperadas",
        copy=True,
        readonly=True,
    )

    optima_delivery_pickup_mode = fields.Boolean(
        string="Expedición a punto de recogida",
        copy=True,
        readonly=True,
    )
    optima_delivery_pickup_provider_code = fields.Char(
        string="Proveedor pickup",
        copy=True,
        readonly=True,
    )
    optima_delivery_pickup_external_id = fields.Char(
        string="ID externo del punto",
        copy=True,
        readonly=True,
    )
    optima_delivery_pickup_carrier_code = fields.Char(
        string="Código transportista del punto",
        copy=True,
        readonly=True,
    )
    optima_delivery_pickup_name = fields.Char(
        string="Punto de recogida",
        copy=True,
        readonly=True,
    )
    optima_delivery_pickup_street = fields.Char(
        string="Dirección del punto",
        copy=True,
        readonly=True,
    )
    optima_delivery_pickup_zip = fields.Char(
        string="CP del punto",
        copy=True,
        readonly=True,
    )
    optima_delivery_pickup_city = fields.Char(
        string="Ciudad del punto",
        copy=True,
        readonly=True,
    )
    optima_delivery_pickup_country_code = fields.Char(
        string="País del punto",
        copy=True,
        readonly=True,
    )
    optima_delivery_preflight_status = fields.Char(
        string="Estado previo al transportista",
        compute="_compute_optima_delivery_preflight_status",
    )

    @staticmethod
    def _optima_normalized_text(value):
        return " ".join(str(value or "").strip().lower().split())

    def _optima_delivery_core_preflight_error(self):
        """Return a blocking diagnostic without performing provider I/O."""
        self.ensure_one()
        if not self.optima_delivery_pickup_mode:
            return False
        if not self.optima_delivery_snapshot_ready:
            return _("No existe un snapshot de entrega confirmado para esta expedición.")
        if not self.carrier_id:
            return _("La expedición no tiene método de entrega.")
        if (
            self.optima_delivery_method_snapshot_id
            and self.carrier_id != self.optima_delivery_method_snapshot_id
        ):
            return _(
                "El método de entrega de la expedición no coincide con el método "
                "validado en el pedido."
            )
        if not self.optima_delivery_pickup_provider_code:
            return _("Falta el proveedor del punto de recogida.")
        if not self.optima_delivery_pickup_external_id:
            return _("Falta el identificador del punto de recogida.")
        if not self.partner_id:
            return _("La expedición no tiene dirección de destino.")

        # Odoo 18 converts pickup_location_data into the delivery partner when
        # the sale is confirmed. Check the stable location parts so a manual
        # address edit cannot silently ship the pickup parcel elsewhere.
        expected_country = self._optima_normalized_text(
            self.optima_delivery_pickup_country_code
        )
        actual_country = self._optima_normalized_text(self.partner_id.country_id.code)
        expected_zip = self._optima_normalized_text(self.optima_delivery_pickup_zip)
        actual_zip = self._optima_normalized_text(self.partner_id.zip)
        expected_city = self._optima_normalized_text(self.optima_delivery_pickup_city)
        actual_city = self._optima_normalized_text(self.partner_id.city)
        expected_street = self._optima_normalized_text(self.optima_delivery_pickup_street)
        actual_street = self._optima_normalized_text(self.partner_id.street)
        if expected_country and actual_country != expected_country:
            return _("El país de la expedición ya no coincide con el punto seleccionado.")
        if expected_zip and actual_zip != expected_zip:
            return _("El código postal de la expedición ya no coincide con el punto seleccionado.")
        if expected_city and actual_city != expected_city:
            return _("La ciudad de la expedición ya no coincide con el punto seleccionado.")
        if expected_street and actual_street != expected_street:
            return _("La dirección de la expedición ya no coincide con el punto seleccionado.")
        return False

    @api.depends(
        "optima_delivery_snapshot_ready",
        "optima_delivery_pickup_mode",
        "optima_delivery_pickup_provider_code",
        "optima_delivery_pickup_external_id",
        "optima_delivery_pickup_zip",
        "optima_delivery_pickup_city",
        "optima_delivery_pickup_country_code",
        "carrier_id",
        "optima_delivery_method_snapshot_id",
        "partner_id",
        "partner_id.street",
        "partner_id.zip",
        "partner_id.city",
        "partner_id.country_id",
    )
    def _compute_optima_delivery_preflight_status(self):
        for picking in self:
            if not picking.optima_delivery_snapshot_ready:
                picking.optima_delivery_preflight_status = _(
                    "Sin snapshot Optima: se aplicará el flujo estándar de Odoo."
                )
                continue
            error = picking._optima_delivery_core_preflight_error()
            if error:
                picking.optima_delivery_preflight_status = error
            elif picking.optima_delivery_pickup_mode:
                picking.optima_delivery_preflight_status = _(
                    "Preparado: método, punto y destino coinciden con el pedido confirmado."
                )
            else:
                picking.optima_delivery_preflight_status = _(
                    "Snapshot de expedición preparado."
                )

    def _optima_delivery_provider_preflight(self):
        """Provider adapter hook executed immediately before carrier shipping."""
        self.ensure_one()
        return None

    def _optima_delivery_assert_ready_for_carrier(self):
        """Block a pickup shipment if its confirmed operational data diverged."""
        self.ensure_one()
        # Backfill pickings created just before upgrading to Phase 4. The sale
        # order already contains the stable pickup snapshot from Phases 1/3, so
        # no provider API call is necessary here.
        if (
            not self.optima_delivery_snapshot_ready
            and self.sale_id
            and self.sale_id.optima_pickup_mode
        ):
            self.sale_id._optima_delivery_sync_pickings()
        error = self._optima_delivery_core_preflight_error()
        if error:
            raise ValidationError(error)
        if self.optima_delivery_pickup_mode:
            self._optima_delivery_provider_preflight()

    def send_to_shipper(self):
        """Run a final local/provider preflight before Odoo calls the carrier.

        The actual shipment, label and tracking lifecycle remains owned by
        stock_delivery and the installed carrier connector. This module only
        guarantees that the data selected during checkout is the data about to
        be sent.
        """
        self.ensure_one()
        self._optima_delivery_assert_ready_for_carrier()
        return super().send_to_shipper()
