import logging
import socket
import xmlrpc.client
from datetime import timedelta

from odoo import api, fields, models, SUPERUSER_ID

_logger = logging.getLogger(__name__)


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout=8):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout=8):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


class OptimaEcommerceRiskSyncQueue(models.Model):
    _name = "optima.ecommerce.risk.sync.queue"
    _description = "Cola sincronización riesgo Ecommerce"
    _order = "write_date asc, id asc"

    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        ondelete="cascade",
        index=True,
    )
    pending = fields.Boolean(default=True, required=True, index=True)
    next_attempt = fields.Datetime(default=fields.Datetime.now, index=True)
    last_attempt = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    @api.model
    def _get_connection_config(self):
        params = self.env["ir.config_parameter"].sudo()
        enabled = params.get_param(
            "optima_ecommerce_credit.risk_sync_enabled", "False"
        )
        return {
            "enabled": str(enabled).lower() in ("1", "true", "yes", "on"),
            "url": (params.get_param("optima_ecommerce_credit.risk_sync_url") or "").rstrip("/"),
            "db": params.get_param("optima_ecommerce_credit.risk_sync_db") or "",
            "username": params.get_param("optima_ecommerce_credit.risk_sync_username") or "",
            "password": params.get_param("optima_ecommerce_credit.risk_sync_password") or "",
            "timeout": int(params.get_param("optima_ecommerce_credit.risk_sync_timeout", "8") or 8),
        }

    @api.model
    def _get_transport(self, url, timeout):
        if url.lower().startswith("https://"):
            return _TimeoutSafeTransport(timeout=timeout)
        return _TimeoutTransport(timeout=timeout)

    def _get_current_risk(self):
        self.ensure_one()
        partner = (
            self.partner_id.commercial_partner_id.sudo().with_company(self.company_id)
        )
        partner.invalidate_recordset(
            [
                "optima_ecommerce_sale_risk",
                "optima_ecommerce_invoice_draft_risk",
                "optima_ecommerce_invoice_open_risk",
                "optima_ecommerce_invoice_unpaid_risk",
                "optima_ecommerce_risk_total",
            ]
        )
        return partner, partner.optima_ecommerce_risk_total

    def _find_remote_partner(self, object_proxy, config, uid, vat=False, name=False):
        def _unique_commercial_root(domain):
            ids = object_proxy.execute_kw(
                config["db"], uid, config["password"], "res.partner", "search",
                [domain], {"limit": 3, "context": {"active_test": False}},
            )
            if not ids:
                return False
            if len(ids) == 1:
                return ids[0]

            rows = object_proxy.execute_kw(
                config["db"], uid, config["password"], "res.partner", "search_read",
                [[("id", "in", ids)]],
                {"fields": ["id", "parent_id", "commercial_partner_id"], "context": {"active_test": False}},
            )
            root_ids = []
            for row in rows:
                commercial = row.get("commercial_partner_id")
                commercial_id = commercial[0] if isinstance(commercial, (list, tuple)) else commercial
                if commercial_id == row["id"] or not row.get("parent_id"):
                    root_ids.append(row["id"])
            root_ids = list(dict.fromkeys(root_ids))
            return root_ids[0] if len(root_ids) == 1 else False

        # Primera opción: NIF/VAT exacto.
        if vat:
            partner_id = _unique_commercial_root([("vat", "=", vat)])
            if partner_id:
                return partner_id, "vat"

        # Fallback: nombre exacto, únicamente si resuelve a un único contacto
        # comercial. No usamos ilike para evitar asignaciones aproximadas.
        if name:
            partner_id = _unique_commercial_root([("name", "=", name)])
            if partner_id:
                return partner_id, "name"

        return False, False

    def _process_one(self):
        self.ensure_one()
        if not self.pending:
            return True

        config = self._get_connection_config()
        now = fields.Datetime.now()

        if not config["enabled"]:
            self.sudo().write({
                "pending": False,
                "last_attempt": now,
                "last_error": False,
            })
            return True

        missing = [
            key
            for key in ("url", "db", "username", "password")
            if not config.get(key)
        ]
        if missing:
            error = "Configuración XML-RPC incompleta: %s" % ", ".join(missing)
            self.sudo().write({
                "pending": True,
                "last_attempt": now,
                "next_attempt": now + timedelta(minutes=5),
                "last_error": error,
            })
            return False

        partner, risk_amount = self._get_current_risk()
        vat = (partner.vat or "").strip()
        name = (partner.name or "").strip()
        if not vat and not name:
            error = "El cliente no tiene NIF/VAT ni nombre; no se puede localizar en Instalaciones."
            self.sudo().write({
                "pending": True,
                "last_attempt": now,
                "next_attempt": now + timedelta(minutes=30),
                "last_error": error,
            })
            partner.with_context(skip_optima_risk_sync=True).write({
                "optima_ecommerce_risk_sync_error": error,
            })
            return False

        currency = self.company_id.currency_id
        last_sent = partner.optima_ecommerce_risk_last_sent
        if (
            partner.optima_ecommerce_risk_last_sync_date
            and not partner.optima_ecommerce_risk_sync_error
            and currency.compare_amounts(last_sent, risk_amount) == 0
        ):
            self.sudo().write({
                "pending": False,
                "last_attempt": now,
                "last_error": False,
            })
            return True

        try:
            transport = self._get_transport(config["url"], config["timeout"])
            common = xmlrpc.client.ServerProxy(
                "%s/xmlrpc/2/common" % config["url"],
                allow_none=True,
                transport=transport,
            )
            uid = common.authenticate(
                config["db"], config["username"], config["password"], {}
            )
            if not uid:
                raise ValueError("Autenticación XML-RPC rechazada por Odoo Instalaciones.")

            # ServerProxy no debe compartir la misma instancia de Transport entre
            # dos proxies/conexiones simultáneas.
            object_proxy = xmlrpc.client.ServerProxy(
                "%s/xmlrpc/2/object" % config["url"],
                allow_none=True,
                transport=self._get_transport(config["url"], config["timeout"]),
            )
            remote_partner_id, match_method = self._find_remote_partner(
                object_proxy, config, uid, vat=vat, name=name
            )
            if not remote_partner_id:
                criteria = []
                if vat:
                    criteria.append("NIF/VAT %s" % vat)
                if name:
                    criteria.append("nombre exacto %s" % name)
                raise ValueError(
                    "No se ha encontrado un único contacto raíz en Instalaciones por %s."
                    % " ni por ".join(criteria)
                )
            if match_method == "name":
                _logger.info(
                    "Partner %s sincronizado por fallback de nombre exacto: %s",
                    partner.id, name,
                )

            object_proxy.execute_kw(
                config["db"],
                uid,
                config["password"],
                "res.partner",
                "write",
                [[remote_partner_id], {"ecommerce_risk_synced": float(risk_amount)}],
                {"context": {"tracking_disable": True}},
            )

            sync_date = fields.Datetime.now()
            partner.with_context(skip_optima_risk_sync=True).write({
                "optima_ecommerce_risk_last_sent": risk_amount,
                "optima_ecommerce_risk_last_sync_date": sync_date,
                "optima_ecommerce_risk_sync_error": False,
            })
            self.sudo().write({
                "pending": False,
                "last_attempt": sync_date,
                "last_error": False,
            })
            return True

        except (xmlrpc.client.Error, OSError, socket.error, ValueError) as exc:
            error = str(exc)
            _logger.warning(
                "No se pudo sincronizar el riesgo Ecommerce del partner %s (%s): %s",
                partner.id,
                vat,
                error,
            )
            retry_at = fields.Datetime.now() + timedelta(minutes=5)
            partner.with_context(skip_optima_risk_sync=True).write({
                "optima_ecommerce_risk_sync_error": error,
            })
            self.sudo().write({
                "pending": True,
                "last_attempt": fields.Datetime.now(),
                "next_attempt": retry_at,
                "last_error": error,
            })
            return False

    @api.model
    def _cron_process_pending(self, limit=50):
        queues = self.sudo().search(
            [
                ("pending", "=", True),
                "|",
                ("next_attempt", "=", False),
                ("next_attempt", "<=", fields.Datetime.now()),
            ],
            limit=limit,
            order="next_attempt asc, id asc",
        )
        for queue in queues:
            queue._process_one()
        return True
