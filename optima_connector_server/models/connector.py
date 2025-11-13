from odoo import models, fields, api, _
from odoo.exceptions import UserError

class OptimaConnector(models.Model):
    _name = "optima.connector"
    _description = "Conector API para pedidos de clientes externos"

    name = fields.Char("Referencia del pedido del cliente")
    partner_id = fields.Many2one("res.partner", "Cliente", required=True)
    order_id = fields.Many2one("sale.order", "Pedido de venta generado")
    state = fields.Selection([
        ("received", "Recibido"),
        ("error", "Error"),
        ("processed", "Procesado"),
    ], default="received")
    
    @api.model
    def create_sale_order_from_api(self, vals):
        """Recibe un pedido vía XML-RPC y lo convierte en pedido de venta."""
        partner_vat = vals.get("partner_vat")
        if not partner_vat:
            raise UserError("No se ha proporcionado el VAT (NIF) del cliente.")

        partner = self.env["res.partner"].search([("vat", "=", partner_vat)], limit=1)
        if not partner:
            raise UserError(f"No se encontró ningún cliente con VAT {partner_vat}.")

        order_lines = []
        for l in vals.get("order_lines", []):
            product = self.env["product.product"].search([
                ("default_code", "=", l.get("product_code"))
            ], limit=1)
            if not product:
                raise UserError(f"Producto {l.get('product_code')} no encontrado.")

            order_lines.append((0, 0, {
                "product_id": product.id,
                "product_uom_qty": l.get("quantity"),
                "price_unit": l.get("price"),
                "name": product.name,
            }))

        sale_vals = {
            "partner_id": partner.id,
            "origin": vals.get("order_ref"),
            "order_line": order_lines,
        }

        order = self.env["sale.order"].create(sale_vals)

        self.create({
            "name": vals.get("order_ref"),
            "partner_id": partner.id,
            "order_id": order.id,
            "state": "processed",
        })

        return {"status": "success", "order_id": order.id, "order_name": order.name}