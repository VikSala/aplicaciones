from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    ecommerce_risk_synced = fields.Monetary(
        string="Riesgo Ecommerce sincronizado",
        currency_field="risk_currency_id",
        help=(
            "Riesgo financiero calculado en el Odoo Ecommerce y sincronizado "
            "con este contacto. Este importe es informativo y no modifica el "
            "riesgo financiero oficial calculado por account_financial_risk."
        ),
    )

    total_risk_synced = fields.Monetary(
        string="Riesgo total sincronizado",
        currency_field="risk_currency_id",
        compute="_compute_total_risk_synced",
        help=(
            "Suma del riesgo financiero oficial de Instalaciones y del riesgo "
            "sincronizado desde Ecommerce. Es un dato exclusivamente informativo."
        ),
    )

    ecommerce_risk_sync_date = fields.Datetime(
        string="Última sincronización Ecommerce",
        readonly=True,
        copy=False,
        help="Fecha y hora de la última actualización del riesgo Ecommerce.",
    )

    @api.depends("risk_total", "ecommerce_risk_synced")
    def _compute_total_risk_synced(self):
        for partner in self:
            partner.total_risk_synced = (
                partner.risk_total + partner.ecommerce_risk_synced
            )

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        prepared_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            if (
                "ecommerce_risk_synced" in vals
                and "ecommerce_risk_sync_date" not in vals
            ):
                vals["ecommerce_risk_sync_date"] = now
            prepared_vals_list.append(vals)
        return super().create(prepared_vals_list)

    def write(self, vals):
        """Registra cuándo se actualiza el riesgo recibido desde Ecommerce.

        El sincronizador puede enviar explícitamente ecommerce_risk_sync_date.
        Si no lo hace, cualquier escritura del importe actualizará la fecha
        automáticamente.
        """
        if (
            "ecommerce_risk_synced" in vals
            and "ecommerce_risk_sync_date" not in vals
        ):
            vals = dict(vals)
            vals["ecommerce_risk_sync_date"] = fields.Datetime.now()
        return super().write(vals)
