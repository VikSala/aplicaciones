from odoo import models
import xmlrpc.client

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        """Envía el pedido de compra al Odoo del proveedor (Óptima)."""
        res = super().button_confirm()

        OPTIMA_URL = "https://b2b.optimaluz.com/"  # dominio del proveedor
        OPTIMA_DB = "odoo0"
        OPTIMA_USER = "admin"
        OPTIMA_PASS = "admin"

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
