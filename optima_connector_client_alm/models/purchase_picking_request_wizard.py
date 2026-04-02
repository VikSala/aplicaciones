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

        SaleLine = self.env["sale.order.line"]

        for l in self.product_lines:
            qty = l.quantity

            if not all_lines and qty <= 0:
                continue

            # Seguridad
            moves = self.picking_id.move_ids_without_package.filtered(
                lambda m: m.product_id.id == l.product_id.id
            )

            total_qty = sum(moves.mapped("product_uom_qty"))

            cedido = sum(SaleLine.search([
                ("x_source_picking_id", "=", self.picking_id.id),
                ("product_id", "=", l.product_id.id),
                ("state", "in", ["sale", "done"])
            ]).mapped("x_cedido_qty"))

            max_qty = max(total_qty - cedido, 0)

            if max_qty <= 0:
                raise UserError(
                    f"No hay cantidad disponible para ceder.\n"
                    f"Producto: {l.product_id.display_name}"
                )

            if qty > max_qty:
                raise UserError(
                    f"No puedes ceder más de lo disponible.\n"
                    f"Producto: {l.product_id.display_name}\n"
                    f"Disponible: {max_qty}"
                )
            
            lines.append((0, 0, {
                "product_id": l.product_id.id,
                "product_uom_qty": qty,
                "price_unit": 0.0,
                "name": l.product_id.name,
                "product_uom": l.uom_id.id,
                "x_cedido_qty": l.quantity,
                "x_source_picking_id": self.picking_id.id,
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
                l.quantity = l.move_id.quantity

        self._create_sale(all_lines=True)
        
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        picking_id = self.env.context.get("default_picking_id")
        if not picking_id:
            return res

        picking = self.env["stock.picking"].browse(picking_id)

        lines = []
        SaleLine = self.env["sale.order.line"]

        for move in picking.move_ids_without_package:
            if move.product_uom_qty <= 0:
                continue

            cedido = sum(SaleLine.search([
                ("x_source_picking_id", "=", picking.id),
                ("product_id", "=", move.product_id.id),
                ("state", "in", ["sale", "done"])
            ]).mapped("x_cedido_qty"))

            disponible = move.product_uom_qty - cedido
            
            lines.append((0, 0, {
                "product_id": move.product_id.id,
                "quantity": disponible,
                "cedido_qty": cedido,
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

    product_id = fields.Many2one("product.product", string="Producto", required=True)
    quantity = fields.Float(string="Cantidad")
    cedido_qty = fields.Float(string="Cedido", readonly=True)
    uom_id = fields.Many2one("uom.uom", string="Unidad")
    move_id = fields.Many2one("stock.move")