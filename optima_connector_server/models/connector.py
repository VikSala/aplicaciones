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
        partner_vat = (vals.get("partner_vat") or "").strip()
        partner_name = (vals.get("partner_name") or "").strip()

        # Buscar cliente por VAT o nombre
        partner = None
        if partner_vat:
            partner = self.env["res.partner"].search([("vat", "=", partner_vat)], limit=1)
        if not partner and partner_name:
            partner = self.env["res.partner"].search([("name", "=", partner_name)], limit=1)

        if not partner:
            raise UserError(
                f"No se encontró ningún cliente con VAT '{partner_vat}' ni nombre '{partner_name}'."
            )

        # Construir líneas del pedido
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

        # Crear pedido de venta
        sale_vals = {
            "x_id_interno": vals.get("source_purchase_id"),
            "partner_id": partner.id,
            "origin": vals.get("order_ref"),
            "order_line": order_lines,
        }

        order = self.env["sale.order"].create(sale_vals)

        # Registrar la creación en optima.connector
        self.create({
            "name": vals.get("order_ref"),
            "partner_id": partner.id,
            "order_id": order.id,
            "state": "processed",
        })

        return {
            "status": "success",
            "order_id": order.id,
            "order_name": order.name,
            "partner": partner.display_name,
        }
        
    @api.model
    def register_return_from_api(self, vals):

        source_purchase_id = vals.get("source_purchase_id")
        return_type = vals.get("return_type")
        lines = vals.get("lines", [])

        if not source_purchase_id:
            raise UserError("No se ha recibido source_purchase_id")

        # Buscar el pedido de venta vinculado
        sale = self.env["sale.order"].search(
            [("x_id_interno", "=", source_purchase_id)],
            limit=1
        )

        if not sale:
            raise UserError(f"No se encontró sale.order con x_id_interno={source_purchase_id}")

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
            "action_create_returns": "Devuelto parcial",
            "action_create_returns_all": "Devuelto completo",
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
        
    @api.model
    def create_purchase_order_from_api(self, vals):

        if not vals:
            raise UserError("No se recibieron datos")

        # --- DATOS ENTRADA ---
        order_lines = vals.get("order_lines", [])
        partner_name = vals.get("partner_name")
        partner_vat = vals.get("partner_vat")
        order_ref = vals.get("order_ref")
        origin = vals.get("origin")

        if not order_lines:
            raise UserError("No hay líneas para crear el pedido")

        # --------------------------------------------------
        # 🧩 1. BUSCAR / CREAR PARTNER (CLIENTE ORIGEN)
        # --------------------------------------------------

        partner = self.env["res.partner"].search([
            ("vat", "=", partner_vat)
        ], limit=1)

        if not partner:
            partner = self.env["res.partner"].create({
                "name": partner_name or "Cliente API",
                "vat": partner_vat,
                "supplier_rank": 1,
            })

        # --------------------------------------------------
        # 🧩 2. CREAR LÍNEAS DE COMPRA
        # --------------------------------------------------

        lines = []

        for l in order_lines:

            product_code = l.get("product_code")
            qty = l.get("quantity")
            price = l.get("price", 0.0)

            if not product_code:
                continue

            product = self.env["product.product"].search([
                ("default_code", "=", product_code)
            ], limit=1)

            if not product:
                raise UserError(f"Producto no encontrado: {product_code}")

            lines.append((0, 0, {
                "product_id": product.id,
                "product_qty": qty,
                "price_unit": price,
                "name": product.name,
                "product_uom": product.uom_po_id.id,
            }))

        if not lines:
            raise UserError("No se pudieron generar líneas válidas")

        # --------------------------------------------------
        # 🧩 3. CREAR PEDIDO DE COMPRA
        # --------------------------------------------------

        purchase = self.env["purchase.order"].create({
            "x_id_interno": vals.get("source_sale_id"),
            "partner_id": partner.id,
            "origin": order_ref or origin,
            "order_line": lines,
        })

        return {
            "purchase_id": purchase.id,
            "purchase_name": purchase.name,
        }