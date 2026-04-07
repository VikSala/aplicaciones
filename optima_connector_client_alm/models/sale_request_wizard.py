from odoo import models, fields, api
from odoo.exceptions import UserError

class SaleOrderRequestOptimaWizard(models.TransientModel):
    _name = "sale.order.request.optima.wizard"
    _description = "Wizard Pedir a Óptima"

    sale_id = fields.Many2one("sale.order", required=True)

    product_lines = fields.One2many(
        "sale.order.request.optima.line",
        "wizard_id",
        string="Productos"
    )
    
    def _get_optima_partner(self):
        partner = self.env["res.partner"].search([
            ("name", "ilike", "Óptima Soluciones Eficientes, S.L.")
        ], limit=1)

        if not partner:
            raise UserError("No se encontró el partner Óptima")

        return partner

    def _get_request_info(self):
        result = []

        PurchaseLine = self.env["purchase.order.line"]

        for l in self.product_lines:

            if not l.sale_line_id:
                continue

            ya_pedido = sum(PurchaseLine.search([
                ("x_sale_line_id", "=", l.sale_line_id.id),
                ("order_id.origin", "=", self.sale_id.name),
                ("state", "in", ["purchase", "done"])
            ]).mapped("product_qty"))

            vendido_real = l.quantity + l.pedido_qty
            disponible = max(vendido_real - ya_pedido, 0)

            result.append({
                "line": l,
                "ya_pedido": ya_pedido,
                "vendido_real": vendido_real,
                "disponible": disponible,
            })

        return result

    def _create_purchase(self, all_lines=False):

        partner = self._get_optima_partner()

        lines = []

        for l in self.product_lines:

            qty = l.quantity

            if not all_lines and qty <= 0:
                continue

            PurchaseLine = self.env["purchase.order.line"]

            ya_pedido = sum(PurchaseLine.search([
                ("x_sale_line_id", "=", l.sale_line_id.id),
                ("order_id.origin", "=", self.sale_id.name),
                ("state", "in", ["purchase", "done"])
            ]).mapped("product_qty"))

            # 🔥 cálculo correcto
            vendido_real = l.quantity + l.pedido_qty
            max_qty = max(vendido_real - ya_pedido, 0)
            #self.sale_id.message_post(body=f"DEBUG → disponible={max_qty} | vendido_real={vendido_real} | ya_pedido={ya_pedido}")

            # 🔴 CASO 1: ya está todo pedido
            if max_qty <= 0:
                raise UserError(
                    f"Este producto ya ha sido pedido completamente.\n"
                    f"Producto: {l.product_id.display_name}"
                )

            # 🔴 CASO 2: te pasas
            if qty > max_qty:
                raise UserError(
                    f"No puedes pedir más de lo disponible.\n"
                    f"Producto: {l.product_id.display_name}\n"
                    f"Disponible: {max_qty}"
                )
            
            lines.append((0, 0, {
                "product_id": l.product_id.id,
                "product_qty": qty,
                "price_unit": 0.0,  # FORZADO A 0
                "name": l.product_id.name,
                "product_uom": l.uom_id.id,
                "x_sale_line_id": l.sale_line_id.id,
            }))

        if not lines:
            raise UserError("No hay líneas con cantidad > 0")

        purchase = self.env["purchase.order"].create({
            "partner_id": partner.id,
            "origin": self.sale_id.name,
            "order_line": lines,
        })

        return purchase


    def action_request(self):
        self._create_purchase(all_lines=False)


    def action_request_all(self):

        for l in self.product_lines:
            if l.sale_line_id:
                l.quantity = l.sale_line_id.product_uom_qty

        self._create_purchase(all_lines=True)
    
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        sale_id = self.env.context.get("default_sale_id")
        if not sale_id:
            return res

        sale = self.env["sale.order"].browse(sale_id)

        # 🔥 creamos wizard temporal (sin guardar aún)
        wizard = self.env["sale.order.request.optima.wizard"].new({
            "sale_id": sale_id,
        })

        # 🔥 generar líneas base (como antes)
        product_lines = []
        for l in sale.order_line:
            product_lines.append((0, 0, {
                "product_id": l.product_id.id,
                "quantity": l.product_uom_qty,
                "uom_id": l.product_uom.id,
                "sale_line_id": l.id,
            }))

        res["product_lines"] = product_lines
        res["sale_id"] = sale_id

        # 🔥 ahora sí: aplicar lógica centralizada
        wizard = self.env["sale.order.request.optima.wizard"].new(res)

        info = wizard._get_request_info()

        updated_lines = []
        for data in info:
            l = data["line"]

            updated_lines.append((0, 0, {
                "product_id": l.product_id.id,
                "quantity": data["disponible"],
                "pedido_qty": data["ya_pedido"],
                "uom_id": l.uom_id.id,
                "sale_line_id": l.sale_line_id.id,
            }))

        res["product_lines"] = updated_lines

        return res
    
class SaleOrderRequestOptimaLine(models.TransientModel):
    _name = "sale.order.request.optima.line"
    _description = "Líneas del wizard Pedir a Óptima"

    wizard_id = fields.Many2one("sale.order.request.optima.wizard", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(string="Cantidad")
    pedido_qty = fields.Float(string="Pedido", readonly=True)
    uom_id = fields.Many2one("uom.uom", string="UdM")
    sale_line_id = fields.Many2one("sale.order.line")