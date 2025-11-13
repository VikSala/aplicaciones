from odoo import models
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
