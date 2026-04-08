from odoo import models, api
import xmlrpc.client
import requests
import io

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        """Confirma el pedido y envía automáticamente el correo 'Ventas: confirmación de pedido'."""
        res = super().action_confirm()

        for order in self:
            try:
                # Buscar la plantilla exacta por nombre
                template = self.env["mail.template"].search(
                    [("name", "=", "Ventas: confirmación de pedido")],
                    limit=1
                )
                if not template:
                    order.message_post(body="⚠️ No se encontró la plantilla 'Ventas: confirmación de pedido'.")
                    continue

                # Enviar correo
                mail_id = template.send_mail(order.id, force_send=True)
                order.message_post(
                    body=f"📧 Correo enviado automáticamente (Plantilla '{template.name}', mail ID {mail_id})."
                )
            except Exception as e:
                order.message_post(body=f"⚠️ Error al enviar correo automático: {e}")

            #Imprimir
            try:
                # Acción de descarga directa del PDF
                pdf_url = f"/report/pdf/sale.report_saleorder/{order.id}"
                return {
                    "type": "ir.actions.act_url",
                    "url": pdf_url,
                    "target": "new",  # abre en nueva pestaña
                }
            except Exception as e:
                order.message_post(body=f"⚠️ Error al generar descarga PDF: {e}")

        return res

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
        es_optima = ("ALMAITANA DE LUZ, S.L." in nombre_partner)

        if not es_optima:
            return
        
        # --- escribir comentario si está vacío ---
        if not purchase.x_comentarios:

            texto = {
                "action_create_returns": "Devuelto a cliente",
                "action_create_returns_all": "Devuelto a cliente",
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
            "x_id_interno": purchase.x_id_interno,
            "return_type": return_type,
            "lines": lines,
        }

        # --- conexión XMLRPC ---
        URL = "https://optimaluz.com"
        DB = "odoo1"
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