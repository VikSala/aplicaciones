import base64
import hashlib
import io
import json
import logging
import math
import re
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.ontime_client import OnTimeAPIError, OnTimeClient
from ..services.ontime_tariff_pdf import (
    OnTimeTariffPDFError,
    OnTimeTariffPDFParser,
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


_logger = logging.getLogger(__name__)


ONTIME_MENSAGLOBAL_PREPRODUCTION_URL = "https://preproduccion.mensaglobal.com/api"
ONTIME_MENSAGLOBAL_PRODUCTION_URL = "https://preproduccion.mensaglobal.com/api"
ONTIME_CONNECTION_TEST_REFERENCE = "__ODOO_OPTIMA_CONNECTION_TEST__"

# Same contractual zoning convention used by the supplied Optima GLS module:
# origin Alicante (03), same province = PROVINCIAL, Alicante's bordering
# provinces Albacete (02), Murcia (30), Valencia (46) = REGIONAL, rest of
# mainland Spain = IBERIA.
ONTIME_DEFAULT_ORIGIN_POSTAL_CODE = "03000"
ONTIME_DEFAULT_REGIONAL_PREFIXES = "02,30,46"

# Operational postcode split for the island tariff columns. These defaults are
# configurable in the carrier so they can be adapted without code if OnTime
# provides a different island classification.
ONTIME_DEFAULT_BALEARES_MINOR_PREFIXES = "077,078"
ONTIME_DEFAULT_CANARIAS_MAJOR_PREFIXES = (
    "350,351,352,353,354,380,381,382,383,384,385,386"
)

# PostgreSQL advisory-lock namespaces. They serialize only OnTime operations for
# the same business record and are released automatically at transaction end.
ONTIME_PICKING_LOCK_NAMESPACE = 1330533449
ONTIME_CARRIER_LOCK_NAMESPACE = 1330533450


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(
        selection_add=[("ontime", "OnTime")],
        ondelete={"ontime": "set default"},
    )

    # ------------------------------------------------------------------
    # Phase 1 / Phase 2 - API configuration and technical client
    # ------------------------------------------------------------------
    ontime_mode = fields.Selection(
        selection=[
            ("simulated", "Simulated (local only)"),
            ("test", "API Test (Test Pruebas)"),
            ("real", "Production"),
        ],
        string="OnTime Mode",
        default="simulated",
        required=True,
        copy=False,
        help=(
            "Simulated mode never communicates with Mensaglobal. API Test uses the real "
            "Mensaglobal URL/token but forces the destination recipient name to 'Test Pruebas', "
            "as instructed by OnTime, so the shipment is not considered valid. Production sends "
            "the real recipient name."
        ),
    )
    ontime_environment = fields.Selection(
        selection=[
            ("sandbox", "Preproduction"),
            ("production", "Production"),
        ],
        string="Legacy OnTime Environment",
        default="production",
        required=True,
        copy=False,
        help="Compatibility field retained from the provisional integration. Phase 7B uses the confirmed Mensaglobal production API URL for both API Test and Production modes.",
    )
    ontime_api_key = fields.Char(
        string="Mensaglobal API Token",
        copy=False,
        groups="base.group_system",
        help="Token supplied by Mensaglobal and sent as Authorization: Bearer <token>.",
    )
    ontime_preproduction_base_url = fields.Char(
        string="Legacy Mensaglobal Preproduction Base URL",
        default=ONTIME_MENSAGLOBAL_PREPRODUCTION_URL,
        copy=False,
        groups="base.group_system",
        help="Compatibility field retained from Phase 7A. It is only used as a fallback if the confirmed API Base URL is empty.",
    )
    ontime_production_base_url = fields.Char(
        string="Mensaglobal API Base URL",
        default=ONTIME_MENSAGLOBAL_PRODUCTION_URL,
        copy=False,
        groups="base.group_system",
        help="API base URL confirmed by OnTime. The same URL/token are used for API Test and Production; test shipments are identified by recipient name Test Pruebas.",
    )
    ontime_origin_center = fields.Char(
        string="Legacy OnTime Origin Center",
        copy=False,
        help=(
            "Compatibility field retained from the provisional API adapter. Mensaglobal v1 "
            "does not use this value and it is not sent in shipment creation."
        ),
    )
    ontime_timeout = fields.Integer(
        string="OnTime Timeout (s)",
        default=20,
        required=True,
        copy=False,
        help="Maximum number of seconds to wait for an OnTime HTTP response.",
    )
    ontime_read_retries = fields.Integer(
        string="OnTime Safe Read Retries",
        default=1,
        required=True,
        copy=False,
        groups="base.group_system",
        help=(
            "Number of automatic retries for read-only OnTime requests such as tracking, "
            "shipment detail, labels and POD. Write operations are never retried automatically."
        ),
    )
    ontime_max_document_size_mb = fields.Float(
        string="OnTime Maximum Document Size (MB)",
        default=20.0,
        required=True,
        copy=False,
        groups="base.group_system",
        help="Maximum accepted size for labels/POD downloaded from OnTime.",
    )
    ontime_base_url = fields.Char(
        string="OnTime Base URL",
        compute="_compute_ontime_base_url",
        readonly=True,
    )
    ontime_shipping_tax_ids = fields.Many2many(
        related="product_id.taxes_id",
        readonly=False,
        string="Shipping Sales Taxes",
        help=(
            "Sales taxes used on the delivery line. If the OnTime delivery product has no "
            "sales tax for the carrier company, the module automatically assigns that "
            "company's default sales tax. Odoo fiscal positions are then applied normally."
        ),
    )

    # ------------------------------------------------------------------
    # Phase 4 - shipment creation
    # ------------------------------------------------------------------
    ontime_shipment_endpoint = fields.Char(
        string="OnTime Shipment Endpoint",
        default="/v1/envios",
        required=True,
        copy=False,
        groups="base.group_system",
        help=(
            "Mensaglobal endpoint used to create shipments. The v1 API uses /v1/envios."
        ),
    )
    ontime_api_service_economy = fields.Char(
        string="OnTime API Service - Economy",
        default="72",
        copy=False,
        groups="base.group_system",
        help=(
            "Mensaglobal service code for the Economy service. OnTime supplied code 72 for "
            "XS Economy 48/72h; keep it configurable in case the account changes."
        ),
    )
    ontime_api_service_xs24 = fields.Char(
        string="OnTime API Service - Fallback XS",
        default="24",
        copy=False,
        groups="base.group_system",
        help=(
            "Mensaglobal service code used as fallback. OnTime supplied code 24 for the "
            "19Horas XS service; keep it configurable in case the account changes."
        ),
    )

    # ------------------------------------------------------------------
    # Phase 5 - labels and tracking
    # ------------------------------------------------------------------
    ontime_label_endpoint = fields.Char(
        string="OnTime Label Endpoint",
        default="/v1/envios/etiquetas/{reference}",
        required=True,
        copy=False,
        groups="base.group_system",
        help=(
            "Mensaglobal endpoint that returns shipment labels as PDF base64. {reference} "
            "is replaced by codigoExpedicion."
        ),
    )
    ontime_tracking_endpoint = fields.Char(
        string="OnTime Tracking Endpoint",
        default="/v1/envios/localizar/{reference}",
        required=True,
        copy=False,
        groups="base.group_system",
        help=(
            "Mensaglobal endpoint used to retrieve ultimoEstado, tracking history, "
            "urlSeguimientoRed and urlPOD."
        ),
    )
    ontime_public_tracking_url = fields.Char(
        string="OnTime Public Tracking URL",
        default=False,
        copy=False,
        help=(
            "Optional fallback tracking URL. In real mode Mensaglobal normally returns "
            "urlSeguimientoRed for each shipment and that URL takes priority."
        ),
    )
    ontime_auto_download_label = fields.Boolean(
        string="Automatically Download OnTime Label",
        default=True,
        help=(
            "After a shipment is created, try to download and attach its label. A label "
            "download failure never invalidates an already-created OnTime shipment; it can "
            "be retried later from the delivery order."
        ),
    )

    # ------------------------------------------------------------------
    # Phase 6 - shipment lifecycle, POD and safe cancellation
    # ------------------------------------------------------------------
    ontime_shipment_detail_endpoint = fields.Char(
        string="OnTime Shipment Detail Endpoint",
        default="/v1/envios/localizar/{reference}",
        required=True,
        copy=False,
        groups="base.group_system",
        help=(
            "Compatibility field. Mensaglobal exposes shipment status through the same "
            "localizar endpoint used for tracking."
        ),
    )
    ontime_pod_endpoint = fields.Char(
        string="OnTime Proof of Delivery Endpoint",
        copy=False,
        groups="base.group_system",
        help=(
            "Legacy compatibility field. Mensaglobal supplies urlPOD through the tracking "
            "response, so this endpoint is no longer used."
        ),
    )
    ontime_cancellation_mode = fields.Selection(
        selection=[
            ("manual", "Legacy manual mode"),
            ("api", "Mensaglobal API"),
        ],
        string="OnTime Cancellation Mode",
        default="api",
        required=True,
        copy=False,
        help=(
            "Mensaglobal v1 exposes an idempotent cancellation endpoint. API mode is the "
            "normal mode; Manual is retained only for database compatibility."
        ),
    )
    ontime_cancel_endpoint = fields.Char(
        string="OnTime Cancellation Endpoint",
        default="/v1/envios/{reference}/anular",
        copy=False,
        groups="base.group_system",
        help=(
            "Mensaglobal idempotent cancellation endpoint. {reference} is codigoExpedicion."
        ),
    )
    ontime_cancel_http_method = fields.Selection(
        selection=[("PUT", "PUT"), ("DELETE", "DELETE"), ("POST", "POST")],
        string="OnTime Cancellation HTTP Method",
        default="PUT",
        required=True,
        copy=False,
        groups="base.group_system",
        help="Mensaglobal v1 cancellation uses PUT. Legacy values are retained for compatibility.",
    )

    # ------------------------------------------------------------------
    # Phase 3 - official tariff PDF and deterministic zoning
    # ------------------------------------------------------------------
    ontime_tariff_rule_ids = fields.One2many(
        "delivery.ontime.tariff.rule",
        "carrier_id",
        string="OnTime Tariff Rates",
        copy=False,
    )
    ontime_tariff_file = fields.Binary(
        string="OnTime Tariff PDF",
        copy=False,
        attachment=True,
        groups="base.group_system",
        help=(
            "Official OnTime XS tariff PDF. Importing a new PDF replaces the "
            "previous parsed tariff for this carrier."
        ),
    )
    ontime_tariff_filename = fields.Char(copy=False, groups="base.group_system")
    ontime_tariff_source_hash = fields.Char(
        string="Tariff SHA-256",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    ontime_tariff_imported_at = fields.Datetime(
        string="Tariff Imported At",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    ontime_tariff_year = fields.Integer(
        string="Tariff Year",
        readonly=True,
        copy=False,
    )
    ontime_origin_postal_code = fields.Char(
        string="Tariff Origin Postal Code",
        default=ONTIME_DEFAULT_ORIGIN_POSTAL_CODE,
        help=(
            "Postal code used to decide Provincial/Regional/Iberia. The supplied "
            "GLS configuration uses Alicante (03) as contractual origin."
        ),
    )
    ontime_regional_postal_prefixes = fields.Char(
        string="Regional Postal Prefixes",
        default=ONTIME_DEFAULT_REGIONAL_PREFIXES,
        help=(
            "Comma-separated Spanish two-digit postal prefixes considered Regional. "
            "Defaults to the same Alicante bordering provinces used by the supplied "
            "GLS module: Albacete 02, Murcia 30 and Valencia 46."
        ),
    )
    ontime_baleares_minor_prefixes = fields.Char(
        string="Baleares Minor Postal Prefixes",
        default=ONTIME_DEFAULT_BALEARES_MINOR_PREFIXES,
        help=(
            "Three-digit postal prefixes classified as Baleares menores. "
            "Other 07xxx destinations are treated as Baleares mayores."
        ),
    )
    ontime_canarias_major_prefixes = fields.Char(
        string="Canarias Major Postal Prefixes",
        default=ONTIME_DEFAULT_CANARIAS_MAJOR_PREFIXES,
        help=(
            "Three-digit postal prefixes classified as Canarias mayores. "
            "Other 35xxx/38xxx destinations are treated as Canarias menores."
        ),
    )

    # ------------------------------------------------------------------
    # Phase 4.1 - XS operational limits and volumetric weight
    # ------------------------------------------------------------------
    ontime_require_weight = fields.Boolean(
        string="Require Product Weight",
        default=True,
        help="Reject quotations/shipments when a physical product has no configured weight.",
    )
    ontime_require_dimensions = fields.Boolean(
        string="Require Product Dimensions",
        default=True,
        help=(
            "Require the OnTime length/width/height on products when estimating a shipment "
            "without real Odoo packages. Real packages use the dimensions of their Package Type."
        ),
    )
    ontime_volumetric_divisor = fields.Float(
        string="Volumetric Divisor",
        default=5000.0,
        digits=(16, 2),
        help=(
            "Volumetric formula: Length (cm) × Width (cm) × Height (cm) / divisor. "
            "Default 5000. Set 0 only if volumetric weight must be disabled by contract."
        ),
    )
    # Kept for backwards compatibility with Phase 3/4 databases. It is no longer
    # used by the calculation; new installations and upgrades use the divisor.
    ontime_volumetric_factor = fields.Float(
        string="Legacy Volumetric Factor (kg/m³)",
        default=0.0,
        digits=(16, 3),
        copy=False,
        help="Deprecated compatibility field. Use Volumetric Divisor instead.",
    )
    ontime_max_package_weight_kg = fields.Float(
        string="Maximum Weight per Package (kg)",
        default=30.0,
        digits=(16, 3),
        help=(
            "Operational XS limit applied per package. Default 30 kg. Keep configurable "
            "so a direct OnTime contract can override it without code changes."
        ),
    )
    ontime_max_package_dimension_sum_cm = fields.Float(
        string="Maximum L+W+H per Package (cm)",
        default=300.0,
        digits=(16, 2),
        help=(
            "Maximum combined package dimensions (Length + Width + Height). Default 300 cm. "
            "Set 0 to disable this validation if OnTime confirms different conditions."
        ),
    )
    ontime_max_length_cm = fields.Float(
        string="Maximum Length (cm)",
        digits=(16, 2),
        help="Optional additional per-side restriction. 0 disables it.",
    )
    ontime_max_width_cm = fields.Float(
        string="Maximum Width (cm)",
        digits=(16, 2),
        help="Optional additional per-side restriction. 0 disables it.",
    )
    ontime_max_height_cm = fields.Float(
        string="Maximum Height (cm)",
        digits=(16, 2),
        help="Optional additional per-side restriction. 0 disables it.",
    )

    @api.depends("ontime_production_base_url")
    def _compute_ontime_base_url(self):
        for carrier in self:
            # OnTime confirmed that the configured Mensaglobal URL is the URL to use
            # for both API Test (recipient = Test Pruebas) and Production. The old
            # preproduction field is kept only for database-upgrade compatibility.
            carrier.ontime_base_url = (
                carrier.ontime_production_base_url
                or ONTIME_MENSAGLOBAL_PRODUCTION_URL
            ).rstrip("/")

    @api.constrains("ontime_timeout", "ontime_read_retries", "ontime_max_document_size_mb")
    def _check_ontime_http_settings(self):
        for carrier in self:
            if carrier.delivery_type != "ontime":
                continue
            if carrier.ontime_timeout <= 0:
                raise ValidationError(_("The OnTime timeout must be greater than 0 seconds."))
            if carrier.ontime_read_retries < 0 or carrier.ontime_read_retries > 5:
                raise ValidationError(_("OnTime safe read retries must be between 0 and 5."))
            if carrier.ontime_max_document_size_mb <= 0 or carrier.ontime_max_document_size_mb > 100:
                raise ValidationError(
                    _("The OnTime maximum document size must be greater than 0 and no more than 100 MB.")
                )

    @api.constrains("ontime_shipment_endpoint")
    def _check_ontime_shipment_endpoint(self):
        for carrier in self:
            endpoint = (carrier.ontime_shipment_endpoint or "").strip()
            if carrier.delivery_type == "ontime" and not endpoint:
                raise ValidationError(_("The OnTime shipment endpoint cannot be empty."))
            if endpoint and not endpoint.startswith("/"):
                raise ValidationError(_("The OnTime shipment endpoint must start with '/'."))

    @api.constrains(
        "ontime_label_endpoint",
        "ontime_tracking_endpoint",
        "ontime_shipment_detail_endpoint",
        "ontime_pod_endpoint",
        "ontime_cancellation_mode",
        "ontime_cancel_endpoint",
    )
    def _check_ontime_reference_endpoints(self):
        for carrier in self:
            if carrier.delivery_type != "ontime":
                continue
            required_fields = (
                "ontime_label_endpoint",
                "ontime_tracking_endpoint",
                "ontime_shipment_detail_endpoint",
            )
            for field_name in required_fields:
                template = (carrier[field_name] or "").strip()
                if not template:
                    raise ValidationError(_("The OnTime endpoint template cannot be empty."))
                if not template.startswith("/"):
                    raise ValidationError(_("OnTime API endpoint templates must start with '/'."))
                if "{reference}" not in template:
                    raise ValidationError(
                        _("OnTime shipment endpoint templates must contain {reference}.")
                    )

            pod_template = (carrier.ontime_pod_endpoint or "").strip()
            if pod_template:
                if not pod_template.startswith("/"):
                    raise ValidationError(_("OnTime API endpoint templates must start with '/'."))
                if "{reference}" not in pod_template:
                    raise ValidationError(
                        _("OnTime shipment endpoint templates must contain {reference}.")
                    )

            cancel_template = (carrier.ontime_cancel_endpoint or "").strip()
            if carrier.ontime_cancellation_mode == "api" and not cancel_template:
                raise ValidationError(
                    _("An OnTime cancellation endpoint is required when API cancellation is enabled.")
                )
            if cancel_template:
                if not cancel_template.startswith("/"):
                    raise ValidationError(_("OnTime API endpoint templates must start with '/'."))
                if "{reference}" not in cancel_template:
                    raise ValidationError(
                        _("OnTime shipment endpoint templates must contain {reference}.")
                    )

    @api.constrains("ontime_public_tracking_url")
    def _check_ontime_public_tracking_url(self):
        for carrier in self:
            url = (carrier.ontime_public_tracking_url or "").strip()
            if url and not url.startswith(("https://", "http://")):
                raise ValidationError(
                    _("The OnTime public tracking URL must start with http:// or https://.")
                )

    @api.constrains(
        "ontime_volumetric_divisor",
        "ontime_volumetric_factor",
        "ontime_max_package_weight_kg",
        "ontime_max_package_dimension_sum_cm",
        "ontime_max_length_cm",
        "ontime_max_width_cm",
        "ontime_max_height_cm",
    )
    def _check_ontime_rate_settings(self):
        for carrier in self:
            values = (
                carrier.ontime_volumetric_divisor,
                carrier.ontime_volumetric_factor,
                carrier.ontime_max_package_weight_kg,
                carrier.ontime_max_package_dimension_sum_cm,
                carrier.ontime_max_length_cm,
                carrier.ontime_max_width_cm,
                carrier.ontime_max_height_cm,
            )
            if any(value < 0 for value in values):
                raise ValidationError(_("OnTime tariff and dimension settings cannot be negative."))

    def _get_ontime_base_url(self):
        self.ensure_one()
        url = (self.ontime_base_url or "").strip().rstrip("/")
        if not url:
            raise UserError(_("Configure the Mensaglobal API base URL."))
        if not url.startswith("https://"):
            raise UserError(_("The Mensaglobal base URL must use HTTPS."))
        return url

    def _get_ontime_client(self):
        self.ensure_one()
        carrier_sudo = self.sudo()
        if not carrier_sudo.ontime_api_key:
            raise UserError(_("Configure the Mensaglobal API token before connecting."))
        return OnTimeClient(
            base_url=carrier_sudo._get_ontime_base_url(),
            api_key=carrier_sudo.ontime_api_key,
            timeout=carrier_sudo.ontime_timeout,
            read_retries=carrier_sudo.ontime_read_retries,
            max_document_bytes=int(carrier_sudo.ontime_max_document_size_mb * 1024 * 1024),
        )

    @staticmethod
    def _format_ontime_api_error(error):
        internal_messages = {
            "MISSING_API_KEY": _("Mensaglobal API token is not configured."),
            "TIMEOUT": _("Timeout while connecting to Mensaglobal."),
            "CONNECTION_ERROR": _("Could not connect to the Mensaglobal API."),
            "HTTP_ERROR": _("Unexpected HTTP error while connecting to Mensaglobal."),
            "DOCUMENT_TOO_LARGE": _("The OnTime document exceeds the configured maximum size."),
            "TOO_MANY_REDIRECTS": _("Too many redirects while downloading OnTime data."),
            "UNSAFE_REDIRECT": _("Mensaglobal returned an unsafe download redirect."),
            "UNEXPECTED_REDIRECT": _("Mensaglobal returned an unexpected HTTP redirect."),
        }
        message = internal_messages.get(error.error_code) or error.message
        details = []
        if error.error_code:
            details.append(_("code: %s") % error.error_code)
        if error.status_code:
            details.append(_("HTTP: %s") % error.status_code)
        if error.correlation_id:
            details.append(_("correlationId: %s") % error.correlation_id)
        suffix = " (%s)" % ", ".join(details) if details else ""
        return "%s%s" % (message, suffix)

    def _ontime_lock_picking(self, picking):
        """Serialize OnTime side effects for one picking inside this transaction."""
        self.ensure_one()
        if not picking.id:
            return
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (ONTIME_PICKING_LOCK_NAMESPACE, int(picking.id)),
        )
        # Another transaction may have completed while we waited for the lock.
        # Drop cached lifecycle fields so duplicate prevention uses fresh data.
        field_names = [
            "ontime_shipment_reference",
            "carrier_tracking_ref",
            "ontime_operation_state",
            "ontime_shipment_cancelled_at",
            "ontime_shipment_status",
            "ontime_label_attachment_id",
            "ontime_pod_attachment_id",
        ]
        available = [name for name in field_names if name in picking._fields]
        if available:
            picking.invalidate_recordset(available)

    def _ontime_lock_carrier(self):
        self.ensure_one()
        if self.id:
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (ONTIME_CARRIER_LOCK_NAMESPACE, int(self.id)),
            )

    def _ontime_reference_duplicate(self, picking, reference):
        self.ensure_one()
        reference = str(reference or "").strip()
        if not reference:
            return self.env["stock.picking"]
        return self.env["stock.picking"].sudo().search(
            [
                ("id", "!=", picking.id),
                ("company_id", "=", picking.company_id.id),
                ("ontime_shipment_reference", "=", reference),
            ],
            limit=1,
        )

    def _ontime_assert_reference_available(self, picking, reference):
        self.ensure_one()
        duplicate = self._ontime_reference_duplicate(picking, reference)
        if duplicate:
            raise UserError(
                _(
                    "OnTime shipment reference %(reference)s is already linked to picking "
                    "%(picking)s in this company."
                )
                % {"reference": reference, "picking": duplicate.display_name}
            )

    def _ontime_effective_company(self, auto_assign=False):
        """Return the carrier company, implicitly resolving single-company databases.

        ``delivery.carrier.company_id`` may legitimately be empty in a database that
        has always had a single company (the field is hidden unless multi-company is
        enabled). In that case there is no ambiguity: use the sole active company and,
        when requested, persist it on the carrier so a future multi-company conversion
        keeps the original credentials/contract correctly isolated.
        """
        self.ensure_one()
        if self.company_id:
            return self.company_id

        companies = self.env["res.company"].sudo().search([], limit=2)
        if len(companies) == 1:
            company = companies
            if auto_assign and self.id:
                self.sudo().write({"company_id": company.id})
                self.invalidate_recordset(["company_id"])
            return company

        return self.env["res.company"]

    def _ontime_shipping_taxes_for_company(self, company=None):
        """Return delivery-product sales taxes applicable to the carrier company."""
        self.ensure_one()
        company = company or self._ontime_effective_company(auto_assign=True)
        if not company or not self.product_id:
            return self.env["account.tax"]
        return self.product_id.taxes_id._filter_taxes_by_company(company)

    def _ontime_ensure_shipping_sale_tax(self):
        """Ensure the delivery product has a company sales tax.

        Odoo itself applies delivery-line taxes from ``delivery.carrier.product_id``
        and maps them through the order fiscal position. The carrier rate must stay
        tax-exclusive; adding VAT manually here would double-tax some orders and
        break fiscal-position behavior.
        """
        self.ensure_one()
        if self.delivery_type != "ontime" or not self.product_id:
            return self.env["account.tax"]
        company = self._ontime_effective_company(auto_assign=True)
        if not company:
            return self.env["account.tax"]
        taxes = self._ontime_shipping_taxes_for_company(company)
        if taxes:
            return taxes
        default_tax = company.account_sale_tax_id
        if default_tax:
            self.product_id.sudo().write({"taxes_id": [(4, default_tax.id)]})
            self.product_id.invalidate_recordset(["taxes_id"])
            taxes = self._ontime_shipping_taxes_for_company(company)
        return taxes

    def _ontime_validate_company(self, business_record=None):
        """Keep credentials/contracts isolated only when company ambiguity exists."""
        self.ensure_one()
        carrier_company = self._ontime_effective_company(auto_assign=True)
        if not carrier_company:
            raise UserError(
                _(
                    "Assign a company to the OnTime carrier. API credentials and the imported "
                    "contract must not be shared implicitly between companies."
                )
            )

        record_company = getattr(business_record, "company_id", False) if business_record else False
        if record_company and record_company != carrier_company:
            raise UserError(
                _(
                    "The OnTime carrier belongs to company '%(carrier_company)s' but the document "
                    "belongs to '%(document_company)s'. Use an OnTime carrier configured for the "
                    "same company."
                )
                % {
                    "carrier_company": carrier_company.display_name,
                    "document_company": record_company.display_name,
                }
            )
        return True

    def _ontime_configuration_errors(self):
        self.ensure_one()
        errors = []
        if self.delivery_type != "ontime":
            errors.append(_("Carrier type is not OnTime."))
            return errors
        if not self._ontime_effective_company(auto_assign=True):
            errors.append(_("Assign a company to the OnTime carrier."))
        if not self.ontime_tariff_rule_ids:
            errors.append(_("Import the current OnTime tariff PDF."))
        if not self._ontime_ensure_shipping_sale_tax():
            errors.append(
                _(
                    "Configure a sales tax on the OnTime delivery product or a default sales "
                    "tax on the carrier company."
                )
            )
        if not (self.ontime_api_service_economy or "").strip():
            errors.append(_("Configure the Mensaglobal service code for XS Economy."))
        if not (self.ontime_api_service_xs24 or "").strip():
            errors.append(_("Configure the Mensaglobal fallback service code."))
        if self.ontime_mode in ("test", "real"):
            if not self.sudo().ontime_api_key:
                errors.append(_("Configure the Mensaglobal API token for API Test or Production mode."))
            try:
                self._get_ontime_base_url()
            except UserError as error:
                errors.append(str(error))

        product_models = (self.env["product.product"], self.env["product.template"])
        for field_name in ("shipping_length_mm", "shipping_width_mm", "shipping_height_mm"):
            if not any(field_name in model._fields for model in product_models):
                errors.append(
                    _("Required Optima product dimension field is missing: %s") % field_name
                )
        return errors

    def action_ontime_validate_configuration(self):
        self.ensure_one()
        errors = self._ontime_configuration_errors()
        if errors:
            raise UserError(
                _("OnTime configuration is not ready:\n- %s") % "\n- ".join(errors)
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OnTime configuration validated"),
                "message": _(
                    "Company isolation, shipping taxes, tariff, Mensaglobal service codes, base URL and product dimensions are configured."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def _ontime_api_request(self, method, path, **kwargs):
        self.ensure_one()
        if self.ontime_mode not in ("test", "real"):
            raise UserError(_("OnTime API calls are disabled while the carrier is in Simulated mode."))
        try:
            return self._get_ontime_client().request(method, path, **kwargs)
        except OnTimeAPIError as error:
            raise UserError(
                _("OnTime API communication failed: %s") % self._format_ontime_api_error(error)
            ) from error

    def action_ontime_test_connection(self):
        self.ensure_one()
        if self.delivery_type != "ontime":
            raise UserError(_("This action is only available for OnTime carriers."))
        self._ontime_validate_company()
        if self.ontime_mode not in ("test", "real"):
            raise UserError(_("Switch OnTime Mode to API Test or Production before testing the connection."))

        client = self._get_ontime_client()
        endpoint = self._ontime_reference_endpoint(
            self.ontime_tracking_endpoint, ONTIME_CONNECTION_TEST_REFERENCE
        )
        try:
            client.request("GET", endpoint)
        except OnTimeAPIError as error:
            # Mensaglobal business validation errors are returned as HTTP 200 with
            # success=false. For a deliberately non-existent shipment that still
            # proves that the Bearer token was accepted and the API was reached.
            if error.status_code != 200:
                raise UserError(
                    _("Mensaglobal connection test failed: %s")
                    % self._format_ontime_api_error(error)
                ) from error

        mode_label = dict(self._fields["ontime_mode"].selection).get(
            self.ontime_mode,
            self.ontime_mode,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Mensaglobal connection successful"),
                "message": _("Bearer authentication and API access are working correctly in %s mode.")
                % mode_label,
                "type": "success",
                "sticky": False,
            },
        }

    # ------------------------------------------------------------------
    # Phase 3 - official PDF import
    # ------------------------------------------------------------------
    def action_ontime_import_tariff(self):
        self.ensure_one()
        if self.delivery_type != "ontime":
            raise UserError(_("This action is only available for OnTime carriers."))
        self._ontime_validate_company()
        if not self.ontime_tariff_file:
            raise UserError(_("Select the official OnTime tariff PDF before importing."))
        filename = (self.ontime_tariff_filename or "").lower()
        if filename and not filename.endswith(".pdf"):
            raise UserError(_("The OnTime tariff must be uploaded as a PDF file."))

        try:
            payload = base64.b64decode(self.ontime_tariff_file)
        except Exception as exc:
            raise UserError(_("The uploaded OnTime tariff file is not valid.")) from exc

        try:
            parsed = OnTimeTariffPDFParser(payload).parse()
        except OnTimeTariffPDFError as exc:
            raise UserError(str(exc)) from exc

        vals_list = [dict(rate, carrier_id=self.id, active=True) for rate in parsed["rates"]]
        if not vals_list:
            raise UserError(_("No OnTime rates were found in the PDF."))

        # Replace only after the complete PDF has been parsed and validated.
        # Serialize concurrent imports so one contract cannot partially overwrite another.
        self._ontime_lock_carrier()
        self.invalidate_recordset(["ontime_tariff_rule_ids"])
        self.ontime_tariff_rule_ids.sudo().unlink()
        self.env["delivery.ontime.tariff.rule"].sudo().create(vals_list)
        self.write(
            {
                "ontime_tariff_source_hash": hashlib.sha256(payload).hexdigest(),
                "ontime_tariff_imported_at": fields.Datetime.now(),
                "ontime_tariff_year": parsed.get("year") or False,
            }
        )

        economy_count = len([rate for rate in vals_list if rate["service"] == SERVICE_ECONOMY])
        xs24_count = len([rate for rate in vals_list if rate["service"] == SERVICE_XS24])
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OnTime tariff imported"),
                "message": _(
                    "Imported %(economy)s XS ECONOMY 24-48h rates and %(xs24)s XS 24h fallback rates."
                )
                % {"economy": economy_count, "xs24": xs24_count},
                "type": "success",
                "sticky": False,
            },
        }

    # ------------------------------------------------------------------
    # Phase 3 - zoning (same Provincial/Regional logic as supplied GLS)
    # ------------------------------------------------------------------
    @staticmethod
    def _ontime_postal_digits(value):
        return "".join(char for char in str(value or "") if char.isdigit())

    @staticmethod
    def _ontime_prefix_set(value, width=None):
        prefixes = set()
        for item in re.split(r"[,;\s]+", value or ""):
            digits = "".join(char for char in item if char.isdigit())
            if not digits:
                continue
            prefixes.add(digits[:width] if width else digits)
        return prefixes

    def _ontime_resolve_zone(self, partner):
        self.ensure_one()
        country_code = (partner.country_id.code or "").upper()
        if country_code != "ES":
            raise UserError(_("OnTime home delivery is configured only for Spain."))

        postal = self._ontime_postal_digits(partner.zip)
        if len(postal) != 5:
            raise UserError(_("A valid 5-digit Spanish postal code is required for OnTime."))
        province_prefix = postal[:2]
        three_prefix = postal[:3]

        # Explicit Spanish exceptions always have priority over mainland zoning.
        if province_prefix == "51":
            return ZONE_CEUTA
        if province_prefix == "52":
            return ZONE_MELILLA
        if province_prefix == "07":
            minor = self._ontime_prefix_set(self.ontime_baleares_minor_prefixes, 3)
            return ZONE_BALEARES_MENORES if three_prefix in minor else ZONE_BALEARES_MAYORES
        if province_prefix in {"35", "38"}:
            major = self._ontime_prefix_set(self.ontime_canarias_major_prefixes, 3)
            return ZONE_CANARIAS_MAYORES if three_prefix in major else ZONE_CANARIAS_MENORES

        origin_digits = self._ontime_postal_digits(self.ontime_origin_postal_code)
        if len(origin_digits) < 2:
            raise UserError(_("Configure a valid OnTime tariff origin postal code."))
        if province_prefix == origin_digits[:2]:
            return ZONE_PROVINCIAL

        regional = self._ontime_prefix_set(self.ontime_regional_postal_prefixes, 2)
        if province_prefix in regional:
            return ZONE_REGIONAL
        return ZONE_IBERIA

    # ------------------------------------------------------------------
    # Phase 3 - weight, restrictions and local quotation
    # ------------------------------------------------------------------
    def _ontime_shipping_lines(self, order):
        return order.order_line.filtered(
            lambda line: line.state != "cancel"
            and not line.is_delivery
            and line.product_id
            and line.product_id.type not in {"service", "combo"}
            and line.product_uom_qty > 0
        )

    def _ontime_weight_to_kg(self, value):
        """Convert Odoo's configured product weight unit to kilograms."""
        value = float(value or 0.0)
        if not value:
            return 0.0
        try:
            source_uom = self.env["product.template"]._get_weight_uom_id_from_ir_config_parameter()
            kg_uom = self.env.ref("uom.product_uom_kgm")
            return source_uom._compute_quantity(value, kg_uom)
        except Exception:
            # Existing Optima installations use kilograms. Keep a safe fallback
            # rather than breaking shipment creation if a custom UoM module alters
            # the helper availability.
            return value

    @staticmethod
    def _ontime_length_to_cm(value, uom_name=None):
        value = float(value or 0.0)
        if not value:
            return 0.0
        unit = str(uom_name or "mm").strip().lower().replace(" ", "")
        if unit in {"mm", "millimeter", "millimeters", "milímetro", "milímetros"}:
            return value / 10.0
        if unit in {"cm", "centimeter", "centimeters", "centímetro", "centímetros"}:
            return value
        if unit in {"m", "meter", "meters", "metro", "metros"}:
            return value * 100.0
        if unit in {"in", "inch", "inches", '"'}:
            return value * 2.54
        if unit in {"ft", "foot", "feet", "pie", "pies", "'"}:
            return value * 30.48
        # Odoo 18 documents package-type dimensions in millimetres.
        return value / 10.0

    def _ontime_product_dimensions_cm(self, product):
        """Return Optima custom product dimensions converted from mm to cm.

        The installation already stores logistics dimensions in:
        shipping_length_mm, shipping_width_mm and shipping_height_mm.
        The fields may live on product.product or product.template depending on
        the custom module, so support both without declaring duplicate fields.
        """
        self.ensure_one()
        field_names = (
            "shipping_length_mm",
            "shipping_width_mm",
            "shipping_height_mm",
        )
        values_mm = []
        missing_fields = []
        template = getattr(product, "product_tmpl_id", False)
        for field_name in field_names:
            if field_name in product._fields:
                value = product[field_name]
            elif template and field_name in template._fields:
                value = template[field_name]
            else:
                missing_fields.append(field_name)
                value = 0.0
            try:
                value = float(value or 0.0)
            except (TypeError, ValueError):
                raise UserError(
                    _("Product dimension field '%(field)s' must contain a numeric value.")
                    % {"field": field_name}
                )
            if value < 0:
                raise UserError(
                    _("Product '%(product)s' has a negative value in %(field)s.")
                    % {"product": product.display_name, "field": field_name}
                )
            values_mm.append(value)

        if missing_fields:
            raise UserError(
                _(
                    "OnTime requires the existing Optima product dimension fields: %(fields)s."
                )
                % {"fields": ", ".join(missing_fields)}
            )

        return tuple(value / 10.0 for value in values_mm)

    def _ontime_volumetric_weight_kg(self, length_cm, width_cm, height_cm, qty=1.0):
        self.ensure_one()
        if not self.ontime_volumetric_divisor:
            return 0.0
        return (
            float(length_cm or 0.0)
            * float(width_cm or 0.0)
            * float(height_cm or 0.0)
            * float(qty or 0.0)
            / self.ontime_volumetric_divisor
        )

    def _ontime_validate_dimensions(self, label, length, width, height, package=False):
        self.ensure_one()
        if min(length, width, height) <= 0:
            raise UserError(
                _("%(label)s has no complete dimensions for OnTime.") % {"label": label}
            )
        if self.ontime_max_length_cm and length > self.ontime_max_length_cm:
            raise UserError(
                _("%(label)s exceeds the OnTime maximum length (%(limit)s cm).")
                % {"label": label, "limit": self.ontime_max_length_cm}
            )
        if self.ontime_max_width_cm and width > self.ontime_max_width_cm:
            raise UserError(
                _("%(label)s exceeds the OnTime maximum width (%(limit)s cm).")
                % {"label": label, "limit": self.ontime_max_width_cm}
            )
        if self.ontime_max_height_cm and height > self.ontime_max_height_cm:
            raise UserError(
                _("%(label)s exceeds the OnTime maximum height (%(limit)s cm).")
                % {"label": label, "limit": self.ontime_max_height_cm}
            )
        if package and self.ontime_max_package_dimension_sum_cm:
            combined = length + width + height
            if combined > self.ontime_max_package_dimension_sum_cm:
                raise UserError(
                    _(
                        "%(label)s exceeds the OnTime XS combined-dimension limit: "
                        "%(combined).2f cm (L+W+H), maximum %(limit).2f cm."
                    )
                    % {
                        "label": label,
                        "combined": combined,
                        "limit": self.ontime_max_package_dimension_sum_cm,
                    }
                )

    def _ontime_get_order_metrics(self, order):
        self.ensure_one()
        actual_weight = 0.0
        volumetric_weight = 0.0
        cubic_meters = 0.0
        missing_weights = []
        missing_dimensions = []
        dimensions_needed = bool(
            self.ontime_require_dimensions
            or self.ontime_volumetric_divisor
            or self.ontime_max_package_dimension_sum_cm
            or self.ontime_max_length_cm
            or self.ontime_max_width_cm
            or self.ontime_max_height_cm
        )

        for line in self._ontime_shipping_lines(order):
            product = line.product_id
            qty = line.product_uom._compute_quantity(line.product_uom_qty, product.uom_id)
            unit_weight = self._ontime_weight_to_kg(product.weight or 0.0)
            if self.ontime_require_weight and unit_weight <= 0:
                missing_weights.append(product.display_name)
            if (
                self.ontime_max_package_weight_kg
                and unit_weight > self.ontime_max_package_weight_kg
            ):
                raise UserError(
                    _(
                        "Product '%(product)s' weighs %(weight).3f kg per unit, above the "
                        "OnTime XS limit of %(limit).3f kg per package."
                    )
                    % {
                        "product": product.display_name,
                        "weight": unit_weight,
                        "limit": self.ontime_max_package_weight_kg,
                    }
                )
            actual_weight += unit_weight * qty

            length, width, height = self._ontime_product_dimensions_cm(product)
            if dimensions_needed and (length <= 0 or width <= 0 or height <= 0):
                missing_dimensions.append(product.display_name)
                continue
            if length and width and height:
                self._ontime_validate_dimensions(
                    _("Product '%s'") % product.display_name,
                    length, width, height,
                    package=True,
                )
                cubic_meters += (length * width * height * qty) / 1_000_000.0
                volumetric_weight += self._ontime_volumetric_weight_kg(
                    length, width, height, qty
                )

        if missing_weights:
            raise UserError(
                _("Products without weight for OnTime: %s")
                % ", ".join(sorted(set(missing_weights)))
            )
        if missing_dimensions:
            raise UserError(
                _("Products without complete OnTime dimensions: %s")
                % ", ".join(sorted(set(missing_dimensions)))
            )

        order_weight = self.env.context.get("order_weight") or getattr(order, "shipping_weight", 0.0)
        if order_weight:
            actual_weight = self._ontime_weight_to_kg(order_weight)
        if actual_weight <= 0:
            raise UserError(_("The order has no billable weight for OnTime."))

        billable_weight = max(actual_weight, volumetric_weight)
        if self.max_weight and actual_weight > self.max_weight:
            raise UserError(
                _("The order weight (%(weight).3f kg) exceeds the carrier maximum (%(limit).3f kg).")
                % {"weight": actual_weight, "limit": self.max_weight}
            )

        estimated_packages = 1
        if self.ontime_max_package_weight_kg:
            estimated_packages = max(
                1, math.ceil(actual_weight / self.ontime_max_package_weight_kg)
            )
        return {
            "actual_weight": actual_weight,
            "cubic_meters": cubic_meters,
            "volumetric_weight": volumetric_weight,
            "billable_weight": billable_weight,
            "package_count": estimated_packages,
        }

    def _ontime_rates_for(self, service, zone):
        self.ensure_one()
        return self.ontime_tariff_rule_ids.sudo().filtered(
            lambda rate: rate.active and rate.service == service and rate.zone == zone
        )

    def _ontime_compute_contract_price(self, zone, billable_weight):
        self.ensure_one()
        rate_model = self.env["delivery.ontime.tariff.rule"]

        # The imported 2024 PDF uses the historic Economy/XS24 tariff buckets.
        # At API level these map to the current codes supplied by OnTime: 72 for
        # XS Economy 48/72 and 24 for the 19Horas XS fallback. The customer never
        # chooses the API service.
        economy_rates = self._ontime_rates_for(SERVICE_ECONOMY, zone)
        economy_price = rate_model.compute_group_price(economy_rates, billable_weight)
        if economy_price is not False:
            return economy_price, SERVICE_ECONOMY

        xs24_rates = self._ontime_rates_for(SERVICE_XS24, zone)
        xs24_price = rate_model.compute_group_price(xs24_rates, billable_weight)
        if xs24_price is not False:
            return xs24_price, SERVICE_XS24

        raise UserError(
            _("The imported OnTime contract has no rate for zone %(zone)s and weight %(weight).3f kg.")
            % {"zone": zone, "weight": billable_weight}
        )

    def ontime_rate_shipment(self, order):
        self.ensure_one()
        try:
            self._ontime_validate_company(order)
            self._ontime_ensure_shipping_sale_tax()
        except UserError as error:
            return {
                "success": False,
                "price": 0.0,
                "error_message": error.args[0],
                "warning_message": False,
            }
        if not self._match_address(order.partner_shipping_id):
            return {
                "success": False,
                "price": 0.0,
                "error_message": _("OnTime is not available for the delivery address."),
                "warning_message": False,
            }
        try:
            if not self.ontime_tariff_rule_ids:
                raise UserError(_("Import the current OnTime tariff PDF before quoting this carrier."))
            metrics = self._ontime_get_order_metrics(order)
            zone = self._ontime_resolve_zone(order.partner_shipping_id)
            price, _service = self._ontime_compute_contract_price(zone, metrics["billable_weight"])
        except UserError as error:
            return {
                "success": False,
                "price": 0.0,
                "error_message": error.args[0],
                "warning_message": False,
            }

        warnings = []
        if metrics["volumetric_weight"] > metrics["actual_weight"]:
            warnings.append(
                _("OnTime rate uses volumetric weight: %(billable).3f kg (actual: %(actual).3f kg).")
                % {
                    "billable": metrics["billable_weight"],
                    "actual": metrics["actual_weight"],
                }
            )
        return {
            "success": True,
            "price": price,
            "error_message": False,
            "warning_message": " ".join(warnings) if warnings else False,
        }

    # ------------------------------------------------------------------
    # Phase 4 - real shipment creation
    # ------------------------------------------------------------------
    @staticmethod
    def _ontime_safe_text(value, limit=None):
        value = " ".join(str(value or "").split())
        if limit and len(value) > limit:
            return value[:limit]
        return value

    def _ontime_validate_shipment_partner(self, partner):
        self.ensure_one()
        missing = []
        if not partner.name:
            missing.append(_("recipient name"))
        if not partner.street:
            missing.append(_("street"))
        if not partner.zip:
            missing.append(_("postal code"))
        if not partner.city:
            missing.append(_("city"))
        if not (partner.phone or partner.mobile):
            missing.append(_("phone"))
        if missing:
            raise UserError(
                _("Complete the following delivery data before creating the OnTime shipment: %s")
                % ", ".join(missing)
            )
        # Reuse the exact Spain/postcode validation from tariff zoning.
        self._ontime_resolve_zone(partner)

    @staticmethod
    def _ontime_picking_move_qty(move):
        """Quantity represented by a stock move, expressed in move UoM.

        Odoo can call the carrier before or after validation depending on the
        workflow. Prefer the processed quantity when available and otherwise
        fall back to the demanded move quantity.
        """
        quantity = getattr(move, "quantity", 0.0) or 0.0
        if quantity <= 0:
            quantity = getattr(move, "product_uom_qty", 0.0) or 0.0
        return quantity

    def _ontime_move_line_qty_in_product_uom(self, line):
        quantity = getattr(line, "quantity", 0.0) or 0.0
        product = line.product_id
        if not product or quantity <= 0:
            return 0.0
        uom = getattr(line, "product_uom_id", False) or product.uom_id
        return uom._compute_quantity(quantity, product.uom_id)

    def _ontime_package_dimensions_cm(self, package):
        package_type = package.package_type_id
        if not package_type:
            raise UserError(
                _(
                    "Package '%s' has no Package Type. Assign a package type with dimensions "
                    "before creating the OnTime shipment."
                )
                % package.display_name
            )
        uom_name = getattr(package_type, "length_uom_name", False)
        length = self._ontime_length_to_cm(package_type.packaging_length, uom_name)
        width = self._ontime_length_to_cm(package_type.width, uom_name)
        height = self._ontime_length_to_cm(package_type.height, uom_name)
        self._ontime_validate_dimensions(
            _("Package '%s'") % package.display_name,
            length, width, height,
            package=True,
        )
        return length, width, height

    def _ontime_product_lines_metrics(self, lines, label_prefix=None):
        actual = 0.0
        volumetric = 0.0
        cubic = 0.0
        missing_weights = []
        missing_dimensions = []
        for line in lines:
            product = line.product_id
            qty = self._ontime_move_line_qty_in_product_uom(line)
            if not product or qty <= 0 or product.type in {"service", "combo"}:
                continue
            unit_weight = self._ontime_weight_to_kg(product.weight or 0.0)
            if self.ontime_require_weight and unit_weight <= 0:
                missing_weights.append(product.display_name)
            if self.ontime_max_package_weight_kg and unit_weight > self.ontime_max_package_weight_kg:
                raise UserError(
                    _(
                        "Product '%(product)s' weighs %(weight).3f kg per unit, above the "
                        "OnTime XS limit of %(limit).3f kg per package."
                    )
                    % {
                        "product": product.display_name,
                        "weight": unit_weight,
                        "limit": self.ontime_max_package_weight_kg,
                    }
                )
            actual += unit_weight * qty
            length, width, height = self._ontime_product_dimensions_cm(product)
            if (
                self.ontime_require_dimensions
                or self.ontime_volumetric_divisor
                or self.ontime_max_package_dimension_sum_cm
                or self.ontime_max_length_cm
                or self.ontime_max_width_cm
                or self.ontime_max_height_cm
            ) and (length <= 0 or width <= 0 or height <= 0):
                missing_dimensions.append(product.display_name)
                continue
            if length and width and height:
                self._ontime_validate_dimensions(
                    _("Product '%s'") % product.display_name,
                    length, width, height,
                    package=True,
                )
                cubic += (length * width * height * qty) / 1_000_000.0
                volumetric += self._ontime_volumetric_weight_kg(length, width, height, qty)
        if missing_weights:
            raise UserError(
                _("Products without weight for OnTime: %s")
                % ", ".join(sorted(set(missing_weights)))
            )
        if missing_dimensions:
            raise UserError(
                _("Products without complete OnTime dimensions: %s")
                % ", ".join(sorted(set(missing_dimensions)))
            )
        return actual, volumetric, cubic

    def _ontime_get_picking_metrics(self, picking):
        self.ensure_one()
        move_lines = getattr(picking, "move_line_ids", self.env["stock.move.line"]).filtered(
            lambda line: line.product_id
            and line.product_id.type not in {"service", "combo"}
            and self._ontime_move_line_qty_in_product_uom(line) > 0
        )
        packages = move_lines.mapped("result_package_id")
        declared_packages = int(getattr(picking, "number_of_packages", 0) or 0)

        # When the warehouse has prepared real Odoo packages, they become the
        # source of truth for per-package XS validation and volumetric weight.
        if packages:
            package_weights = packages._get_weight(picking.id)
            actual_weight = 0.0
            volumetric_weight = 0.0
            billable_weight = 0.0
            cubic_meters = 0.0
            for package in packages:
                raw_weight = package.shipping_weight or package_weights.get(package, 0.0)
                package_weight = self._ontime_weight_to_kg(raw_weight)
                if package_weight <= 0:
                    raise UserError(
                        _("Package '%s' has no valid shipping weight for OnTime.")
                        % package.display_name
                    )
                if (
                    self.ontime_max_package_weight_kg
                    and package_weight > self.ontime_max_package_weight_kg
                ):
                    raise UserError(
                        _(
                            "Package '%(package)s' weighs %(weight).3f kg, above the OnTime XS "
                            "limit of %(limit).3f kg per package."
                        )
                        % {
                            "package": package.display_name,
                            "weight": package_weight,
                            "limit": self.ontime_max_package_weight_kg,
                        }
                    )
                length, width, height = self._ontime_package_dimensions_cm(package)
                package_volumetric = self._ontime_volumetric_weight_kg(length, width, height)
                actual_weight += package_weight
                volumetric_weight += package_volumetric
                billable_weight += max(package_weight, package_volumetric)
                cubic_meters += (length * width * height) / 1_000_000.0

            # Any move lines left outside a result package are treated as an
            # estimated loose shipment. They must still comply with product-level
            # XS limits and may require one or more additional packages by weight.
            loose_lines = move_lines.filtered(lambda line: not line.result_package_id)
            loose_actual, loose_volumetric, loose_cubic = self._ontime_product_lines_metrics(loose_lines)
            actual_weight += loose_actual
            volumetric_weight += loose_volumetric
            billable_weight += max(loose_actual, loose_volumetric)
            cubic_meters += loose_cubic

            loose_packages = 0
            if loose_actual > 0:
                loose_packages = 1
                if self.ontime_max_package_weight_kg:
                    loose_packages = max(
                        1, math.ceil(loose_actual / self.ontime_max_package_weight_kg)
                    )
            minimum_packages = len(packages) + loose_packages
            if declared_packages and declared_packages < minimum_packages:
                raise UserError(
                    _(
                        "The picking declares %(declared)s package(s), but OnTime XS requires at "
                        "least %(minimum)s for the prepared/loose weight."
                    )
                    % {"declared": declared_packages, "minimum": minimum_packages}
                )
            package_count = minimum_packages
        else:
            # No real packages yet: estimate from product data. This keeps checkout
            # and simple warehouse flows working, but validates the minimum package
            # count required by the 30 kg-per-package operational limit.
            moves = picking.move_ids.filtered(
                lambda move: move.state != "cancel"
                and move.product_id
                and move.product_id.type not in {"service", "combo"}
                and self._ontime_picking_move_qty(move) > 0
            )
            actual_weight = 0.0
            volumetric_weight = 0.0
            cubic_meters = 0.0
            missing_weights = []
            missing_dimensions = []
            for move in moves:
                product = move.product_id
                qty = move.product_uom._compute_quantity(
                    self._ontime_picking_move_qty(move), product.uom_id
                )
                unit_weight = self._ontime_weight_to_kg(product.weight or 0.0)
                if self.ontime_require_weight and unit_weight <= 0:
                    missing_weights.append(product.display_name)
                if self.ontime_max_package_weight_kg and unit_weight > self.ontime_max_package_weight_kg:
                    raise UserError(
                        _(
                            "Product '%(product)s' weighs %(weight).3f kg per unit, above the "
                            "OnTime XS limit of %(limit).3f kg per package."
                        )
                        % {
                            "product": product.display_name,
                            "weight": unit_weight,
                            "limit": self.ontime_max_package_weight_kg,
                        }
                    )
                actual_weight += unit_weight * qty
                length, width, height = self._ontime_product_dimensions_cm(product)
                dimensions_needed = bool(
                    self.ontime_require_dimensions
                    or self.ontime_volumetric_divisor
                    or self.ontime_max_package_dimension_sum_cm
                    or self.ontime_max_length_cm
                    or self.ontime_max_width_cm
                    or self.ontime_max_height_cm
                )
                if dimensions_needed and (length <= 0 or width <= 0 or height <= 0):
                    missing_dimensions.append(product.display_name)
                    continue
                if length and width and height:
                    self._ontime_validate_dimensions(
                        _("Product '%s'") % product.display_name,
                        length, width, height,
                        package=True,
                    )
                    cubic_meters += (length * width * height * qty) / 1_000_000.0
                    volumetric_weight += self._ontime_volumetric_weight_kg(
                        length, width, height, qty
                    )
            if missing_weights:
                raise UserError(
                    _("Products without weight for OnTime: %s")
                    % ", ".join(sorted(set(missing_weights)))
                )
            if missing_dimensions:
                raise UserError(
                    _("Products without complete OnTime dimensions: %s")
                    % ", ".join(sorted(set(missing_dimensions)))
                )
            picking_weight = getattr(picking, "shipping_weight", 0.0) or 0.0
            if picking_weight > 0:
                actual_weight = self._ontime_weight_to_kg(picking_weight)
            if actual_weight <= 0:
                raise UserError(_("The picking has no billable weight for OnTime."))
            billable_weight = max(actual_weight, volumetric_weight)
            minimum_packages = 1
            if self.ontime_max_package_weight_kg:
                minimum_packages = max(
                    1, math.ceil(actual_weight / self.ontime_max_package_weight_kg)
                )
            if declared_packages and declared_packages < minimum_packages:
                raise UserError(
                    _(
                        "The picking declares %(declared)s package(s), but %(weight).3f kg requires "
                        "at least %(minimum)s package(s) with the OnTime XS limit of %(limit).3f kg each."
                    )
                    % {
                        "declared": declared_packages,
                        "weight": actual_weight,
                        "minimum": minimum_packages,
                        "limit": self.ontime_max_package_weight_kg,
                    }
                )
            package_count = declared_packages or minimum_packages

        if self.max_weight and actual_weight > self.max_weight:
            raise UserError(
                _("The picking weight (%(weight).3f kg) exceeds the carrier maximum (%(limit).3f kg).")
                % {"weight": actual_weight, "limit": self.max_weight}
            )
        return {
            "actual_weight": actual_weight,
            "cubic_meters": cubic_meters,
            "volumetric_weight": volumetric_weight,
            "billable_weight": billable_weight,
            "package_count": package_count,
        }

    def _ontime_api_service_value(self, service):
        self.ensure_one()
        if service == SERVICE_ECONOMY:
            value = self.ontime_api_service_economy
        elif service == SERVICE_XS24:
            value = self.ontime_api_service_xs24
        else:
            value = False
        if not value:
            raise UserError(
                _("Configure the OnTime API product/service code for the selected tariff service.")
            )
        return value.strip()

    def _ontime_origin_partner(self, picking):
        self.ensure_one()
        warehouse = getattr(picking.picking_type_id, "warehouse_id", False)
        warehouse_partner = getattr(warehouse, "partner_id", False) if warehouse else False
        if warehouse_partner and warehouse_partner.street and warehouse_partner.zip and warehouse_partner.city:
            return warehouse_partner
        return picking.company_id.partner_id

    def _ontime_mensaglobal_address(self, partner, *, role, name_override=None):
        self.ensure_one()
        missing = []
        if not partner.name:
            missing.append(_("name"))
        if not partner.street:
            missing.append(_("street"))
        if not partner.zip:
            missing.append(_("postal code"))
        if not partner.city:
            missing.append(_("city"))
        if missing:
            raise UserError(
                _("Complete the %(role)s address before creating the OnTime shipment: %(fields)s")
                % {"role": role, "fields": ", ".join(missing)}
            )
        country = (partner.country_id.code or "ES") if partner.country_id else "ES"
        values = {
            "nombre": self._ontime_safe_text(name_override or partner.name, 120),
            "direccion": self._ontime_safe_text(
                ", ".join(part for part in (partner.street, partner.street2) if part), 200
            ),
            "cp": self._ontime_safe_text(partner.zip, 16),
            "localidad": self._ontime_safe_text(partner.city, 100),
            "pais": self._ontime_safe_text(country, 3),
        }
        phone = partner.phone or partner.mobile
        if partner.state_id:
            values["provincia"] = self._ontime_safe_text(partner.state_id.name, 100)
        if phone:
            values["telefono"] = self._ontime_safe_text(phone, 40)
        if partner.email:
            values["email"] = self._ontime_safe_text(partner.email, 120)
        return values

    @staticmethod
    def _ontime_split_weight(total_weight, count):
        count = max(int(count or 1), 1)
        total_weight = max(float(total_weight or 0.0), 0.001)
        each = round(total_weight / count, 3)
        weights = [each] * count
        weights[-1] = round(max(total_weight - sum(weights[:-1]), 0.001), 3)
        return weights

    def _ontime_prepare_api_packages(self, picking, metrics):
        """Prepare Mensaglobal ``bultos`` without inventing package geometry.

        Real Odoo packages carry exact weight and Package Type dimensions and are
        sent verbatim. When the warehouse has not packed the picking yet, only
        weights are sent unless one product unit maps unambiguously to one bulto.
        This avoids fabricating dimensions for a mixed carton.
        """
        self.ensure_one()
        move_lines = getattr(picking, "move_line_ids", self.env["stock.move.line"]).filtered(
            lambda line: line.product_id
            and line.product_id.type not in {"service", "combo"}
            and self._ontime_move_line_qty_in_product_uom(line) > 0
        )
        packages = move_lines.mapped("result_package_id")
        result = []
        if packages:
            package_weights = packages._get_weight(picking.id)
            for package in packages:
                raw_weight = package.shipping_weight or package_weights.get(package, 0.0)
                weight = self._ontime_weight_to_kg(raw_weight)
                length, width, height = self._ontime_package_dimensions_cm(package)
                result.append(
                    {
                        "peso": round(weight, 3),
                        "alto": round(height, 2),
                        "ancho": round(width, 2),
                        "largo": round(length, 2),
                    }
                )

            loose_lines = move_lines.filtered(lambda line: not line.result_package_id)
            if loose_lines:
                loose_actual, _loose_vol, _loose_cubic = self._ontime_product_lines_metrics(loose_lines)
                loose_count = 1
                if self.ontime_max_package_weight_kg:
                    loose_count = max(1, math.ceil(loose_actual / self.ontime_max_package_weight_kg))
                result.extend({"peso": value} for value in self._ontime_split_weight(loose_actual, loose_count))
            return result

        package_count = max(int(metrics.get("package_count") or 1), 1)
        moves = picking.move_ids.filtered(
            lambda move: move.state != "cancel"
            and move.product_id
            and move.product_id.type not in {"service", "combo"}
            and self._ontime_picking_move_qty(move) > 0
        )
        if len(moves) == 1:
            move = moves[0]
            product = move.product_id
            qty = move.product_uom._compute_quantity(
                self._ontime_picking_move_qty(move), product.uom_id
            )
            rounded_qty = int(round(qty))
            if rounded_qty == package_count and abs(qty - rounded_qty) < 1e-6:
                length, width, height = self._ontime_product_dimensions_cm(product)
                unit_weight = self._ontime_weight_to_kg(product.weight or 0.0)
                if unit_weight > 0 and length > 0 and width > 0 and height > 0:
                    return [
                        {
                            "peso": round(unit_weight, 3),
                            "alto": round(height, 2),
                            "ancho": round(width, 2),
                            "largo": round(length, 2),
                        }
                        for _index in range(package_count)
                    ]

        return [
            {"peso": value}
            for value in self._ontime_split_weight(metrics.get("actual_weight"), package_count)
        ]





    def _ontime_prepare_shipment_payload(self, picking, metrics, zone, service):
        """Build the documented Mensaglobal v1 shipment request."""
        self.ensure_one()
        origin_partner = self._ontime_origin_partner(picking)
        destination_partner = picking.partner_id
        payload = {
            "direccionOrigen": self._ontime_mensaglobal_address(
                origin_partner, role=_("origin")
            ),
            "direccionDestino": self._ontime_mensaglobal_address(
                destination_partner,
                role=_("destination"),
                name_override="Test Pruebas" if self.ontime_mode == "test" else None,
            ),
            "servicio": self._ontime_api_service_value(service),
            "bultos": self._ontime_prepare_api_packages(picking, metrics),
            "referencia": self._ontime_safe_text(picking.name, 120),
        }
        return payload

    @staticmethod
    def _ontime_response_data(payload):
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def _ontime_extract_shipment_result(self, payload):
        self.ensure_one()
        data = self._ontime_response_data(payload)
        reference = data.get("codigoExpedicion") or False
        network_reference = data.get("codigoExpedicionRed") or False
        barcode = data.get("codigoBarras") or False
        label_base64 = data.get("etiquetas") or False
        status = "CREATED" if reference else False
        correlation_id = False
        for source in (payload, data):
            if not isinstance(source, dict):
                continue
            for key in ("correlationId", "correlation_id", "requestId", "request_id"):
                if source.get(key):
                    correlation_id = str(source[key])
                    break
            if correlation_id:
                break
        return (
            str(reference) if reference else False,
            status,
            correlation_id,
            str(network_reference) if network_reference else False,
            str(barcode) if barcode else False,
            label_base64,
        )

    def _ontime_simulated_reference(self, picking):
        self.ensure_one()
        safe_name = re.sub(r"[^A-Za-z0-9]+", "-", picking.name or str(picking.id)).strip("-")
        return "SIM-ONTIME-%s" % (safe_name or picking.id)

    @staticmethod
    def _ontime_request_hash(payload):
        canonical = json.dumps(
            payload or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _ontime_is_uncertain_write_error(error):
        if error.error_code in {"TIMEOUT", "CONNECTION_ERROR"}:
            return True
        status = int(error.status_code or 0)
        return status == 408 or status >= 500

    def _ontime_mark_operation_uncertain(
        self, picking, state, message, *, base_vals=None, request_hash=False
    ):
        self.ensure_one()
        vals = dict(base_vals or {})
        vals.update(
            {
                "ontime_operation_state": state,
                "ontime_last_api_attempt_at": fields.Datetime.now(),
                "ontime_last_api_error": self._ontime_safe_text(message, 4000),
            }
        )
        if request_hash:
            vals["ontime_shipment_request_hash"] = request_hash
        picking.write(vals)
        picking.message_post(
            body=_(
                "OnTime returned an uncertain result for a write operation. Automatic retry is "
                "blocked to prevent duplicates. Reconcile the shipment with OnTime before retrying. "
                "Technical detail: %s"
            )
            % self._ontime_safe_text(message, 1000)
        )

    def _ontime_create_one_shipment(self, picking):
        self.ensure_one()
        self._ontime_validate_company(picking)
        self._ontime_ensure_shipping_sale_tax()
        self._ontime_lock_picking(picking)

        operation_state = picking.ontime_operation_state or "none"
        if operation_state == "create_uncertain":
            raise UserError(
                _(
                    "This picking has an uncertain OnTime creation result. Automatic retry is "
                    "blocked to avoid creating a duplicate shipment. Reconcile it first."
                )
            )
        if operation_state == "cancel_uncertain":
            raise UserError(
                _(
                    "This picking has an uncertain OnTime cancellation result. Reconcile it "
                    "before attempting any new shipment operation."
                )
            )

        existing_reference = picking.ontime_shipment_reference
        if not existing_reference and picking.carrier_id == self and picking.carrier_tracking_ref:
            existing_reference = picking.carrier_tracking_ref
        if existing_reference:
            if picking.ontime_shipment_cancelled_at or operation_state in {
                "cancelled", "cancelled_network_unconfirmed"
            }:
                raise UserError(
                    _(
                        "The existing OnTime shipment is cancelled in Mensaglobal. A cancelled "
                        "shipment is never recreated automatically from the same picking."
                    )
                )
            vals = {"ontime_operation_state": "created"}
            if not picking.ontime_shipment_reference:
                vals["ontime_shipment_reference"] = existing_reference
            picking.write(vals)
            return {
                "exact_price": picking.ontime_shipment_price or 0.0,
                "tracking_number": existing_reference,
            }

        partner = picking.partner_id
        self._ontime_validate_shipment_partner(partner)
        if not self.ontime_tariff_rule_ids:
            raise UserError(_("Import the current OnTime tariff PDF before creating a shipment."))

        metrics = self._ontime_get_picking_metrics(picking)
        zone = self._ontime_resolve_zone(partner)
        price, service = self._ontime_compute_contract_price(zone, metrics["billable_weight"])
        api_service = self._ontime_api_service_value(service)
        payload = self._ontime_prepare_shipment_payload(picking, metrics, zone, service)
        request_hash = self._ontime_request_hash(payload)

        vals = {
            "ontime_shipment_service": service,
            "ontime_shipment_zone": zone,
            "ontime_shipment_price": price,
            "ontime_shipment_weight": metrics["actual_weight"],
            "ontime_shipment_billable_weight": metrics["billable_weight"],
            "ontime_shipment_volumetric_weight": metrics["volumetric_weight"],
            "ontime_shipment_packages": metrics["package_count"],
            "ontime_shipment_api_service": api_service,
            "ontime_shipment_request_hash": request_hash,
            "ontime_is_test_shipment": self.ontime_mode == "test",
            "ontime_last_api_error": False,
        }

        if self.ontime_mode == "simulated":
            reference = self._ontime_simulated_reference(picking)
            vals.update(
                {
                    "ontime_shipment_reference": reference,
                    "ontime_network_reference": "SIM-NET-%s" % picking.id,
                    "ontime_barcode": "SIM%s" % picking.id,
                    "ontime_shipment_status": "SIMULATED",
                    "ontime_shipment_created_at": fields.Datetime.now(),
                    "carrier_tracking_ref": reference,
                    "ontime_operation_state": "created",
                    "ontime_last_api_attempt_at": fields.Datetime.now(),
                }
            )
            picking.write(vals)
            if self.ontime_auto_download_label:
                self._ontime_store_label_attachment(picking, force=True)
            return {"exact_price": price, "tracking_number": reference}

        endpoint = (self.ontime_shipment_endpoint or "/v1/envios").strip()
        try:
            response = self._get_ontime_client().request("POST", endpoint, json=payload)
        except OnTimeAPIError as error:
            formatted = self._format_ontime_api_error(error)
            if self._ontime_is_uncertain_write_error(error):
                self._ontime_mark_operation_uncertain(
                    picking,
                    "create_uncertain",
                    formatted,
                    base_vals=vals,
                    request_hash=request_hash,
                )
                return {"exact_price": price, "tracking_number": False}
            raise UserError(
                _("Mensaglobal rejected OnTime shipment creation: %s") % formatted
            ) from error

        (
            reference,
            status,
            correlation_id,
            network_reference,
            barcode,
            label_base64,
        ) = self._ontime_extract_shipment_result(response)
        if not reference:
            detail = _(
                "Mensaglobal accepted the shipment request but did not return codigoExpedicion. "
                "The creation result must be reconciled before retrying."
            )
            self._ontime_mark_operation_uncertain(
                picking,
                "create_uncertain",
                detail,
                base_vals=vals,
                request_hash=request_hash,
            )
            return {"exact_price": price, "tracking_number": False}

        duplicate = self._ontime_reference_duplicate(picking, reference)
        if duplicate:
            detail = _(
                "Mensaglobal returned codigoExpedicion %(reference)s, but it is already linked "
                "to picking %(picking)s in this company. Reconcile it manually."
            ) % {"reference": reference, "picking": duplicate.display_name}
            uncertain_vals = dict(vals)
            uncertain_vals["ontime_shipment_correlation_id"] = correlation_id or False
            self._ontime_mark_operation_uncertain(
                picking,
                "create_uncertain",
                detail,
                base_vals=uncertain_vals,
                request_hash=request_hash,
            )
            return {"exact_price": price, "tracking_number": False}

        vals.update(
            {
                "ontime_shipment_reference": reference,
                "ontime_network_reference": network_reference or False,
                "ontime_barcode": barcode or False,
                "ontime_shipment_status": status or "CREATED",
                "ontime_shipment_correlation_id": correlation_id or False,
                "ontime_shipment_created_at": fields.Datetime.now(),
                "carrier_tracking_ref": reference,
                "ontime_operation_state": "created",
                "ontime_last_api_attempt_at": fields.Datetime.now(),
                "ontime_last_api_error": False,
            }
        )
        picking.write(vals)
        if self.ontime_mode == "test":
            picking.message_post(
                body=_(
                    "OnTime API TEST shipment created. Mensaglobal received the destination "
                    "recipient name as 'Test Pruebas' per OnTime instructions; this shipment "
                    "must not be considered a valid delivery."
                )
            )

        label_stored = False
        if label_base64 and self.ontime_auto_download_label:
            try:
                label_stored = bool(self._ontime_store_label_base64(picking, label_base64))
            except UserError as error:
                _logger.warning(
                    "Mensaglobal shipment %s created but inline label could not be stored: %s",
                    reference,
                    error,
                )
        if self.ontime_auto_download_label and not label_stored:
            try:
                self._ontime_store_label_attachment(picking, force=True)
            except UserError as error:
                _logger.warning(
                    "Mensaglobal shipment %s created but label download failed: %s",
                    reference,
                    error,
                )
                picking.message_post(
                    body=_(
                        "The OnTime shipment was created correctly, but its label could not "
                        "be obtained automatically. Use 'Etiqueta OnTime' to retry. Error: %s"
                    ) % error
                )
        return {"exact_price": price, "tracking_number": reference}

    def ontime_send_shipping(self, pickings):
        self.ensure_one()
        if self.delivery_type != "ontime":
            raise UserError(_("This action is only available for OnTime carriers."))
        return [self._ontime_create_one_shipment(picking) for picking in pickings]

    # ------------------------------------------------------------------
    # Phase 5 - labels and tracking
    # ------------------------------------------------------------------
    def _ontime_reference_endpoint(self, template, reference):
        self.ensure_one()
        template = (template or "").strip()
        if not template or "{reference}" not in template:
            raise UserError(_("The OnTime endpoint template is not configured correctly."))
        return template.format(reference=quote(str(reference), safe=""))

    @staticmethod
    def _ontime_guess_document_extension(content_type, content):
        content_type = (content_type or "").lower()
        if content.startswith(b"%PDF-") or "pdf" in content_type:
            return ".pdf", "application/pdf"
        if content.startswith(b"PK\x03\x04") or "zip" in content_type:
            return ".zip", "application/zip"
        if "png" in content_type:
            return ".png", "image/png"
        if "jpeg" in content_type or "jpg" in content_type:
            return ".jpg", "image/jpeg"
        return ".bin", content_type or "application/octet-stream"

    @staticmethod
    def _ontime_decode_base64_document(value):
        if not isinstance(value, str):
            return False, False
        value = value.strip()
        if not value:
            return False, False
        mimetype = False
        if value.startswith("data:") and ";base64," in value:
            header, value = value.split(",", 1)
            mimetype = header[5:].split(";", 1)[0] or False
        # URLs and short scalar values are not documents.
        if value.startswith(("http://", "https://")) or len(value) < 80:
            return False, False
        try:
            decoded = base64.b64decode(value, validate=True)
        except Exception:
            try:
                decoded = base64.b64decode(value)
            except Exception:
                return False, False
        if not decoded:
            return False, False
        return decoded, mimetype

    def _ontime_extract_document_from_json(self, payload, reference):
        """Best-effort adapter for label responses wrapped in JSON.

        The Shipments catalogue guarantees label download capability, but an
        account/gateway may expose the document as raw bytes, base64 in the
        common envelope, or a temporary download URL. Raw PDF is handled first
        by ``_ontime_fetch_label_document``; this method covers the two wrapped
        variants without coupling the rest of the module to a single schema.
        """
        self.ensure_one()
        if not isinstance(payload, dict):
            return False
        data = payload.get("data")
        roots = [data, payload] if isinstance(data, dict) else [payload]
        base64_keys = (
            "etiquetas", "labelBase64", "label_base64", "podBase64", "pod_base64",
            "proofOfDeliveryBase64", "proof_of_delivery_base64",
            "pdfBase64", "pdf_base64", "fileBase64", "file_base64",
            "contentBase64", "content_base64", "content", "document", "pdf",
            "label", "pod", "proofOfDelivery", "proof_of_delivery",
        )
        url_keys = ("downloadUrl", "download_url", "labelUrl", "label_url", "url")
        name_keys = ("filename", "fileName", "name")
        type_keys = ("contentType", "content_type", "mimeType", "mimetype")

        for root in roots:
            if not isinstance(root, dict):
                continue
            filename = next((root.get(k) for k in name_keys if root.get(k)), False)
            declared_type = next((root.get(k) for k in type_keys if root.get(k)), False)
            for key in base64_keys:
                content, embedded_type = self._ontime_decode_base64_document(root.get(key))
                if content:
                    content_type = embedded_type or declared_type or "application/pdf"
                    ext, content_type = self._ontime_guess_document_extension(content_type, content)
                    filename = filename or "OnTime-%s%s" % (reference, ext)
                    return content, filename, content_type
            for key in url_keys:
                url = root.get(key)
                if isinstance(url, str) and url.startswith("http://"):
                    raise UserError(_("OnTime document download URLs must use HTTPS."))
                if isinstance(url, str) and url.startswith("https://"):
                    try:
                        result = self._get_ontime_client().request_binary(
                            "GET",
                            url,
                            headers={"Accept": "application/pdf, application/zip, image/*, application/json"},
                        )
                    except OnTimeAPIError as error:
                        raise UserError(
                            _("OnTime label download URL failed: %s")
                            % self._format_ontime_api_error(error)
                        ) from error
                    if result.get("json"):
                        # Do not recurse indefinitely if the URL returns the same wrapper.
                        nested = result["json"]
                        for nested_root in (nested.get("data"), nested) if isinstance(nested, dict) else ():
                            if isinstance(nested_root, dict):
                                for nested_key in base64_keys:
                                    content, embedded_type = self._ontime_decode_base64_document(
                                        nested_root.get(nested_key)
                                    )
                                    if content:
                                        content_type = embedded_type or declared_type or "application/pdf"
                                        ext, content_type = self._ontime_guess_document_extension(
                                            content_type, content
                                        )
                                        return (
                                            content,
                                            filename or "OnTime-%s%s" % (reference, ext),
                                            content_type,
                                        )
                    content = result.get("content") or b""
                    if content:
                        ext, content_type = self._ontime_guess_document_extension(
                            result.get("content_type"), content
                        )
                        return (
                            content,
                            result.get("filename") or filename or "OnTime-%s%s" % (reference, ext),
                            content_type,
                        )
        return False

    def _ontime_simulated_label_pdf(self, picking):
        """Generate a small printable PDF so Phase 5 can be tested without an API key."""
        self.ensure_one()
        try:
            from reportlab.lib.pagesizes import A6
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise UserError(
                _("ReportLab is required to generate the simulated OnTime label.")
            ) from exc

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A6)
        width, height = A6
        y = height - 28
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(24, y, "ONTIME - SIMULATED")
        y -= 24
        pdf.setFont("Helvetica", 9)
        lines = [
            "Reference: %s" % (picking.ontime_shipment_reference or picking.name),
            "Picking: %s" % picking.name,
            "Recipient: %s" % self._ontime_safe_text(picking.partner_id.name, 45),
            "Postal code: %s" % (picking.partner_id.zip or ""),
            "Packages: %s" % (picking.ontime_shipment_packages or 1),
            "Weight: %.3f kg" % (picking.ontime_shipment_weight or 0.0),
            "Service: %s" % (picking.ontime_shipment_api_service or ""),
            "This document is not a valid carrier label.",
        ]
        for line in lines:
            pdf.drawString(24, y, line)
            y -= 16
        pdf.rect(18, 18, width - 36, height - 36)
        pdf.showPage()
        pdf.save()
        return buffer.getvalue()

    def _ontime_fetch_label_document(self, picking):
        self.ensure_one()
        self._ontime_validate_company(picking)
        reference = picking.ontime_shipment_reference or picking.carrier_tracking_ref
        if not reference:
            raise UserError(_("Create the OnTime shipment before requesting its label."))
        if self.ontime_mode == "simulated":
            content = self._ontime_simulated_label_pdf(picking)
            return content, "OnTime-%s-SIMULATED.pdf" % reference, "application/pdf"

        endpoint = self._ontime_reference_endpoint(self.ontime_label_endpoint, reference)
        try:
            result = self._get_ontime_client().request_binary(
                "GET",
                endpoint,
                headers={"Accept": "application/pdf, application/zip, image/*, application/json"},
            )
        except OnTimeAPIError as error:
            raise UserError(
                _("OnTime label download failed: %s")
                % self._format_ontime_api_error(error)
            ) from error

        if result.get("json"):
            extracted = self._ontime_extract_document_from_json(result["json"], reference)
            if extracted:
                return extracted
            raise UserError(
                _("OnTime returned a successful label response but no printable document was found.")
            )

        content = result.get("content") or b""
        if not content:
            raise UserError(_("OnTime returned an empty label document."))
        ext, content_type = self._ontime_guess_document_extension(
            result.get("content_type"), content
        )
        filename = result.get("filename") or "OnTime-%s%s" % (reference, ext)
        return content, filename, content_type

    def _ontime_store_label_content(self, picking, content, filename, mimetype):
        self.ensure_one()
        max_bytes = int((self.ontime_max_document_size_mb or 0) * 1024 * 1024)
        if max_bytes and len(content or b"") > max_bytes:
            raise UserError(_("The OnTime label exceeds the configured maximum document size."))
        attachment = picking.ontime_label_attachment_id
        values = {
            "name": filename,
            "type": "binary",
            "datas": base64.b64encode(content),
            "mimetype": mimetype,
            "res_model": "stock.picking",
            "res_id": picking.id,
        }
        if attachment:
            attachment.sudo().write(values)
        else:
            attachment = self.env["ir.attachment"].sudo().create(values)
        picking.write(
            {
                "ontime_label_attachment_id": attachment.id,
                "ontime_label_downloaded_at": fields.Datetime.now(),
            }
        )
        return attachment

    def _ontime_store_label_base64(self, picking, value):
        self.ensure_one()
        content, embedded_type = self._ontime_decode_base64_document(value)
        if not content:
            return False
        reference = picking.ontime_shipment_reference or picking.name
        ext, mimetype = self._ontime_guess_document_extension(
            embedded_type or "application/pdf", content
        )
        return self._ontime_store_label_content(
            picking, content, "OnTime-%s%s" % (reference, ext), mimetype
        )



    def _ontime_store_label_attachment(self, picking, force=False):
        self.ensure_one()
        self._ontime_validate_company(picking)
        self._ontime_lock_picking(picking)
        attachment = picking.ontime_label_attachment_id
        if attachment and not force:
            return attachment
        content, filename, mimetype = self._ontime_fetch_label_document(picking)
        return self._ontime_store_label_content(picking, content, filename, mimetype)

    @staticmethod
    def _ontime_tracking_last_event_text(data):
        if not isinstance(data, dict):
            return False
        current = data.get("ultimoEstado")
        events = data.get("seguimiento") or data.get("events")
        event_text = False
        if isinstance(events, list) and events:
            event = events[-1]
            if isinstance(event, dict):
                parts = []
                for key in ("fecha", "dateTime", "datetime", "timestamp", "date", "time"):
                    if event.get(key):
                        parts.append(str(event[key]))
                        break
                for key in ("estado", "status", "descripcion", "description", "event", "message"):
                    if event.get(key):
                        parts.append(str(event[key]))
                        break
                event_text = " - ".join(parts) if parts else json.dumps(event, ensure_ascii=False)
            else:
                event_text = str(event)
        if current and event_text:
            return "%s - %s" % (current, event_text[:350])
        return str(current or event_text or "")[:500] or False

    def _ontime_refresh_tracking(self, picking):
        self.ensure_one()
        self._ontime_validate_company(picking)
        reference = picking.ontime_shipment_reference or picking.carrier_tracking_ref
        if not reference:
            raise UserError(_("Create the OnTime shipment before requesting tracking."))
        if self.ontime_mode == "simulated":
            cancelled = bool(picking.ontime_shipment_cancelled_at)
            status = "CANCELLED" if cancelled else "SIMULATED"
            event_text = _("Shipment cancelled") if cancelled else _(
                "Simulated shipment - no remote tracking events."
            )
            data = {
                "codigoExpedicion": reference,
                "codigoExpedicionRed": picking.ontime_network_reference or False,
                "ultimoEstado": status,
                "seguimiento": [],
                "urlSeguimientoRed": picking.ontime_tracking_url or False,
                "urlPOD": picking.ontime_pod_url or False,
                "codigoBarras": picking.ontime_barcode or False,
            }
        else:
            endpoint = self._ontime_reference_endpoint(self.ontime_tracking_endpoint, reference)
            try:
                payload = self._get_ontime_client().request("GET", endpoint)
            except OnTimeAPIError as error:
                raise UserError(
                    _("Mensaglobal tracking request failed: %s")
                    % self._format_ontime_api_error(error)
                ) from error
            data = self._ontime_response_data(payload)
            status = self._ontime_extract_status(data)
            event_text = self._ontime_tracking_last_event_text(data)

        status = self._ontime_extract_status(data)
        vals = self._ontime_status_vals(picking, status)
        vals.update(
            {
                "ontime_tracking_last_sync": fields.Datetime.now(),
                "ontime_tracking_last_event": event_text,
                "ontime_tracking_events_json": json.dumps(
                    data, ensure_ascii=False, indent=2, default=str
                )[:100000],
                "ontime_last_api_attempt_at": fields.Datetime.now(),
                "ontime_last_api_error": False,
            }
        )
        if data.get("codigoExpedicionRed"):
            vals["ontime_network_reference"] = str(data["codigoExpedicionRed"])
        if data.get("codigoBarras"):
            vals["ontime_barcode"] = str(data["codigoBarras"])
        if data.get("urlSeguimientoRed"):
            vals["ontime_tracking_url"] = str(data["urlSeguimientoRed"])
        if data.get("urlPOD"):
            vals["ontime_pod_url"] = str(data["urlPOD"])
        picking.write(vals)
        return data

    # ------------------------------------------------------------------
    # Phase 6 - shipment detail, proof of delivery and cancellation
    # ------------------------------------------------------------------
    @staticmethod
    def _ontime_extract_status(data):
        if not isinstance(data, dict):
            return False
        for key in ("ultimoEstado", "status", "shipmentStatus", "shipment_status", "state"):
            value = data.get(key)
            if value is not None:
                if isinstance(value, dict):
                    value = value.get("code") or value.get("name") or value.get("description")
                if value is not None:
                    return str(value)
        shipment = data.get("shipment")
        if isinstance(shipment, dict):
            return DeliveryCarrier._ontime_extract_status(shipment)
        return False

    @staticmethod
    def _ontime_status_is_cancelled(status):
        normalized = re.sub(r"[^A-Z]", "", str(status or "").upper())
        return normalized in {"CANCELLED", "CANCELED", "ANULADO", "ANULADA"}

    def _ontime_status_vals(self, picking, status):
        self.ensure_one()
        vals = {}
        if status:
            vals["ontime_shipment_status"] = str(status)
        if self._ontime_status_is_cancelled(status):
            # Do not erase the explicit Mensaglobal warning that cancellation was
            # not confirmed in the carrier network merely because a local status
            # contains the word "cancelled".
            if picking.ontime_operation_state != "cancelled_network_unconfirmed":
                vals["ontime_operation_state"] = "cancelled"
                vals["ontime_shipment_cancelled_at"] = (
                    picking.ontime_shipment_cancelled_at or fields.Datetime.now()
                )
            vals["ontime_last_api_error"] = False
        elif picking.ontime_shipment_reference and picking.ontime_operation_state == "none":
            vals["ontime_operation_state"] = "created"
        return vals

    def _ontime_refresh_shipment_detail(self, picking):
        """Compatibility action: Mensaglobal exposes detail through localizar."""
        self.ensure_one()
        data = self._ontime_refresh_tracking(picking)
        picking.write(
            {
                "ontime_shipment_detail_last_sync": fields.Datetime.now(),
                "ontime_shipment_detail_json": json.dumps(
                    data, ensure_ascii=False, indent=2, default=str
                )[:100000],
            }
        )
        return data

    def _ontime_simulated_pod_pdf(self, picking):
        self.ensure_one()
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise UserError(
                _("ReportLab is required to generate the simulated OnTime POD.")
            ) from exc

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        y = height - 50
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(45, y, "ONTIME - SIMULATED POD")
        y -= 35
        pdf.setFont("Helvetica", 10)
        lines = [
            "Reference: %s" % (picking.ontime_shipment_reference or picking.name),
            "Picking: %s" % picking.name,
            "Recipient: %s" % self._ontime_safe_text(picking.partner_id.name, 70),
            "Postal code: %s" % (picking.partner_id.zip or ""),
            "Status: %s" % (picking.ontime_shipment_status or "SIMULATED"),
            "This document is only for testing and is not a valid proof of delivery.",
        ]
        for line in lines:
            pdf.drawString(45, y, line)
            y -= 22
        pdf.rect(35, 35, width - 70, height - 70)
        pdf.showPage()
        pdf.save()
        return buffer.getvalue()

    def _ontime_fetch_pod_document(self, picking):
        self.ensure_one()
        self._ontime_validate_company(picking)
        reference = picking.ontime_shipment_reference or picking.carrier_tracking_ref
        if not reference:
            raise UserError(_("Create the OnTime shipment before requesting proof of delivery."))
        if self.ontime_mode == "simulated":
            content = self._ontime_simulated_pod_pdf(picking)
            return content, "OnTime-%s-POD-SIMULATED.pdf" % reference, "application/pdf"

        if not picking.ontime_pod_url:
            self._ontime_refresh_tracking(picking)
        url = (picking.ontime_pod_url or "").strip()
        if not url:
            raise UserError(
                _("Mensaglobal has not returned a POD URL for this shipment yet.")
            )
        if not url.startswith("https://"):
            raise UserError(_("The Mensaglobal POD URL must use HTTPS."))
        try:
            result = self._get_ontime_client().request_binary(
                "GET",
                url,
                headers={"Accept": "application/pdf, application/zip, image/*, application/json"},
            )
        except OnTimeAPIError as error:
            raise UserError(
                _("OnTime proof-of-delivery download failed: %s")
                % self._format_ontime_api_error(error)
            ) from error

        if result.get("json"):
            extracted = self._ontime_extract_document_from_json(result["json"], reference)
            if extracted:
                content, filename, mimetype = extracted
                if filename and "pod" not in filename.lower():
                    ext = ("." + filename.rsplit(".", 1)[-1]) if "." in filename else ""
                    filename = "OnTime-%s-POD%s" % (reference, ext or ".pdf")
                return content, filename, mimetype
            raise UserError(
                _("The POD URL returned JSON but no downloadable document was found.")
            )

        content = result.get("content") or b""
        if not content:
            raise UserError(_("OnTime returned an empty proof-of-delivery document."))
        ext, content_type = self._ontime_guess_document_extension(
            result.get("content_type"), content
        )
        filename = result.get("filename") or "OnTime-%s-POD%s" % (reference, ext)
        return content, filename, content_type

    def _ontime_store_pod_attachment(self, picking, force=False):
        self.ensure_one()
        self._ontime_validate_company(picking)
        self._ontime_lock_picking(picking)
        attachment = picking.ontime_pod_attachment_id
        if attachment and not force:
            return attachment
        content, filename, mimetype = self._ontime_fetch_pod_document(picking)
        values = {
            "name": filename,
            "type": "binary",
            "datas": base64.b64encode(content),
            "mimetype": mimetype,
            "res_model": "stock.picking",
            "res_id": picking.id,
        }
        if attachment:
            attachment.sudo().write(values)
        else:
            attachment = self.env["ir.attachment"].sudo().create(values)
        picking.write(
            {
                "ontime_pod_attachment_id": attachment.id,
                "ontime_pod_downloaded_at": fields.Datetime.now(),
            }
        )
        return attachment

    def _ontime_mark_cancelled(self, picking, correlation_id=False, network_cancelled=None):
        self.ensure_one()
        if network_cancelled is False:
            status = "CANCELLED_MENSAGLOBAL_ONLY"
            operation_state = "cancelled_network_unconfirmed"
            network_state = "no"
            event = _("Cancelled in Mensaglobal, but cancellation was not confirmed in OnTime")
        else:
            status = "CANCELLED"
            operation_state = "cancelled"
            network_state = "yes" if network_cancelled is True else "unknown"
            event = _("Shipment cancelled")
        picking.write(
            {
                "ontime_shipment_status": status,
                "ontime_shipment_cancelled_at": fields.Datetime.now(),
                "ontime_cancel_correlation_id": correlation_id or False,
                "ontime_tracking_last_event": event,
                "ontime_operation_state": operation_state,
                "ontime_network_cancellation_state": network_state,
                "ontime_last_api_attempt_at": fields.Datetime.now(),
                "ontime_last_api_error": False,
            }
        )
        if network_cancelled is False:
            picking.message_post(
                body=_(
                    "The shipment was cancelled in Mensaglobal, but Mensaglobal returned "
                    "anuladoEnRed=false. OnTime may still deliver it; verify the shipment with "
                    "the carrier before assuming it is stopped."
                )
            )
        else:
            picking.message_post(
                body=_("OnTime shipment %(reference)s has been marked as cancelled.")
                % {
                    "reference": picking.ontime_shipment_reference
                    or picking.carrier_tracking_ref
                    or picking.name
                }
            )

    def _ontime_cancel_one_shipment(self, picking):
        self.ensure_one()
        self._ontime_validate_company(picking)
        self._ontime_lock_picking(picking)

        if picking.ontime_operation_state == "create_uncertain":
            raise UserError(
                _(
                    "The OnTime shipment creation result is uncertain. Reconcile creation before "
                    "attempting cancellation."
                )
            )
        if picking.ontime_operation_state == "cancel_uncertain":
            raise UserError(
                _(
                    "The OnTime cancellation result is uncertain. Automatic retry is blocked; "
                    "reconcile the shipment first."
                )
            )

        reference = picking.ontime_shipment_reference or picking.carrier_tracking_ref
        if not reference:
            return True
        if picking.ontime_shipment_cancelled_at:
            return True

        if self.ontime_mode == "simulated":
            self._ontime_mark_cancelled(picking, network_cancelled=True)
            return True

        endpoint = self._ontime_reference_endpoint(
            self.ontime_cancel_endpoint or "/v1/envios/{reference}/anular", reference
        )
        try:
            payload = self._get_ontime_client().request("PUT", endpoint)
        except OnTimeAPIError as error:
            formatted = self._format_ontime_api_error(error)
            if self._ontime_is_uncertain_write_error(error):
                self._ontime_mark_operation_uncertain(
                    picking,
                    "cancel_uncertain",
                    formatted,
                )
                return True
            raise UserError(
                _("Mensaglobal rejected shipment cancellation: %s") % formatted
            ) from error

        data = self._ontime_response_data(payload)
        network_cancelled = data.get("anuladoEnRed")
        if network_cancelled not in (True, False):
            network_cancelled = None
        self._ontime_mark_cancelled(
            picking,
            network_cancelled=network_cancelled,
        )
        return True

    def ontime_cancel_shipment(self, pickings):
        self.ensure_one()
        if self.delivery_type != "ontime":
            raise UserError(_("This action is only available for OnTime carriers."))
        for picking in pickings:
            self._ontime_cancel_one_shipment(picking)
        return True

    def ontime_get_tracking_link(self, picking):
        self.ensure_one()
        self._ontime_validate_company(picking)
        if picking.ontime_tracking_url:
            return picking.ontime_tracking_url
        if self.ontime_mode in ("test", "real") and picking.ontime_shipment_reference:
            self._ontime_refresh_tracking(picking)
            if picking.ontime_tracking_url:
                return picking.ontime_tracking_url
        template = (self.ontime_public_tracking_url or "").strip()
        if not template:
            return False
        reference = picking.ontime_shipment_reference or picking.carrier_tracking_ref or ""
        postal_code = picking.partner_id.zip or ""
        try:
            return template.format(
                reference=quote(str(reference), safe=""),
                postal_code=quote(str(postal_code), safe=""),
            )
        except (KeyError, ValueError):
            return template
