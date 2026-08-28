from odoo import models, fields, api
from odoo.exceptions import UserError

class SaleOrderRequestOptimaWizard(models.TransientModel):
    _name = "sale.order.request.optima.wizard"
    _description = "Wizard Pedir a Óptima"

    sale_id = fields.Many2one(
        "sale.order",
        string="Pedido de venta",
        required=True
    )

    product_lines = fields.One2many(
        "sale.order.request.optima.line",
        "wizard_id",
        string="Líneas"
    )

    # -------------------------
    # AUXILIAR: PARTNER ÓPTIMA
    # -------------------------
    def _get_optima_partner(self):
        self.ensure_one()

        company = self.sale_id.company_id

        partner = self.env["res.partner"].with_company(company).search([
            ("name", "ilike", "Óptima Soluciones Eficientes, S.L."),
            ("company_id", "in", [False, company.id]),
        ], limit=1)

        if not partner:
            raise UserError(
                f"No se encontró el partner Óptima para la compañía {company.display_name}"
            )

        return partner

    # -------------------------
    # DEFAULT_GET
    # -------------------------
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        sale_id = self.env.context.get("default_sale_id")
        if not sale_id:
            return res

        sale = self.env["sale.order"].browse(sale_id)

        lines = []
        for l in sale.order_line:
            if not l.product_id:
                continue

            lines.append((0, 0, {
                "product_id": l.product_id.id,
                "quantity": l.product_uom_qty,
                "uom_id": l.product_uom.id,
                "sale_line_id": l.id,
            }))

        res.update({
            "sale_id": sale.id,
            "product_lines": lines,
        })

        return res

    # -------------------------
    # CREAR PEDIDO DE COMPRA
    # -------------------------
    def _create_purchase(self):
        self.ensure_one()

        if not self.product_lines:
            raise UserError("No hay líneas para pedir.")

        partner = self._get_optima_partner()

        purchase_lines = []
        PurchaseLine = self.env["purchase.order.line"]

        for line in self.product_lines:
            sale_line = line.sale_line_id

            if not sale_line:
                sale_line = self.sale_id.order_line.filtered(
                    lambda l: l.product_id == line.product_id
                )[:1]

            if not sale_line:
                raise UserError(
                    f"No se encontró línea de venta para el producto {line.product_id.display_name}"
                )

            # -------------------------
            # YA PEDIDO (ACUMULADO)
            # -------------------------
            company = self.sale_id.company_id

            ya_pedido = sum(
                PurchaseLine.with_company(company).search([
                    ("company_id", "=", company.id),
                    ("x_sale_line_id", "=", sale_line.id),
                    ("product_id", "=", line.product_id.id),
                    ("order_id.origin", "=", self.sale_id.name),
                    ("order_id.state", "in", ["purchase", "done"]),
                ]).mapped("product_qty")
            )

            # -------------------------
            # VALIDACIÓN TOTAL
            # -------------------------
            if (line.quantity + ya_pedido) > sale_line.product_uom_qty:
                raise UserError(
                    f"No puedes pedir más de lo vendido.\n\n"
                    f"Producto: {line.product_id.display_name}\n"
                    f"Vendido: {sale_line.product_uom_qty}\n"
                    f"Ya pedido: {ya_pedido}\n"
                    f"Intentas pedir ahora: {line.quantity}\n"
                    f"Total sería: {line.quantity + ya_pedido}"
                )

            purchase_lines.append((0, 0, {
                "product_id": line.product_id.id,
                "product_qty": line.quantity,
                "product_uom": line.uom_id.id,
                "price_unit": 0.0,
                "date_planned": fields.Datetime.now(),
                "x_sale_line_id": sale_line.id,
                "name": line.product_id.display_name,
            }))

        company = self.sale_id.company_id

        purchase = self.env["purchase.order"].with_company(company).create({
            "company_id": company.id,
            "partner_id": partner.id,
            "origin": self.sale_id.name,
            "order_line": purchase_lines,
        })

        return purchase

    # -------------------------
    # BOTONES
    # -------------------------
    def action_request(self):
        purchase = self._create_purchase()
        return {
            "type": "ir.actions.act_window",
            "res_model": "purchase.order",
            "res_id": purchase.id,
            "view_mode": "form",
        }

    def action_request_all(self):
        for line in self.product_lines:
            if line.sale_line_id:
                line.quantity = line.sale_line_id.product_uom_qty

        return self.action_request()
    
class SaleOrderRequestOptimaLine(models.TransientModel):
    _name = "sale.order.request.optima.line"
    _description = "Línea solicitud a Óptima"

    wizard_id = fields.Many2one(
        "sale.order.request.optima.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade"
    )

    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True
    )

    quantity = fields.Float(
        string="Cantidad",
        default=1.0,
        required=True
    )

    uom_id = fields.Many2one(
        "uom.uom",
        string="Unidad de medida",
        required=True
    )

    # Opcional pero MUY recomendable
    sale_line_id = fields.Many2one(
        "sale.order.line",
        string="Línea de venta origen"
    )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id