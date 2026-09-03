from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    is_ecommerce = fields.Boolean(
        string="Factura Ecommerce",
        default=False,
        index=True,
        copy=True,
        help=(
            "Marca las facturas y abonos procedentes de pedidos Ecommerce para que "
            "solo su saldo participe en el riesgo financiero Ecommerce."
        ),
    )

    def _optima_sync_ecommerce_flag_from_sale_lines(self):
        """Autocorrige la marca usando la relación real factura <-> pedido.

        La marca se propaga normalmente desde ``sale.order._prepare_invoice``, pero
        usamos además la relación ``invoice_line_ids.sale_line_ids`` como fuente de
        verdad. Esto hace el módulo robusto ante otros módulos que personalicen la
        creación de facturas y ante facturas antiguas creadas antes de esta mejora.
        """
        candidates = self.filtered(
            lambda move: move.move_type in ("out_invoice", "out_refund")
            and not move.is_ecommerce
        )
        for move in candidates:
            ecommerce_orders = move.invoice_line_ids.sale_line_ids.order_id.filtered(
                "is_ecommerce"
            )
            if ecommerce_orders:
                move.is_ecommerce = True

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._optima_sync_ecommerce_flag_from_sale_lines()
        for company, partners in moves._optima_get_risk_sync_map().items():
            partners._optima_queue_ecommerce_risk_sync(company=company)
        return moves

    def action_post(self):
        # Última autocorrección antes de que la factura empiece a formar parte del
        # riesgo contable abierto/vencido.
        self._optima_sync_ecommerce_flag_from_sale_lines()
        return super().action_post()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        """Propaga la marca Ecommerce a notas de crédito/reversiones."""
        if not default_values_list:
            default_values_list = [{} for move in self]
        else:
            default_values_list = [dict(vals or {}) for vals in default_values_list]

        for move, values in zip(self, default_values_list):
            values.setdefault("is_ecommerce", move.is_ecommerce)

        moves = super()._reverse_moves(
            default_values_list=default_values_list,
            cancel=cancel,
        )
        moves._optima_sync_ecommerce_flag_from_sale_lines()
        return moves

    def _optima_is_ecommerce_risk_move(self):
        self.ensure_one()
        if self.move_type not in ("out_invoice", "out_refund"):
            return False
        return bool(
            self.is_ecommerce
            or self.invoice_line_ids.sale_line_ids.order_id.filtered("is_ecommerce")
        )

    def _optima_get_risk_sync_map(self):
        result = {}
        for move in self.filtered(lambda m: m._optima_is_ecommerce_risk_move()):
            result.setdefault(move.company_id, self.env["res.partner"])
            result[move.company_id] |= move.commercial_partner_id
        return result

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
