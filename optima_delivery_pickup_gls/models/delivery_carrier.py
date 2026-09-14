from odoo import _, fields, models


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    optima_gls_tariff_enabled = fields.Boolean(
        string="Usar tarifas Optima GLS",
        help="Calcula la tarifa desde la plantilla GLS importada en lugar del precio fijo del producto.",
    )
    optima_gls_tariff_service = fields.Selection(
        [
            ("AUTO", "Automático según Servicio/Horario GLS"),
            ("SHOP_DELIVERY", "ShopDeliveryService"),
            ("BUSINESS_PARCEL", "BusinessParcel"),
        ],
        string="Servicio de tarifa GLS",
        default="AUTO",
    )
    optima_gls_tariff_book_id = fields.Many2one(
        "optima.gls.tariff.book",
        string="Libro de tarifas GLS (forzar)",
        help="Déjalo vacío para seleccionar automáticamente la plantilla activa del año vigente.",
    )

    def _optima_pickup_get_provider_code(self):
        """Expose only real GLS ParcelShop delivery methods to pickup checkout."""
        self.ensure_one()
        code = super()._optima_pickup_get_provider_code()
        if code:
            return code
        if self.delivery_type == "gls_asm" and self.gls_asm_shiptime == "19":
            return "gls"
        return False

    def _optima_gls_tariff_service_code(self):
        self.ensure_one()
        if self.optima_gls_tariff_service and self.optima_gls_tariff_service != "AUTO":
            return self.optima_gls_tariff_service
        if self.gls_asm_shiptime == "19":
            return "SHOP_DELIVERY"
        if self.gls_asm_service == "96" and self.gls_asm_shiptime == "18":
            return "BUSINESS_PARCEL"
        return False

    def _optima_gls_find_tariff_service(self, order, service_code=False):
        self.ensure_one()
        service_code = service_code or self._optima_gls_tariff_service_code()
        if not service_code:
            return self.env["optima.gls.tariff.service"]
        # Checkout tariffs are selected by tariff year, not by the historical
        # creation date of the web cart. GLS price sheets are annual commercial
        # books and their exact from/to dates remain informative metadata.
        on_date = fields.Date.context_today(order)
        year_start = on_date.replace(month=1, day=1)
        year_end = on_date.replace(month=12, day=31)
        domain = [
            ("code", "=", service_code),
            ("active", "=", True),
            ("book_id.active", "=", True),
            ("valid_from", "<=", year_end),
            ("valid_to", ">=", year_start),
        ]
        if self.optima_gls_tariff_book_id:
            domain.append(("book_id", "=", self.optima_gls_tariff_book_id.id))
        return self.env["optima.gls.tariff.service"].sudo().search(
            domain, order="valid_from desc, id desc", limit=1
        )

    def _optima_gls_tariff_rate(self, order, service_code=False):
        self.ensure_one()
        service = self._optima_gls_find_tariff_service(order, service_code=service_code)
        if not service:
            return False
        result = service.rate_order(order)
        result["tariff_service_record"] = service
        return result

    def gls_asm_rate_shipment(self, order):
        self.ensure_one()
        if not self.optima_gls_tariff_enabled:
            return super().gls_asm_rate_shipment(order)
        result = self._optima_gls_tariff_rate(order)
        if result is False:
            return {
                "success": False,
                "price": 0.0,
                "error_message": _("No hay una plantilla GLS activa para este método y año."),
                "warning_message": False,
            }
        return {
            "success": bool(result.get("success")),
            "price": float(result.get("price") or 0.0),
            "error_message": result.get("error_message") or False,
            "warning_message": result.get("warning_message") or False,
        }

    def action_optima_gls_import_tariff(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Importar tarifas GLS"),
            "res_model": "optima.gls.tariff.import.wizard",
            "view_mode": "form",
            "target": "new",
        }

    def action_optima_gls_tariff_books(self):
        self.ensure_one()
        return self.env.ref("optima_delivery_pickup_gls.action_optima_gls_tariff_book").read()[0]

    def action_optima_gls_download_tariff_template(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/optima_delivery_pickup_gls/static/xlsx/GLS_Tarifas_2026_OPTIMA.xlsx",
            "target": "self",
        }
