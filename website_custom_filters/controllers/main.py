import logging
import re

from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)


class WebsiteSaleRange(WebsiteSale):
    """Añade filtros reales de rango numérico solo a páginas de listado de /shop."""

    def _is_shop_listing_request(self):
        """True solo en listados donde deben actuar los sliders.

        Importante: en Odoo también hay fichas de producto con ruta /shop/<slug>,
        por ejemplo /shop/3300-vq22633001-producto-11069. Esas rutas NO deben
        pasar por la lógica custom del slider ni propagar parámetros del filtro.
        """
        path = getattr(getattr(request, 'httprequest', None), 'path', '') or ''
        return (
            path in ('/shop', '/shop/')
            or path.startswith('/shop/category/')
            or path.startswith('/shop/page/')
        )

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
        """Lee de la URL los filtros range_min_ID/range_max_ID activos.

        Esta función se blinda para que nunca devuelva filtros en ficha de
        producto. Así evitamos que una URL /shop/<producto> con parámetros
        heredados pueda contaminar la lógica nativa de variantes.
        """
        if not self._is_shop_listing_request():
            return []

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
            if not attribute or not attribute._wcf_is_range_attribute():
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
        """Devuelve los product.attribute.value que caen dentro del rango seleccionado."""
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

        Punto crítico de rendimiento: este método solo debe ejecutarse en listado
        y solo cuando existan range_min_/range_max_ activos. No debe intervenir
        nunca en ficha de producto.
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
                "Filtro range aplicado: atributo=%s min=%s max=%s valores_validos=%s productos_restantes=%s",
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

        if not self._is_shop_listing_request() or not self._get_active_range_filters():
            return fuzzy_search_term, product_count, search_result

        filtered_result = self._filter_products_recordset_by_ranges(search_result)
        if filtered_result != search_result:
            product_count = len(filtered_result)
        return fuzzy_search_term, product_count, filtered_result.with_context(bin_size=True)



    def _get_additional_shop_values(self, values, **post):
        """Activa el estado nativo de filtros cuando hay rangos custom activos.

        Odoo 18 pinta el botón original "Clear Filters" del offcanvas como
        disabled cuando no detecta `attrib_values`, `tags` ni rango de precio.
        Nuestros sliders usan parámetros propios `range_min_ID/range_max_ID`,
        así que el filtrado funciona, pero el botón nativo no se activa.

        La bandera se mantiene para activar los estados nativos cuando la
        plantilla los renderiza. El frontend añade un reemplazo idéntico en la
        ubicación nativa cuando Odoo omite por completo el botón.
        """
        extra_values = super()._get_additional_shop_values(values, **post)
        has_active_range_filters = bool(self._get_active_range_filters())
        extra_values.update({
            'wcf_has_active_range_filters': has_active_range_filters,
        })
        return extra_values

    def _shop_get_query_url_kwargs(
        self, category, search, min_price, max_price, order=None, tags=None, attribute_value=None, **post
    ):
        """Mantiene range_min_ID/range_max_ID solo en URLs de listado.

        Aquí es donde debes fijarte si vuelven a aparecer parámetros extraños en
        enlaces de producto: esta función controla qué parámetros conserva Odoo al
        paginar, ordenar o regenerar enlaces del shop. No debe inyectar nada en una
        ficha /shop/<producto>.
        """
        values = super()._shop_get_query_url_kwargs(
            category, search, min_price, max_price,
            order=order, tags=tags, attribute_value=attribute_value, **post
        )

        if not self._is_shop_listing_request():
            for key in list(values):
                if key.startswith('range_min_') or key.startswith('range_max_'):
                    values.pop(key, None)
            return values

        for key, value in (request.params or {}).items():
            if (key.startswith('range_min_') or key.startswith('range_max_')) and value not in (None, ''):
                values[key] = value
        return values
