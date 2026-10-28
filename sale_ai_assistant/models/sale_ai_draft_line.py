from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleAIDraftLine(models.Model):
    _name = "sale.ai.draft.line"
    _description = "Línea de propuesta de presupuesto IA"
    _order = "sequence, id"
    _check_company_auto = True

    draft_id = fields.Many2one(
        "sale.ai.draft", string="Borrador", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(
        related="draft_id.company_id", store=True, readonly=True, index=True,
        string="Compañía"
    )
    user_id = fields.Many2one(
        related="draft_id.user_id", store=True, readonly=True, index=True,
        string="Propietario"
    )
    currency_id = fields.Many2one(
        related="draft_id.currency_id", readonly=True, string="Moneda"
    )
    sequence = fields.Integer(string="Orden", default=10)
    line_kind = fields.Selection(
        [("product", "Producto"), ("line_section", "Sección"),
         ("line_note", "Nota")],
        default="product", required=True, string="Tipo de línea"
    )
    source_sale_line_id = fields.Integer(
        string="ID de línea del presupuesto de origen", readonly=True, copy=False,
        help="Identificador estable aunque otro usuario elimine la línea en Odoo.",
    )
    product_id = fields.Many2one("product.product", string="Producto", check_company=True)
    name = fields.Text(string="Descripción propuesta", required=True)
    product_uom_qty = fields.Float(string="Cantidad", default=1.0, digits="Product Unit of Measure")
    product_uom_id = fields.Many2one("uom.uom", string="Unidad de medida")
    price_unit = fields.Monetary(currency_field="currency_id", string="Precio unitario propuesto")
    discount = fields.Float(string="Descuento (%)", digits="Discount")
    price_source = fields.Selection(
        [("odoo", "Catálogo Odoo"), ("pricelist", "Tarifa del cliente Odoo"),
         ("history", "Referencia histórica"),
         ("external", "Referencia externa verificada"),
         ("estimate", "Estimación IA"), ("user", "Fijado por el usuario")],
        default="estimate", required=True, string="Origen del precio"
    )
    price_evidence = fields.Text(
        string="Justificación del precio / referencia",
        help="No etiquetar como verificada una cifra sin fuente consultada."
    )
    amount_estimate = fields.Monetary(
        compute="_compute_amount_estimate", currency_field="currency_id",
        string="Importe provisional sin impuestos"
    )

    @api.depends("line_kind", "product_uom_qty", "price_unit", "discount")
    def _compute_amount_estimate(self):
        for line in self:
            line.amount_estimate = (
                line.product_uom_qty * line.price_unit * (1 - line.discount / 100.0)
                if line.line_kind == "product" else 0.0
            )

    @api.constrains("product_uom_qty", "discount", "line_kind", "price_unit")
    def _check_estimated_values(self):
        for line in self:
            if line.product_uom_qty < 0 or not 0 <= line.discount <= 100:
                raise ValidationError(_("Cantidad negativa o descuento fuera del rango de 0 a 100."))
            if line.line_kind != "product" and (line.price_unit or line.product_uom_qty):
                raise ValidationError(_("Las secciones y notas no pueden tener cantidades ni precios."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("source_sale_line_id") and not self.env.context.get("sale_ai_internal_edit"):
                raise UserError(_("No se puede asociar manualmente una línea del presupuesto."))
            draft = self.env["sale.ai.draft"].browse(vals["draft_id"])
            draft.session_id._ensure_can_edit_draft()
            if vals.get("line_kind") in ("line_section", "line_note"):
                vals.update({"product_uom_qty": 0, "price_unit": 0, "discount": 0,
                             "product_id": False, "product_uom_id": False})
        return super().create(vals_list)

    def write(self, vals):
        if "source_sale_line_id" in vals and not self.env.context.get("sale_ai_internal_edit"):
            raise UserError(_("No se puede modificar la línea real asociada al borrador."))
        if "draft_id" in vals:
            raise UserError(_("No se puede trasladar una línea a otro presupuesto."))
        self.mapped("draft_id.session_id")._ensure_can_edit_draft()
        if vals.get("line_kind") in ("line_section", "line_note"):
            vals = dict(vals, product_uom_qty=0, price_unit=0, discount=0,
                        product_id=False, product_uom_id=False)
        return super().write(vals)

    def unlink(self):
        self.mapped("draft_id.session_id")._ensure_can_edit_draft()
        return super().unlink()
