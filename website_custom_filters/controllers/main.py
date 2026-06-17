import logging
import re

from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)


class WebsiteSaleRange(WebsiteSale):
    """Añade filtros reales de rango numérico a /shop."""

    def _range_to_float(self, value):
        """Convierte textos como '150', '150 W' o '150,5' a float."""
        if value in (None, False, ''):
            return None
        text = str(value).replace(',', '.').strip()
        match = re.search(r'-?\d+(?:\.\d+)?', text)
        if not match:
            return None
        try:
            return float(match.group(0))
        except (TypeError, ValueError):
            return None

    def _get_active_range_filters(self):
        """Lee de la URL los filtros range_max_ID que realmente limitan resultados."""
        active_filters = []
        for param, value in (request.params or {}).items():
            if not param.startswith('range_max_') or value in (None, ''):
                continue
            try:
                attr_id = int(param.replace('range_max_', '', 1))
            except (TypeError, ValueError):
                continue

            current_max = self._range_to_float(value)
            if current_max is None:
                continue

            attribute = request.env['product.attribute'].sudo().browse(attr_id).exists()
            if not attribute or attribute.display_type != 'range':
                continue

            configured_max = self._range_to_float(attribute.range_max)
            if configured_max is not None and current_max >= configured_max:
                continue

            active_filters.append((attribute, current_max))
        return active_filters

    def _template_matches_range_filter(self, product_tmpl, attribute, current_max):
        """Comprueba si el producto tiene ese atributo con valor numérico <= current_max."""
        lines = product_tmpl.sudo().attribute_line_ids.filtered(
            lambda line: line.attribute_id.id == attribute.id
        )
        if not lines:
            return False

        for line in lines:
            for value in line.value_ids:
                numeric_value = self._range_to_float(value.name)
                if numeric_value is not None and numeric_value <= current_max:
                    return True
        return False

    def _filter_products_recordset_by_ranges(self, products):
        """Filtra un recordset de product.template con todos los rangos activos."""
        active_filters = self._get_active_range_filters()
        if not active_filters or not products:
            return products

        filtered_products = products
        for attribute, current_max in active_filters:
            filtered_products = filtered_products.filtered(
                lambda product, attr=attribute, max_value=current_max:
                    self._template_matches_range_filter(product, attr, max_value)
            )
            _logger.info(
                "Filtro range aplicado: atributo=%s max=%s productos_restantes=%s",
                attribute.name,
                current_max,
                len(filtered_products),
            )
        return filtered_products

    def _shop_lookup_products(self, attrib_set, options, post, search, website):
        """Aplica el filtro antes de que Odoo calcule paginación y tarjetas."""
        fuzzy_search_term, product_count, search_result = super()._shop_lookup_products(
            attrib_set, options, post, search, website
        )
        filtered_result = self._filter_products_recordset_by_ranges(search_result)
        if filtered_result != search_result:
            product_count = len(filtered_result)
        return fuzzy_search_term, product_count, filtered_result.with_context(bin_size=True)

    def _shop_get_query_url_kwargs(
        self, category, search, min_price, max_price, order=None, tags=None, attribute_value=None, **post
    ):
        """Mantiene range_max_ID al paginar, ordenar o cambiar vista."""
        values = super()._shop_get_query_url_kwargs(
            category, search, min_price, max_price,
            order=order, tags=tags, attribute_value=attribute_value, **post
        )
        for key, value in (request.params or {}).items():
            if key.startswith('range_max_') and value not in (None, ''):
                values[key] = value
        return values
