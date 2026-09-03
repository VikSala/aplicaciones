from datetime import timedelta

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # -------------------------------------------------------------------------
    # Datos maestros / sincronizados
    # -------------------------------------------------------------------------
    optima_credit_payment_enabled = fields.Boolean(
        string="Permitir pago a crédito",
        company_dependent=True,
        default=False,
        help=(
            "Habilita al cliente para usar la futura forma de pago 'Pago a Crédito'. "
            "La fase de checkout se añadirá posteriormente."
        ),
    )
    optima_installations_risk_synced = fields.Monetary(
        string="Riesgo Instalaciones sincronizado",
        currency_field="currency_id",
        company_dependent=True,
        help=(
            "Riesgo oficial calculado en Odoo Instalaciones y sincronizado en este "
            "cliente. Es editable para permitir sincronización y correcciones manuales."
        ),
    )
    optima_installations_risk_exception = fields.Boolean(
        string="Excepción de riesgo en Instalaciones",
        company_dependent=True,
        default=False,
        help=(
            "Copia del estado de excepción/bloqueo de riesgo del Odoo Instalaciones. "
            "Si está activo, el cliente no será apto para Pago a Crédito."
        ),
    )
    optima_installations_risk_sync_date = fields.Datetime(
        string="Última sincronización Instalaciones",
        company_dependent=True,
        readonly=True,
        copy=False,
    )
    optima_risk_alert_percentage = fields.Float(
        string="Porcentaje riesgo alerta",
        company_dependent=True,
        default=80.0,
        help=(
            "Porcentaje de crédito consumido a partir del cual se muestra una alerta "
            "informativa. No bloquea por sí solo el crédito."
        ),
    )

    # -------------------------------------------------------------------------
    # Riesgo local Ecommerce
    # -------------------------------------------------------------------------
    optima_ecommerce_sale_risk = fields.Monetary(
        string="Pedidos Ecommerce pendientes",
        currency_field="currency_id",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
    )
    optima_ecommerce_invoice_draft_risk = fields.Monetary(
        string="Facturas Ecommerce borrador",
        currency_field="currency_id",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
    )
    optima_ecommerce_invoice_open_risk = fields.Monetary(
        string="Facturas Ecommerce abiertas",
        currency_field="currency_id",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
    )
    optima_ecommerce_invoice_unpaid_risk = fields.Monetary(
        string="Facturas Ecommerce vencidas",
        currency_field="currency_id",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
    )
    optima_ecommerce_risk_total = fields.Monetary(
        string="Riesgo Ecommerce",
        currency_field="currency_id",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
        help=(
            "Riesgo generado exclusivamente por pedidos creados realmente en Ecommerce. "
            "Este es el importe que debe sincronizarse hacia Odoo Instalaciones."
        ),
    )

    # -------------------------------------------------------------------------
    # Riesgo global
    # -------------------------------------------------------------------------
    optima_risk_total = fields.Monetary(
        string="Riesgo total",
        currency_field="currency_id",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
        help="Riesgo Instalaciones sincronizado + riesgo local Ecommerce.",
    )
    optima_risk_remaining_value = fields.Monetary(
        string="Crédito disponible",
        currency_field="currency_id",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
    )
    optima_risk_remaining_percentage = fields.Float(
        string="Crédito disponible (%)",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
    )
    optima_risk_exception = fields.Boolean(
        string="Excepción por riesgo",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
        help=(
            "Se activa si Instalaciones informa una excepción o si el riesgo total "
            "supera el crédito concedido."
        ),
    )
    optima_risk_alert = fields.Boolean(
        string="Alerta de riesgo",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
    )
    optima_credit_available = fields.Boolean(
        string="Crédito disponible para Ecommerce",
        compute="_compute_optima_financial_risk",
        compute_sudo=True,
        help=(
            "Indicador técnico para la futura fase de checkout. Requiere crédito "
            "habilitado, límite positivo, ausencia de excepción y saldo disponible."
        ),
    )

    @api.model
    def _commercial_fields(self):
        return super()._commercial_fields() + [
            "optima_credit_payment_enabled",
            "optima_installations_risk_synced",
            "optima_installations_risk_exception",
            "optima_installations_risk_sync_date",
            "optima_risk_alert_percentage",
        ]

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        prepared_vals_list = []
        watched_fields = {
            "optima_installations_risk_synced",
            "optima_installations_risk_exception",
        }
        for vals in vals_list:
            vals = dict(vals)
            if (
                watched_fields.intersection(vals)
                and "optima_installations_risk_sync_date" not in vals
            ):
                vals["optima_installations_risk_sync_date"] = now
            prepared_vals_list.append(vals)
        return super().create(prepared_vals_list)

    def write(self, vals):
        watched_fields = {
            "optima_installations_risk_synced",
            "optima_installations_risk_exception",
        }
        if (
            watched_fields.intersection(vals)
            and "optima_installations_risk_sync_date" not in vals
        ):
            vals = dict(vals)
            vals["optima_installations_risk_sync_date"] = fields.Datetime.now()
        return super().write(vals)

    @api.depends_context("company")
    @api.depends(
        "credit_limit",
        "optima_credit_payment_enabled",
        "optima_installations_risk_synced",
        "optima_installations_risk_exception",
        "optima_risk_alert_percentage",
    )
    def _compute_optima_financial_risk(self):
        """Calcula el riesgo para la compañía activa.

        Los pedidos históricos importados desde Instalaciones no participan porque
        el dominio exige sale.order.is_ecommerce = True.

        El tránsito pedido -> factura evita doble conteo:
        - una factura en borrador incrementa qty_invoiced de la línea de venta y,
          por tanto, reduce el riesgo de pedido;
        - simultáneamente su saldo entra en riesgo de factura borrador;
        - al publicar, pasa a abierto/vencido;
        - al conciliar/cobrar, amount_residual cae y deja de consumir riesgo.
        """
        company = self.env.company
        company_currency = company.currency_id
        today = fields.Date.context_today(self)

        # Inicialización explícita para todos los registros, incluidos contactos hijos.
        for partner in self:
            partner.optima_ecommerce_sale_risk = 0.0
            partner.optima_ecommerce_invoice_draft_risk = 0.0
            partner.optima_ecommerce_invoice_open_risk = 0.0
            partner.optima_ecommerce_invoice_unpaid_risk = 0.0
            partner.optima_ecommerce_risk_total = 0.0
            partner.optima_risk_total = 0.0
            partner.optima_risk_remaining_value = 0.0
            partner.optima_risk_remaining_percentage = 0.0
            partner.optima_risk_exception = False
            partner.optima_risk_alert = False
            partner.optima_credit_available = False

        commercial_partners = self.mapped("commercial_partner_id")
        if not commercial_partners:
            return

        # 1) Pedidos confirmados originados realmente en Ecommerce.
        #
        # No usamos únicamente el Monetary almacenado de la línea. Calculamos el
        # importe vivo desde las relaciones reales con las facturas para que, en el
        # mismo instante en que aparece una factura (también en borrador), el importe
        # deje de estar en el bloque de PV y pase al bloque de factura.
        sale_lines = self.env["sale.order.line"].sudo().search(
            [
                ("company_id", "=", company.id),
                ("order_id.is_ecommerce", "=", True),
                ("state", "=", "sale"),
                ("optima_risk_partner_id", "in", commercial_partners.ids),
            ]
        )
        sale_risk_by_partner = {}
        for line in sale_lines:
            risk_partner = line.optima_risk_partner_id
            if not risk_partner:
                continue
            sale_risk_by_partner[risk_partner.id] = (
                sale_risk_by_partner.get(risk_partner.id, 0.0)
                + line._optima_get_live_ecommerce_risk_amount()
            )

        # 2) Facturas Ecommerce.
        #
        # La fuente de verdad no es solo account.move.is_ecommerce. También
        # reconocemos como Ecommerce cualquier factura que esté realmente enlazada
        # mediante sus líneas a un sale.order con is_ecommerce=True. Con ello quedan
        # cubiertas facturas ya existentes cuya marca no se hubiera propagado y
        # personalizaciones de terceros que alteren _prepare_invoice().
        ecommerce_moves = self.env["account.move"].sudo().search(
            [
                ("company_id", "=", company.id),
                ("move_type", "in", ("out_invoice", "out_refund")),
                ("commercial_partner_id", "in", commercial_partners.ids),
                "|",
                ("is_ecommerce", "=", True),
                (
                    "invoice_line_ids.sale_line_ids.order_id.is_ecommerce",
                    "=",
                    True,
                ),
            ]
        )

        receivable_base_domain = [
            ("company_id", "=", company.id),
            ("move_id", "in", ecommerce_moves.ids),
            ("account_type", "=", "asset_receivable"),
        ]

        draft_by_partner = {}
        open_by_partner = {}
        unpaid_by_partner = {}

        for commercial_partner in commercial_partners:
            partner_domain = [
                ("move_id.commercial_partner_id", "=", commercial_partner.id),
            ]

            draft_lines = self.env["account.move.line"].sudo().search(
                receivable_base_domain
                + partner_domain
                + [("parent_state", "=", "draft")]
            )
            draft_by_partner[commercial_partner.id] = sum(
                draft_lines.mapped("amount_residual")
            )

            posted_lines = self.env["account.move.line"].sudo().search(
                receivable_base_domain
                + partner_domain
                + [
                    ("parent_state", "=", "posted"),
                    ("reconciled", "=", False),
                ]
            )

            open_amount = 0.0
            unpaid_amount = 0.0
            for line in posted_lines:
                maturity_date = line.date_maturity or line.date
                if maturity_date and maturity_date < today:
                    unpaid_amount += line.amount_residual
                else:
                    open_amount += line.amount_residual

            open_by_partner[commercial_partner.id] = open_amount
            unpaid_by_partner[commercial_partner.id] = unpaid_amount

        # 3) Asignación a cada partner solicitado usando su entidad comercial.
        for partner in self:
            commercial = partner.commercial_partner_id
            # Los importes de venta/contabilidad ya están en moneda de compañía.
            sale_risk = sale_risk_by_partner.get(commercial.id, 0.0)
            draft_risk = draft_by_partner.get(commercial.id, 0.0)
            open_risk = open_by_partner.get(commercial.id, 0.0)
            unpaid_risk = unpaid_by_partner.get(commercial.id, 0.0)

            ecommerce_total = sale_risk + draft_risk + open_risk + unpaid_risk
            installations_risk = commercial.with_company(company).optima_installations_risk_synced
            total_risk = ecommerce_total + installations_risk
            credit_limit = commercial.with_company(company).sudo().credit_limit
            remaining = credit_limit - total_risk
            remaining_percentage = (
                round(100.0 * remaining / credit_limit, 2)
                if credit_limit
                else 0.0
            )
            consumed_percentage = (
                100.0 - remaining_percentage if credit_limit else 0.0
            )
            installations_exception = commercial.with_company(
                company
            ).optima_installations_risk_exception
            risk_exception = bool(
                installations_exception
                or (credit_limit > 0.0 and total_risk > credit_limit)
            )
            alert_percentage = commercial.with_company(company).optima_risk_alert_percentage

            partner.optima_ecommerce_sale_risk = sale_risk
            partner.optima_ecommerce_invoice_draft_risk = draft_risk
            partner.optima_ecommerce_invoice_open_risk = open_risk
            partner.optima_ecommerce_invoice_unpaid_risk = unpaid_risk
            partner.optima_ecommerce_risk_total = ecommerce_total
            partner.optima_risk_total = total_risk
            partner.optima_risk_remaining_value = remaining
            partner.optima_risk_remaining_percentage = remaining_percentage
            partner.optima_risk_exception = risk_exception
            partner.optima_risk_alert = bool(
                credit_limit > 0.0
                and alert_percentage > 0.0
                and consumed_percentage >= alert_percentage
            )
            partner.optima_credit_available = bool(
                commercial.with_company(company).optima_credit_payment_enabled
                and credit_limit > 0.0
                and not risk_exception
                and remaining > 0.0
            )
