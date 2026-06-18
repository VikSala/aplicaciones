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
        """Lee de la URL los filtros range_min_ID/range_max_ID que realmente limitan resultados."""
        active_filters = []
        range_values = {}

        for param, value in (request.params or {}).items():
            if value in (None, ''):
                continue
            is_min = param.startswith('range_min_')
            is_max = param.startswith('range_max_')
            if not is_min and not is_max:
                continue

            try:
                attr_id = int(param.replace('range_min_' if is_min else 'range_max_', '', 1))
            except (TypeError, ValueError):
                continue

            number = self._range_to_float(value)
            if number is None:
                continue

            range_values.setdefault(attr_id, {})['min' if is_min else 'max'] = number

        for attr_id, values in range_values.items():
            attribute = request.env['product.attribute'].sudo().browse(attr_id).exists()
            if not attribute or attribute.display_type != 'range':
                continue

            configured_min = self._range_to_float(attribute.range_min)
            configured_max = self._range_to_float(attribute.range_max)
            current_min = values.get('min', configured_min)
            current_max = values.get('max', configured_max)

            if current_min is None and current_max is None:
                continue
            if configured_min is not None and current_min is not None and current_min < configured_min:
                current_min = configured_min
            if configured_max is not None and current_max is not None and current_max > configured_max:
                current_max = configured_max
            if current_min is not None and current_max is not None and current_min > current_max:
                current_min, current_max = current_max, current_min

            min_is_default = configured_min is None or current_min is None or current_min <= configured_min
            max_is_default = configured_max is None or current_max is None or current_max >= configured_max
            if min_is_default and max_is_default:
                continue

            active_filters.append((attribute, current_min, current_max))
        return active_filters

    def _get_matching_range_value_ids(self, attribute, current_min, current_max):
        """Devuelve los product.attribute.value que caen dentro del rango seleccionado.

        Importante para rendimiento: se parsean solo los valores posibles del atributo,
        no los atributos de cada producto. En catálogos grandes evita recorrer miles
        de product.template en Python con lecturas ORM repetidas.
        """
        values = request.env['product.attribute.value'].sudo().search([
            ('attribute_id', '=', attribute.id),
        ])
        matching_ids = []
        for value in values:
            numeric_value = self._range_to_float(value.name)
            if numeric_value is None:
                continue
            if current_min is not None and numeric_value < current_min:
                continue
            if current_max is not None and numeric_value > current_max:
                continue
            matching_ids.append(value.id)
        return matching_ids

    def _filter_products_recordset_by_ranges(self, products):
        """Filtra un recordset de product.template con todos los rangos activos.

        Versión optimizada para catálogos grandes: primero calcula los valores
        permitidos del atributo y después deja que PostgreSQL encuentre las líneas
        de atributo coincidentes. Así evitamos recorrer producto a producto y leer
        attribute_line_ids/value_ids para miles de productos.
        """
        active_filters = self._get_active_range_filters()
        if not active_filters or not products:
            return products

        ProductTemplate = request.env['product.template'].sudo()
        AttributeLine = request.env['product.template.attribute.line'].sudo()
        filtered_ids = products.ids

        for attribute, current_min, current_max in active_filters:
            matching_value_ids = self._get_matching_range_value_ids(attribute, current_min, current_max)
            if not matching_value_ids:
                filtered_ids = []
            elif filtered_ids:
                lines = AttributeLine.search([
                    ('product_tmpl_id', 'in', filtered_ids),
                    ('attribute_id', '=', attribute.id),
                    ('value_ids', 'in', matching_value_ids),
                ])
                allowed_ids = set(lines.mapped('product_tmpl_id').ids)
                filtered_ids = [product_id for product_id in filtered_ids if product_id in allowed_ids]

            _logger.info(
                "Filtro range optimizado aplicado: atributo=%s min=%s max=%s valores_validos=%s productos_restantes=%s",
                attribute.name,
                current_min,
                current_max,
                len(matching_value_ids),
                len(filtered_ids),
            )

            if not filtered_ids:
                break

        return ProductTemplate.browse(filtered_ids).with_context(bin_size=True)

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
            if (key.startswith('range_min_') or key.startswith('range_max_')) and value not in (None, ''):
                values[key] = value
        return values
