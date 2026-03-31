from odoo import models, fields, api
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_open_request_optima_from_picking(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Ceder a OSE",
            "res_model": "stock.picking.request.optima.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_picking_id": self.id,
            }
        }


class StockPickingRequestOptimaWizard(models.TransientModel):
    _name = "stock.picking.request.optima.wizard"
    _description = "Wizard Ceder a Óptima desde Picking"

    picking_id = fields.Many2one("stock.picking", required=True)

    product_lines = fields.One2many(
        "stock.picking.request.optima.line",
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

    def _create_sale(self, all_lines=False):
        partner = self._get_optima_partner()

        lines = []

        for l in self.product_lines:
            qty = l.quantity

            if not all_lines and qty <= 0:
                continue

            # Seguridad: no ceder más de lo recibido
            if l.move_id and qty > l.move_id.quantity_done:
                raise UserError(
                    f"No puedes ceder más cantidad que la recibida.\n"
                    f"Producto: {l.product_id.display_name}\n"
                    f"Máximo permitido: {l.move_id.quantity_done}"
                )

            lines.append((0, 0, {
                "product_id": l.product_id.id,
                "product_uom_qty": qty,
                "price_unit": 0.0,
                "name": l.product_id.name,
                "product_uom": l.uom_id.id,
            }))

        if not lines:
            raise UserError("No hay líneas con cantidad > 0")

        sale = self.env["sale.order"].create({
            "partner_id": partner.id,
            "origin": self.picking_id.name,
            "order_line": lines,
        })

        return sale

    def action_ceder(self):
        self._create_sale(all_lines=False)

    def action_ceder_all(self):
        for l in self.product_lines:
            if l.move_id:
                l.quantity = l.move_id.quantity_done

        self._create_sale(all_lines=True)
        
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        picking_id = self.env.context.get("default_picking_id")
        if not picking_id:
            return res

        picking = self.env["stock.picking"].browse(picking_id)

        lines = []

        for move in picking.move_ids_without_package:
            if move.quantity_done <= 0:
                continue

            lines.append((0, 0, {
                "product_id": move.product_id.id,
                "quantity": move.quantity_done,
                "uom_id": move.product_uom.id,
                "move_id": move.id,
            }))

        res["product_lines"] = lines

        return res
        
class StockPickingRequestOptimaLine(models.TransientModel):
    _name = "stock.picking.request.optima.line"
    _description = "Líneas del wizard Ceder a Óptima"

    wizard_id = fields.Many2one(
        "stock.picking.request.optima.wizard",
        required=True,
        ondelete="cascade"
    )

    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(string="Cantidad")
    uom_id = fields.Many2one("uom.uom", string="UdM")
    move_id = fields.Many2one("stock.move")