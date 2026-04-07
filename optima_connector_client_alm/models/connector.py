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
    def register_return_from_api(self, vals):

        x_id_interno = vals.get("x_id_interno")
        return_type = vals.get("return_type")
        lines = vals.get("lines", [])

        if not x_id_interno:
            raise UserError("No se ha recibido x_id_interno")

        # Buscar el pedido de venta vinculado
        sale = self.env["sale.order"].search(
            [("id", "=", x_id_interno)],
            limit=1
        )

        if not sale:
            raise UserError(f"No se encontró sale.order con x_id_interno={x_id_interno}")

        # Buscar picking de entrega ya validado
        picking = sale.picking_ids.filtered(lambda p: p.state == "done")[:1]

        if not picking:
            raise UserError("No hay picking entregado para devolver")

        # Crear wizard de devolución
        wizard = self.env["stock.return.picking"].with_context(
            active_id=picking.id,
            active_ids=[picking.id],
            active_model="stock.picking"
        ).create({})

        # Mapear cantidades por SKU
        qty_map = {l["product_code"]: l["quantity"] for l in lines}

        for line in wizard.product_return_moves:

            # CAMBIO IMPORTANTE → coger el SKU del movimiento original
            sku = line.move_id.product_id.default_code

            if sku not in qty_map:
                line.quantity = 0
                continue

            if return_type == "action_create_returns_all":
                continue

            line.quantity = qty_map[sku]

        # Ejecutar devolución
        if return_type == "action_create_returns":
            wizard.action_create_returns()

        elif return_type == "action_create_returns_all":
            wizard.action_create_returns_all()

        elif return_type == "action_create_exchanges":
            wizard.action_create_exchanges()

        else:
            raise UserError(f"Tipo de devolución desconocido: {return_type}")

        # --- escribir comentario en el pedido ---
        texto = {
            "action_create_returns": "Devuelto a cliente",
            "action_create_returns_all": "Devuelto a cliente",
            "action_create_exchanges": "Devuelto para cambio",
        }.get(return_type)

        if texto:
            sale.write({
                "x_comentarios": texto
            })

        return {
            "status": "success",
            "sale_order": sale.name,
            "return_type": return_type,
        }