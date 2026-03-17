from odoo import models, fields
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


    def _create_purchase(self, all_lines=False):

        partner = self._get_optima_partner()

        lines = []

        for l in self.product_lines:

            qty = l.quantity

            if not all_lines and qty <= 0:
                continue

            lines.append((0, 0, {
                "product_id": l.product_id.id,
                "product_qty": qty,
                "price_unit": 0.0,  # FORZADO A 0
                "name": l.product_id.name,
                "product_uom": l.uom_id.id,
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
    
    
class SaleOrderRequestOptimaLine(models.TransientModel):
    _name = "sale.order.request.optima.line"
    _description = "Líneas del wizard Pedir a Óptima"

    wizard_id = fields.Many2one("sale.order.request.optima.wizard", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(string="Cantidad")
    uom_id = fields.Many2one("uom.uom", string="UdM")
    sale_line_id = fields.Many2one("sale.order.line")