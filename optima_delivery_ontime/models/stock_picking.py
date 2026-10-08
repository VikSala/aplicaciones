from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.ontime_tariff_pdf import (
    SERVICE_ECONOMY,
    SERVICE_XS24,
    ZONE_BALEARES_MAYORES,
    ZONE_BALEARES_MENORES,
    ZONE_CANARIAS_MAYORES,
    ZONE_CANARIAS_MENORES,
    ZONE_CEUTA,
    ZONE_IBERIA,
    ZONE_MELILLA,
    ZONE_PROVINCIAL,
    ZONE_REGIONAL,
)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    ontime_shipment_reference = fields.Char(
        string="OnTime Shipment Reference",
        readonly=True,
        copy=False,
        index=True,
    )
    ontime_shipment_status = fields.Char(
        string="OnTime Shipment Status",
        readonly=True,
        copy=False,
    )
    ontime_is_test_shipment = fields.Boolean(
        string="OnTime API Test Shipment",
        readonly=True,
        copy=False,
        help=(
            "Enabled when the shipment was sent in API Test mode. In that mode the module "
            "forces direccionDestino.nombre to 'Test Pruebas' so Mensaglobal/OnTime do not "
            "consider it a valid delivery."
        ),
    )
    ontime_network_reference = fields.Char(
        string="OnTime Network Reference",
        readonly=True,
        copy=False,
        help="codigoExpedicionRed returned by Mensaglobal.",
    )
    ontime_barcode = fields.Char(
        string="OnTime Barcode",
        readonly=True,
        copy=False,
        help="codigoBarras returned by Mensaglobal.",
    )
    ontime_tracking_url = fields.Char(
        string="OnTime Tracking URL",
        readonly=True,
        copy=False,
        help="urlSeguimientoRed returned by Mensaglobal tracking.",
    )
    ontime_pod_url = fields.Char(
        string="OnTime POD URL",
        readonly=True,
        copy=False,
        help="urlPOD returned by Mensaglobal tracking when proof of delivery is available.",
    )
    ontime_shipment_correlation_id = fields.Char(
        string="OnTime Correlation ID",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    ontime_shipment_created_at = fields.Datetime(
        string="OnTime Shipment Created At",
        readonly=True,
        copy=False,
    )
    ontime_shipment_service = fields.Selection(
        [
            (SERVICE_ECONOMY, "XS ECONOMY 24-48h"),
            (SERVICE_XS24, "Fallback XS (19Horas)"),
        ],
        string="OnTime Tariff Service",
        readonly=True,
        copy=False,
    )
    ontime_shipment_api_service = fields.Char(
        string="OnTime API Service",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    ontime_shipment_zone = fields.Selection(
        [
            (ZONE_PROVINCIAL, "Provincial"),
            (ZONE_REGIONAL, "Regional"),
            (ZONE_IBERIA, "Iberia"),
            (ZONE_CEUTA, "Ceuta"),
            (ZONE_MELILLA, "Melilla"),
            (ZONE_BALEARES_MAYORES, "Baleares mayores"),
            (ZONE_BALEARES_MENORES, "Baleares menores"),
            (ZONE_CANARIAS_MAYORES, "Canarias mayores"),
            (ZONE_CANARIAS_MENORES, "Canarias menores"),
        ],
        string="OnTime Tariff Zone",
        readonly=True,
        copy=False,
    )
    ontime_shipment_price = fields.Monetary(
        string="OnTime Contract Price",
        currency_field="ontime_currency_id",
        readonly=True,
        copy=False,
    )
    ontime_shipment_weight = fields.Float(
        string="OnTime Actual Weight (kg)",
        digits=(16, 3),
        readonly=True,
        copy=False,
    )
    ontime_shipment_billable_weight = fields.Float(
        string="OnTime Billable Weight (kg)",
        digits=(16, 3),
        readonly=True,
        copy=False,
    )
    ontime_shipment_volumetric_weight = fields.Float(
        string="OnTime Volumetric Weight (kg)",
        digits=(16, 3),
        readonly=True,
        copy=False,
    )
    ontime_shipment_packages = fields.Integer(
        string="OnTime Packages",
        readonly=True,
        copy=False,
    )

    # Phase 5 - label + tracking lifecycle
    ontime_label_attachment_id = fields.Many2one(
        "ir.attachment",
        string="OnTime Label",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    ontime_label_downloaded_at = fields.Datetime(
        string="OnTime Label Downloaded At",
        readonly=True,
        copy=False,
    )
    ontime_tracking_last_sync = fields.Datetime(
        string="OnTime Tracking Last Sync",
        readonly=True,
        copy=False,
    )
    ontime_tracking_last_event = fields.Char(
        string="OnTime Last Tracking Event",
        readonly=True,
        copy=False,
    )
    ontime_tracking_events_json = fields.Text(
        string="OnTime Tracking Raw Data",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )

    # Phase 6 - lifecycle, POD and cancellation audit
    ontime_shipment_detail_last_sync = fields.Datetime(
        string="OnTime Shipment Detail Last Sync",
        readonly=True,
        copy=False,
    )
    ontime_shipment_detail_json = fields.Text(
        string="OnTime Shipment Detail Raw Data",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    ontime_pod_attachment_id = fields.Many2one(
        "ir.attachment",
        string="OnTime Proof of Delivery",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    ontime_pod_downloaded_at = fields.Datetime(
        string="OnTime POD Downloaded At",
        readonly=True,
        copy=False,
    )
    ontime_shipment_cancelled_at = fields.Datetime(
        string="OnTime Shipment Cancelled At",
        readonly=True,
        copy=False,
    )
    ontime_cancel_correlation_id = fields.Char(
        string="OnTime Cancellation Correlation ID",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    ontime_network_cancellation_state = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("yes", "Cancelled in OnTime network"),
            ("no", "Not confirmed in OnTime network"),
        ],
        string="OnTime Network Cancellation",
        default="unknown",
        readonly=True,
        copy=False,
    )

    # Phase 8 - operational safety/audit. ``*_uncertain`` means a write request
    # may have reached OnTime but Odoo did not receive a conclusive response.
    ontime_operation_state = fields.Selection(
        [
            ("none", "No OnTime shipment"),
            ("created", "Created / linked"),
            ("create_uncertain", "Creation result uncertain"),
            ("cancel_uncertain", "Cancellation result uncertain"),
            ("cancelled_network_unconfirmed", "Cancelled in Mensaglobal; network not confirmed"),
            ("cancelled", "Cancelled"),
        ],
        string="OnTime Operation State",
        default="none",
        readonly=True,
        copy=False,
        index=True,
    )
    ontime_last_api_attempt_at = fields.Datetime(
        string="OnTime Last API Attempt",
        readonly=True,
        copy=False,
    )
    ontime_last_api_error = fields.Text(
        string="OnTime Last API Error",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    ontime_shipment_request_hash = fields.Char(
        string="OnTime Shipment Request Hash",
        readonly=True,
        copy=False,
        groups="base.group_system",
        index=True,
    )
    ontime_reconciled_at = fields.Datetime(
        string="OnTime Reconciled At",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    ontime_reconciliation_note = fields.Text(
        string="OnTime Reconciliation Note",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )

    ontime_currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )

    def _ontime_action_carrier(self):
        self.ensure_one()
        carrier = self.carrier_id
        if not carrier or carrier.delivery_type != "ontime":
            raise UserError(_("This delivery order is not assigned to an OnTime carrier."))
        carrier._ontime_validate_company(self)
        if self.ontime_operation_state == "create_uncertain":
            raise UserError(
                _(
                    "The OnTime creation result is uncertain. Reconcile the operation before "
                    "using shipment actions."
                )
            )
        if not (self.ontime_shipment_reference or self.carrier_tracking_ref):
            raise UserError(_("Create the OnTime shipment before using label or tracking actions."))
        return carrier

    def action_ontime_reconcile(self):
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only an administrator can reconcile uncertain OnTime operations."))
        if self.ontime_operation_state not in {"create_uncertain", "cancel_uncertain"}:
            raise UserError(_("This picking has no uncertain OnTime operation to reconcile."))
        wizard = self.env["delivery.ontime.reconcile.wizard"].create(
            {"picking_id": self.id}
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Reconcile OnTime operation"),
            "res_model": "delivery.ontime.reconcile.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "optima_delivery_ontime.view_delivery_ontime_reconcile_wizard_form"
            ).id,
            "res_id": wizard.id,
            "target": "new",
        }

    def action_ontime_download_label(self):
        self.ensure_one()
        carrier = self._ontime_action_carrier()
        attachment = carrier._ontime_store_label_attachment(self)
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }

    def action_ontime_refresh_tracking(self):
        self.ensure_one()
        carrier = self._ontime_action_carrier()
        carrier._ontime_refresh_tracking(self)
        message = self.ontime_tracking_last_event or self.ontime_shipment_status or _("Updated")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OnTime tracking updated"),
                "message": message,
                "type": "success",
                "sticky": False,
            },
        }

    def action_ontime_refresh_shipment_detail(self):
        self.ensure_one()
        carrier = self._ontime_action_carrier()
        carrier._ontime_refresh_shipment_detail(self)
        message = self.ontime_shipment_status or _("Updated")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OnTime shipment updated"),
                "message": message,
                "type": "success",
                "sticky": False,
            },
        }

    def action_ontime_download_pod(self):
        self.ensure_one()
        carrier = self._ontime_action_carrier()
        attachment = carrier._ontime_store_pod_attachment(self)
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }

    def action_ontime_cancel_shipment(self):
        self.ensure_one()
        carrier = self._ontime_action_carrier()
        carrier.ontime_cancel_shipment(self)
        uncertain = self.ontime_operation_state == "cancel_uncertain"
        network_unconfirmed = self.ontime_operation_state == "cancelled_network_unconfirmed"
        title = (
            _("OnTime cancellation requires reconciliation")
            if uncertain
            else (
                _("Cancellation not confirmed in OnTime network")
                if network_unconfirmed
                else _("OnTime shipment cancelled")
            )
        )
        message = (
            _("The remote cancellation result is uncertain. Check Mensaglobal before retrying.")
            if uncertain
            else (
                _("Mensaglobal cancelled the shipment, but OnTime may still deliver it.")
                if network_unconfirmed
                else (self.ontime_shipment_reference or self.carrier_tracking_ref or self.name)
            )
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": "warning" if (uncertain or network_unconfirmed) else "success",
                "sticky": bool(uncertain or network_unconfirmed),
            },
        }

    def action_ontime_open_tracking(self):
        self.ensure_one()
        carrier = self._ontime_action_carrier()
        url = carrier.ontime_get_tracking_link(self)
        if not url:
            raise UserError(_("Mensaglobal has not returned a public tracking URL for this shipment."))
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }
