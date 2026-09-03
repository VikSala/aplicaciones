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
