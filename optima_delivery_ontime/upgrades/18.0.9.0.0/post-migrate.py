import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Finalize OnTime/Mensaglobal defaults and repair missing shipping taxes."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    carriers = (
        env["delivery.carrier"]
        .with_context(active_test=False)
        .search([("delivery_type", "=", "ontime")])
    )
    companies = env["res.company"].search([], limit=2)
    sole_company = companies if len(companies) == 1 else env["res.company"]

    for carrier in carriers:
        vals = {}
        if not carrier.company_id and sole_company:
            vals["company_id"] = sole_company.id
        if not carrier.ontime_production_base_url:
            vals["ontime_production_base_url"] = "https://preproduccion.mensaglobal.com/api"
        if carrier.ontime_api_service_economy != "72":
            vals["ontime_api_service_economy"] = "72"
        if carrier.ontime_api_service_xs24 != "24":
            vals["ontime_api_service_xs24"] = "24"
        if carrier.ontime_shipment_endpoint != "/v1/envios":
            vals["ontime_shipment_endpoint"] = "/v1/envios"
        if carrier.ontime_label_endpoint != "/v1/envios/etiquetas/{reference}":
            vals["ontime_label_endpoint"] = "/v1/envios/etiquetas/{reference}"
        if carrier.ontime_tracking_endpoint != "/v1/envios/localizar/{reference}":
            vals["ontime_tracking_endpoint"] = "/v1/envios/localizar/{reference}"
        if carrier.ontime_shipment_detail_endpoint != "/v1/envios/localizar/{reference}":
            vals["ontime_shipment_detail_endpoint"] = "/v1/envios/localizar/{reference}"
        if carrier.ontime_cancel_endpoint != "/v1/envios/{reference}/anular":
            vals["ontime_cancel_endpoint"] = "/v1/envios/{reference}/anular"
        if carrier.ontime_cancellation_mode != "api":
            vals["ontime_cancellation_mode"] = "api"
        if carrier.ontime_cancel_http_method != "PUT":
            vals["ontime_cancel_http_method"] = "PUT"
        if vals:
            carrier.write(vals)

        company = carrier.company_id or sole_company
        product = carrier.product_id
        if not company or not product:
            continue
        taxes = product.taxes_id._filter_taxes_by_company(company)
        default_tax = company.account_sale_tax_id
        if not taxes and default_tax:
            product.write({"taxes_id": [(4, default_tax.id)]})
            _logger.info(
                "Assigned default sales tax %s to OnTime delivery product %s for company %s",
                default_tax.display_name,
                product.display_name,
                company.display_name,
            )

    _logger.info("Optima OnTime final Mensaglobal migration completed for %s carrier(s)", len(carriers))
