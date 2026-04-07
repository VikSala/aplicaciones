from odoo import models, fields
import xmlrpc.client

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        """Envía el pedido de compra al Odoo del proveedor (Óptima)."""
        res = super().button_confirm()
        
        # --- FILTRADO DE SEGURIDAD ---
        nombre_partner = self.partner_id.name
        es_optima = ("Óptima Soluciones Eficientes, S.L." in nombre_partner)

        if not es_optima:
            # Si no es Óptima, salimos sin chatter
            return res

        OPTIMA_URL = "https://b2b.optimaluz.com/"  # dominio del proveedor
        OPTIMA_DB = "odoo0"
        OPTIMA_USER = "admin"
        OPTIMA_PASS = "1324"

        try:
            common = xmlrpc.client.ServerProxy(f"{OPTIMA_URL}/xmlrpc/2/common", allow_none=True)
            uid = common.authenticate(OPTIMA_DB, OPTIMA_USER, OPTIMA_PASS, {})
            if not uid:
                raise Exception("❌ No se pudo autenticar con Óptima.")

            models = xmlrpc.client.ServerProxy(f"{OPTIMA_URL}/xmlrpc/2/object", allow_none=True)

            order_lines = []
            for l in self.order_line:
                order_lines.append({
                    "product_code": l.product_id.default_code,
                    "quantity": l.product_qty,
                    "price": l.price_unit,
                })

            vals = {
                "source_purchase_id": self.id,
                "partner_vat": self.company_id.vat,
                "partner_name": self.company_id.name,
                "order_ref": self.name,
                "order_lines": order_lines,
            }

            result = models.execute_kw(
                OPTIMA_DB, uid, OPTIMA_PASS,
                "optima.connector", "create_sale_order_from_api", [vals]
            )
            self.message_post(body=f"📡 Pedido enviado a Óptima: {result}")
        except Exception as e:
            self.message_post(body=f"⚠️ Error enviando pedido a Óptima: {e}")
        return res

class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    x_sale_line_id = fields.Many2one("sale.order.line")

class SaleOrder(models.Model):
    _inherit = "sale.order"
    
    def action_open_request_optima(self):
        self.ensure_one()
        
        lines = []
        for l in self.order_line:
            lines.append((0, 0, {
                "product_id": l.product_id.id,
                "quantity": l.product_uom_qty,
                "uom_id": l.product_uom.id,
                "sale_line_id": l.id,
            }))

        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order.request.optima.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_sale_id": self.id,
            }
        }

class StockReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    def action_create_returns(self):
        """Botón: Devolver"""
        res = super().action_create_returns()
        self._notify_return_to_optima(res, "action_create_returns")
        return res

    def action_create_returns_all(self):
        """Botón: Devolver todo"""
        res = super().action_create_returns_all()
        self._notify_return_to_optima(res, "action_create_returns_all")
        return res

    def action_create_exchanges(self):
        """Botón: Devolver para cambio"""
        res = super().action_create_exchanges()
        self._notify_return_to_optima(res, "action_create_exchanges")
        return res

    def _notify_return_to_optima(self, action_res, return_type):
        """Envía la devolución al Odoo proveedor (Óptima)"""

        new_picking_id = action_res.get("res_id")

        # Algunas acciones devuelven domain en lugar de res_id
        if not new_picking_id and action_res.get("domain"):
            domain = action_res["domain"]
            for d in domain:
                if d[0] == "id" and d[1] == "in":
                    new_picking_id = d[2][0]
                    break

        if not new_picking_id:
            return

        picking = self.env["stock.picking"].browse(new_picking_id)

        # localizar el pedido de compra original
        purchase = picking.move_ids_without_package.mapped(
            "purchase_line_id.order_id"
        )[:1]

        if not purchase:
            return

        # --- FILTRADO DE SEGURIDAD ---
        nombre_partner = purchase.partner_id.name
        es_optima = ("Óptima Soluciones Eficientes, S.L." in nombre_partner)

        if not es_optima:
            return
        
        # --- escribir comentario si está vacío ---
        if not purchase.x_comentarios:

            texto = {
                "action_create_returns": "Devuelto parcial",
                "action_create_returns_all": "Devuelto completo",
                "action_create_exchanges": "Devuelto para cambio",
            }.get(return_type)

            if texto:
                purchase.write({"x_comentarios": texto})

        # --- preparar líneas ---
        lines = []

        for move in picking.move_ids_without_package:

            qty = move.product_uom_qty

            lines.append({
                "product_code": move.product_id.default_code,
                "quantity": qty,
            })

        # --- datos enviados al proveedor ---
        vals = {
            "source_purchase_id": purchase.id,
            "return_type": return_type,
            "lines": lines,
        }

        # --- conexión XMLRPC ---
        URL = "https://b2b.optimaluz.com"
        DB = "odoo0"
        USER = "admin"
        PASS = "1324"

        try:

            common = xmlrpc.client.ServerProxy(
                f"{URL}/xmlrpc/2/common", allow_none=True
            )
            uid = common.authenticate(DB, USER, PASS, {})

            models_rpc = xmlrpc.client.ServerProxy(
                f"{URL}/xmlrpc/2/object", allow_none=True
            )

            result = models_rpc.execute_kw(
                DB,
                uid,
                PASS,
                "optima.connector",
                "register_return_from_api",
                [vals],
            )

            picking.message_post(
                body=f"📡 Devolución notificada a Óptima: {result}"
            )

        except Exception as e:
            picking.message_post(
                body=f"⚠️ Error notificando devolución: {e}"
            )