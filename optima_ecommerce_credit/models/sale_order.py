from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    is_ecommerce = fields.Boolean(
        string="Pedido Ecommerce",
        default=False,
        index=True,
        copy=False,
        help=(
            "Indica que el pedido se ha originado realmente en la tienda online. "
            "Los pedidos históricos sincronizados desde Instalaciones deben permanecer "
            "desmarcados para que no consuman riesgo Ecommerce."
        ),
    )

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            # website_sale crea el carrito/pedido indicando website_id desde el inicio.
            # Integraciones/importaciones pueden forzar explícitamente False.
            if "is_ecommerce" not in vals and vals.get("website_id"):
                vals["is_ecommerce"] = True
            prepared_vals_list.append(vals)
        orders = super().create(prepared_vals_list)
        for company, partners in orders._optima_get_risk_sync_map().items():
            partners._optima_queue_ecommerce_risk_sync(company=company)
        return orders

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals["is_ecommerce"] = self.is_ecommerce
        return vals

    def _get_invoice_grouping_keys(self):
        """Nunca mezclar en una misma factura pedidos Ecommerce y no Ecommerce."""
        keys = super()._get_invoice_grouping_keys()
        if "is_ecommerce" not in keys:
            keys = [*keys, "is_ecommerce"]
        return keys

    # -------------------------------------------------------------------------
    # Pago a Crédito
    # -------------------------------------------------------------------------
    def _optima_get_credit_partner(self):
        self.ensure_one()
        return (
            self.partner_invoice_id.commercial_partner_id.sudo().with_company(
                self.company_id
            )
        )

    def _optima_get_credit_required_company_currency(self):
        """Importe del pedido que debe quedar cubierto por crédito, en moneda compañía."""
        self.ensure_one()
        date = (
            self.date_order.date()
            if self.date_order
            else fields.Date.context_today(self)
        )
        return self.currency_id._convert(
            self.amount_total,
            self.company_id.currency_id,
            self.company_id,
            date,
            round=True,
        )

    def _optima_get_available_credit_order_currency(self):
        """Crédito disponible expresado en la moneda del pedido para mostrar en checkout."""
        self.ensure_one()
        partner = self._optima_get_credit_partner()
        partner.invalidate_recordset(
            [
                "optima_ecommerce_sale_risk",
                "optima_ecommerce_invoice_draft_risk",
                "optima_ecommerce_invoice_open_risk",
                "optima_ecommerce_invoice_unpaid_risk",
                "optima_ecommerce_risk_total",
                "optima_risk_total",
                "optima_risk_remaining_value",
                "optima_risk_remaining_percentage",
                "optima_risk_exception",
                "optima_credit_available",
            ]
        )
        available_company = max(partner.optima_risk_remaining_value, 0.0)
        date = (
            self.date_order.date()
            if self.date_order
            else fields.Date.context_today(self)
        )
        return self.company_id.currency_id._convert(
            available_company,
            self.currency_id,
            self.company_id,
            date,
            round=True,
        )

    def _optima_get_credit_status(self, lock_partner=False):
        """Devuelve la elegibilidad del pedido para Pago a Crédito.

        ``lock_partner=True`` serializa la confirmación de pedidos del mismo cliente
        para evitar que dos checkouts simultáneos consuman el mismo saldo disponible.
        """
        self.ensure_one()
        partner = self._optima_get_credit_partner()

        if lock_partner:
            self.env.cr.execute(
                "SELECT id FROM res_partner WHERE id = %s FOR UPDATE",
                [partner.id],
            )

        # Los campos de riesgo no son almacenados y consultan pedidos/facturas en
        # tiempo real. Invalidamos la caché antes de una decisión de pago.
        partner.invalidate_recordset(
            [
                "credit_limit",
                "optima_credit_payment_enabled",
                "optima_installations_risk_synced",
                "optima_installations_risk_exception",
                "optima_ecommerce_sale_risk",
                "optima_ecommerce_invoice_draft_risk",
                "optima_ecommerce_invoice_open_risk",
                "optima_ecommerce_invoice_unpaid_risk",
                "optima_ecommerce_risk_total",
                "optima_risk_total",
                "optima_risk_remaining_value",
                "optima_risk_remaining_percentage",
                "optima_risk_exception",
                "optima_credit_available",
            ]
        )

        required = self._optima_get_credit_required_company_currency()
        available = partner.optima_risk_remaining_value
        company_currency = self.company_id.currency_id

        if not self.is_ecommerce:
            return {
                "allowed": False,
                "reason": _("El pedido no está marcado como pedido Ecommerce."),
                "available": available,
                "required": required,
            }
        if self.state not in ("draft", "sent"):
            return {
                "allowed": False,
                "reason": _("El pedido ya no está pendiente de confirmación."),
                "available": available,
                "required": required,
            }
        if not partner.optima_credit_payment_enabled:
            return {
                "allowed": False,
                "reason": _("El cliente no tiene habilitado el Pago a Crédito."),
                "available": available,
                "required": required,
            }
        if company_currency.compare_amounts(partner.credit_limit, 0.0) <= 0:
            return {
                "allowed": False,
                "reason": _("El cliente no tiene crédito concedido."),
                "available": available,
                "required": required,
            }
        if partner.optima_risk_exception:
            return {
                "allowed": False,
                "reason": _("El cliente está bloqueado por excepción de riesgo."),
                "available": available,
                "required": required,
            }
        if company_currency.compare_amounts(available, required) < 0:
            return {
                "allowed": False,
                "reason": _(
                    "El crédito disponible no es suficiente para confirmar este pedido."
                ),
                "available": available,
                "required": required,
            }

        return {
            "allowed": True,
            "reason": False,
            "available": available,
            "required": required,
        }

    def _optima_can_pay_on_credit(self):
        self.ensure_one()
        return self._optima_get_credit_status(lock_partner=False)["allowed"]

    def _optima_validate_credit_payment(self, lock_partner=False):
        """Valida en backend el Pago a Crédito o lanza ValidationError."""
        self.ensure_one()
        status = self._optima_get_credit_status(lock_partner=lock_partner)
        if not status["allowed"]:
            raise ValidationError(status["reason"])
        return True

    def _optima_get_risk_sync_map(self):
        result = {}
        for order in self.filtered(lambda o: o.is_ecommerce and o.state == "sale"):
            result.setdefault(order.company_id, self.env["res.partner"])
            result[order.company_id] |= order.partner_invoice_id.commercial_partner_id
        return result

    def write(self, vals):
        before = self._optima_get_risk_sync_map()
        result = super().write(vals)
        after = self._optima_get_risk_sync_map()
        companies = set(before) | set(after)
        for company in companies:
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
