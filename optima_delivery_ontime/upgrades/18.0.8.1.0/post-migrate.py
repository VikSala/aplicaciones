import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Convert known Phase 8 provisional defaults to Mensaglobal v1 values."""
    if not version:
        return

    cr.execute(
        """
        UPDATE delivery_carrier
           SET ontime_api_service_economy = '72'
         WHERE delivery_type = 'ontime'
           AND COALESCE(ontime_api_service_economy, '') IN ('', 'XS ECONOMY 24-48h')
        """
    )
    cr.execute(
        """
        UPDATE delivery_carrier
           SET ontime_api_service_xs24 = '24'
         WHERE delivery_type = 'ontime'
           AND COALESCE(ontime_api_service_xs24, '') IN ('', 'XS 24h')
        """
    )
    cr.execute(
        """
        UPDATE delivery_carrier
           SET ontime_shipment_endpoint = '/v1/envios'
         WHERE delivery_type = 'ontime'
           AND COALESCE(ontime_shipment_endpoint, '') IN ('', '/v1/shipments')
        """
    )
    cr.execute(
        """
        UPDATE delivery_carrier
           SET ontime_label_endpoint = '/v1/envios/etiquetas/{reference}'
         WHERE delivery_type = 'ontime'
           AND COALESCE(ontime_label_endpoint, '') IN ('', '/v1/shipments/{reference}/label')
        """
    )
    cr.execute(
        """
        UPDATE delivery_carrier
           SET ontime_tracking_endpoint = '/v1/envios/localizar/{reference}'
         WHERE delivery_type = 'ontime'
           AND COALESCE(ontime_tracking_endpoint, '') IN ('', '/v1/shipments/{reference}/tracking')
        """
    )
    cr.execute(
        """
        UPDATE delivery_carrier
           SET ontime_shipment_detail_endpoint = '/v1/envios/localizar/{reference}'
         WHERE delivery_type = 'ontime'
           AND COALESCE(ontime_shipment_detail_endpoint, '') IN ('', '/v1/shipments/{reference}')
        """
    )
    cr.execute(
        """
        UPDATE delivery_carrier
           SET ontime_cancellation_mode = 'api',
               ontime_cancel_endpoint = '/v1/envios/{reference}/anular',
               ontime_cancel_http_method = 'PUT'
         WHERE delivery_type = 'ontime'
           AND (
                COALESCE(ontime_cancellation_mode, 'manual') = 'manual'
                OR COALESCE(ontime_cancel_endpoint, '') = ''
           )
        """
    )
    cr.execute(
        """
        UPDATE delivery_carrier
           SET ontime_preproduction_base_url = 'https://preproduccion.mensaglobal.com/api'
         WHERE delivery_type = 'ontime'
           AND COALESCE(ontime_preproduction_base_url, '') = ''
        """
    )
    cr.execute(
        """
        UPDATE delivery_carrier
           SET ontime_public_tracking_url = NULL
         WHERE delivery_type = 'ontime'
           AND ontime_public_tracking_url = 'https://alina.ontime.es/ords/r/ontime/portalcliente999/login?p9999_tipo=1'
        """
    )
    _logger.info("Optima OnTime Phase 7A: migrated provisional API defaults to Mensaglobal v1")
