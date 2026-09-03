from odoo import api, fields, models
from odoo.tools import float_round


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    optima_company_currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="company_id.currency_id",
        string="Moneda compañía (riesgo)",
        readonly=True,
    )
    optima_risk_partner_id = fields.Many2one(
        comodel_name="res.partner",
        related="order_id.partner_invoice_id.commercial_partner_id",
        string="Entidad comercial de riesgo",
        store=True,
        index=True,
        readonly=True,
    )
    optima_ecommerce_risk_amount = fields.Monetary(
        string="Riesgo pendiente Ecommerce",
        currency_field="optima_company_currency_id",
        compute="_compute_optima_ecommerce_risk_amount",
        compute_sudo=True,
        store=True,
        help=(
            "Importe del pedido todavía no trasladado a factura. Las facturas en "
            "borrador ya reducen este importe, evitando contar dos veces el mismo riesgo."
        ),
    )

    def _optima_get_live_invoiced_qty(self):
        """Cantidad facturada calculada directamente desde las líneas enlazadas.

        No dependemos exclusivamente del valor almacenado de ``qty_invoiced``. Esto
        evita que una caché/recomputación pendiente mantenga temporalmente el PV en
        riesgo después de haber creado su factura. Replica el criterio base de Odoo:
        cuenta facturas salvo canceladas y resta los abonos ligados a la línea de venta.
        """
        self.ensure_one()
        qty_invoiced = 0.0
        for invoice_line in self.invoice_lines:
            move = invoice_line.move_id
            if move.state == "cancel" and move.payment_state != "invoicing_legacy":
                continue
            qty = invoice_line.product_uom_id._compute_quantity(
                invoice_line.quantity,
                self.product_uom,
                round=False,
            )
            if move.move_type == "out_invoice":
                qty_invoiced += qty
            elif move.move_type == "out_refund":
                qty_invoiced -= qty
        return qty_invoiced

    def _optima_get_live_ecommerce_risk_amount(self):
        """Riesgo vivo de la línea, en moneda de compañía."""
        self.ensure_one()
        if self.state != "sale" or self.display_type:
            return 0.0

        qty = self.product_uom_qty
        if self.product_id.invoice_policy == "delivery":
            # Criterio prudente heredado del planteamiento OCA: mientras siga
            # existiendo cantidad no facturada, mantenemos el compromiso del PV.
            qty = max(qty, self.qty_delivered)

        qty_invoiced = self._optima_get_live_invoiced_qty()
        rounding = self.product_uom.rounding if self.product_uom else 0.01
        risk_qty = float_round(
            qty - qty_invoiced,
            precision_rounding=rounding or 0.01,
        )

        if not risk_qty:
            return 0.0

        if self.product_uom_qty:
            amount = self.price_total * (risk_qty / self.product_uom_qty)
        else:
            amount = self.price_reduce_taxinc * risk_qty

        order_date = (
            self.order_id.date_order.date()
            if self.order_id.date_order
            else fields.Date.context_today(self)
        )
        return self.order_id.currency_id._convert(
            amount,
            self.company_id.currency_id,
            self.company_id,
            order_date,
            round=False,
        )

    @api.depends(
        "state",
        "display_type",
        "price_total",
        "price_reduce_taxinc",
        "product_uom_qty",
        "qty_delivered",
        "qty_invoiced",
        "product_id.invoice_policy",
        "order_id.currency_id",
        "order_id.date_order",
        "company_id.currency_id",
        "invoice_lines",
        "invoice_lines.quantity",
        "invoice_lines.product_uom_id",
        "invoice_lines.move_id.state",
        "invoice_lines.move_id.move_type",
        "invoice_lines.move_id.payment_state",
    )
    def _compute_optima_ecommerce_risk_amount(self):
        for line in self:
            line.optima_ecommerce_risk_amount = (
                line._optima_get_live_ecommerce_risk_amount()
            )

    def _optima_get_risk_sync_map(self):
        result = {}
        for line in self.filtered(
            lambda line: line.order_id.is_ecommerce and line.order_id.state == "sale"
        ):
            result.setdefault(line.company_id, self.env["res.partner"])
            result[line.company_id] |= line.order_id.partner_invoice_id.commercial_partner_id
        return result

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for company, partners in lines._optima_get_risk_sync_map().items():
            partners._optima_queue_ecommerce_risk_sync(company=company)
        return lines

    def write(self, vals):
        before = self._optima_get_risk_sync_map()
        result = super().write(vals)
        after = self._optima_get_risk_sync_map()
        for company in set(before) | set(after):
            partners = (
                before.get(company, self.env["res.partner"])
                | after.get(company, self.env["res.partner"])
            ).exists()
            if partners:
                partners._optima_queue_ecommerce_risk_sync(company=company)
        return result

    def unlink(self):
        before = self._optima_get_risk_sync_map()
        result = super().unlink()
        for company, partners in before.items():
            partners.exists()._optima_queue_ecommerce_risk_sync(company=company)
        return result
