from odoo import models, fields
import xmlrpc.client

class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    x_cedido_qty = fields.Float(string="Cantidad cedida acumulada")
    x_source_picking_id = fields.Many2one("stock.picking")

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        res = super().action_confirm()

        for order in self:

            # --- FILTRO ---
            if "Óptima Soluciones Eficientes, S.L." not in order.partner_id.name:
                continue

            # --- DATOS CONEXIÓN ---
            URL = "https://b2b.optimaluz.com"
            DB = "odoo0"
            USER = "admin"
            PASS = "1324"

            try:
                common = xmlrpc.client.ServerProxy(
                    f"{URL}/xmlrpc/2/common", allow_none=True
                )
                uid = common.authenticate(DB, USER, PASS, {})

                if not uid:
                    raise Exception("No se pudo autenticar")

                models_rpc = xmlrpc.client.ServerProxy(
                    f"{URL}/xmlrpc/2/object", allow_none=True
                )

                # --- PREPARAR LÍNEAS ---
                order_lines = []

                for l in order.order_line:
                    order_lines.append({
                        "product_code": l.product_id.default_code,
                        "quantity": l.product_uom_qty,
                        "price": l.price_unit,
                    })

                # --- PAYLOAD ---
                vals = {
                    "source_sale_id": order.id,
                    "partner_name": order.company_id.name,
                    "partner_vat": order.company_id.vat,
                    "order_ref": order.name,
                    "origin": order.origin,
                    "order_lines": order_lines,
                }

                # --- LLAMADA REMOTA ---
                result = models_rpc.execute_kw(
                    DB,
                    uid,
                    PASS,
                    "optima.connector",
                    "create_purchase_order_from_api",  # 👈 NUEVO MÉTODO
                    [vals],
                )

                order.message_post(
                    body=f"📡 Pedido enviado a Óptima (compra remota): {result}"
                )

            except Exception as e:
                order.message_post(
                    body=f"⚠️ Error enviando pedido a Óptima: {e}"
                )

        return res