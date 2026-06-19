from odoo import api, fields, models


class ProductAttribute(models.Model):
    _inherit = 'product.attribute'

    # Se mantiene la opción 'range' para compatibilidad con los atributos ya creados
    # y para que puedas seguir seleccionándola en el formulario. Internamente se
    # convierte a un display_type nativo compatible con website_sale.
    display_type = fields.Selection(
        selection_add=[('range', 'Rango Numérico')],
        ondelete={'range': 'set default'},
    )

    wcf_is_range_filter = fields.Boolean(
        string="Usar como slider de rango en tienda",
        help=(
            "Activa este atributo como filtro slider en el listado de tienda. "
            "El display_type real se mantiene en un tipo nativo de Odoo para no romper "
            "el configurador de variantes de la ficha de producto."
        ),
    )
    range_min = fields.Float(string="Mínimo para el Slider", default=0.0)
    range_max = fields.Float(string="Máximo para el Slider", default=100.0)

    def init(self):
        """Migra atributos antiguos display_type='range' a un tipo nativo.

        El origen del error "Esta combinación no existe" era que website_sale no
        reconoce 'range' como display_type válido en la ficha de producto cuando
        el producto tiene más atributos de variante. Para el shop seguimos usando
        wcf_is_range_filter=True; para producto dejamos display_type='radio'.
        """
        self.env.cr.execute(
            """
            UPDATE product_attribute
               SET wcf_is_range_filter = TRUE,
                   display_type = 'radio'
             WHERE display_type = 'range'
            """
        )

    def _wcf_normalize_range_vals(self, vals):
        vals = dict(vals or {})
        if vals.get('display_type') == 'range':
            vals['wcf_is_range_filter'] = True
            vals['display_type'] = 'radio'
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._wcf_normalize_range_vals(vals) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        vals = self._wcf_normalize_range_vals(vals)
        return super().write(vals)

    def _wcf_is_range_attribute(self):
        self.ensure_one()
        return bool(self.wcf_is_range_filter or self.display_type == 'range')
