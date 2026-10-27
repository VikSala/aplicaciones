"""Bounded, opt-in Spanish market research; no web scraping or price fabrication.

Tavily results are *search excerpts* and not validated supplier quotations.  The
AI must not present extracted figures as verified prices without manual review.
"""
import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

import requests

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

from .sale_ai_draft_tools import SaleAIDraftTools

_logger = logging.getLogger(__name__)
TAVILY_ENDPOINT = "https://api.tavily.com/search"
KEY_PREFIX = "sale_ai_assistant.market."


def market_setting(env, company_id, field, default):
    value = env["ir.config_parameter"].sudo().get_param(
        "%s%s.%s" % (KEY_PREFIX, field, company_id))
    return default if value is None else value


def _bounded_int(env, company_id, field, default, minimum, maximum):
    try:
        value = int(market_setting(env, company_id, field, default))
    except (ValueError, TypeError):
        value = default
    return min(max(value, minimum), maximum)


def _dec(value, label, ceiling=100000000):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("%s debe ser un número." % label)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("%s inválido." % label)
    if not number.is_finite() or not 0 <= number <= ceiling:
        raise ValueError("%s fuera de rango." % label)
    return number


def _money(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# Searches must identify a purchasable material, rather than the generic word
# "precio" (which otherwise retrieves Spanish/English dictionaries).
_MATERIAL_GROUPS = {
    "cable": ("cable", "conductor", "manguera", "h07z1", "h07v", "cobre"),
    "tubo": ("tubo", "tuberia", "corrugado", "canalizacion"),
    "caja": ("caja estanca", "cajas estancas", "caja derivacion", "caja de derivacion", "registro estanco"),
    "magnetotermico": ("magnetotermico", "automatico magnetotermico", "interruptor automatico"),
    "diferencial": ("diferencial", "interruptor diferencial"),
    "guardamotor": ("guardamotor", "protector motor", "arrancador motor"),
    "bridas": ("bridas", "brida de nylon", "brida plastica"),
    "tacos": ("tacos de fijacion", "taco fijacion", "tacos nylon", "taco nylon"),
    "bornas": ("borna", "regleta conexion", "conector electrico", "clema"),
}
_EXCLUDED_MARKET_HOSTS = (
    "wordreference.com", "collinsdictionary.com", "dictionary.cambridge.org",
    "linguee.com", "reverso.net", "deepl.com", "wiktionary.org",
)


def _plain(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(c for c in value if not unicodedata.combining(c)).replace("×", "x")


def _material_family(query):
    text = _plain(query)
    found = [family for family, aliases in _MATERIAL_GROUPS.items()
             if any(alias in text for alias in aliases)]
    # Two distinct material families are not one meaningful product search.
    return found[0] if len(found) == 1 else None


def _relevant_market_result(query, family, title, content, url):
    """Reject translations and mismatched materials/dimensions deterministically.

    Relevance is deliberately conservative. Rejecting a possibly useful result
    is safer than presenting a dictionary page as a Spanish supplier.
    """
    host = (urlparse(url).hostname or "").lower()
    if any(host == blocked or host.endswith("." + blocked)
           for blocked in _EXCLUDED_MARKET_HOSTS):
        return False
    text = _plain("%s %s %s" % (title, content, url))
    if not any(alias in text for alias in _MATERIAL_GROUPS[family]):
        return False
    # Critical electrical specs (e.g. 2,5 mm² or 25 mm) must be present.
    # Do not accidentally match a 1.5 mm conductor to a 2.5 mm request.
    query_dimensions = re.findall(r"(\d+(?:[.,]\d+)?)\s*(mm2|mm²|mm|cm|kw)\b",
                                  _plain(query))
    normalized_text = re.sub(r"\s+", "", text.replace(",", "."))
    for value, unit in query_dimensions:
        dimension = value.replace(",", ".") + unit.replace("²", "2")
        if dimension not in normalized_text.replace("²", "2"):
            return False
    return True


def _unit_price_signal(text):
    """Only report explicit per-unit price text; never infer prices from snippets."""
    match = re.search(r"(?<![\d])\d{1,6}(?:[.,]\d{1,2})?\s*(?:€|eur)\s*/\s*(?:m|metro|ud|unidad)\b",
                      text, flags=re.IGNORECASE)
    return match.group(0)[:45] if match else ""


class SaleAIMarketUsage(models.Model):
    _name = "sale.ai.market.usage"
    _description = "Consumo de búsquedas web del asistente comercial"
    _order = "id desc"

    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="restrict")
    session_id = fields.Many2one("sale.ai.session", ondelete="set null", index=True)
    query_hash = fields.Char(required=True, size=64)
    provider = fields.Selection([("tavily", "Tavily")], default="tavily", required=True)
    result_count = fields.Integer(default=0)
    queried_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    # No query text, returned snippets or API credentials are stored here.

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group("sales_team.group_sale_manager"):
            raise AccessError(_("Solo administradores de Ventas pueden realizar búsquedas web."))
        for vals in vals_list:
            if vals.get("company_id") != self.env.company.id or vals.get("user_id") != self.env.uid:
                raise AccessError(_("No se pueden registrar consultas de otra compañía o usuario."))
        return super().create(vals_list)


class SaleAICommercialTools(SaleAIDraftTools):
    """Phase 5 tools: transparent calculations + optional market search."""

    def __init__(self, session):
        super().__init__(session)
        self.market_queries_this_turn = 0
        self.market_sources_this_turn = []

    def _market_enabled(self):
        return bool(self.company.sale_ai_allow_online_research and market_setting(
            self.env, self.company.id, "api_key", ""))

    def definitions(self):
        defs = super().definitions()
        obj = lambda props, required=(): {
            "type": "object", "properties": props, "required": list(required),
            "additionalProperties": False,
        }
        n = lambda description: {"type": "number", "description": description}
        defs.append({"type": "function", "function": {
            "name": "calculate_cost_breakdown",
            "description": "Calculadora aritmética determinista (SIN consulta web). Materiales con cantidades y precios aportados/estimados, operarios, horas, tarifa y margen. Devuelve base económica SIN IVA; no establece fiscalidad ni escribe el borrador.",
            "parameters": obj({
                "materials": {"type": "array", "maxItems": 15, "items": obj({
                    "name": {"type": "string", "description": "Descripción corta."},
                    "quantity": n("Cantidad de materiales."),
                    "unit_price": n("Precio por unidad SIN IVA (estimación o fuente aportada)."),
                    "unit": {"type": "string", "description": "m, ud, lote..."},
                    "source": {"type": "string", "enum": ["odoo", "external_snippet", "user", "estimate"],
                               "description": "Origen de referencia; external_snippet nunca significa precio verificado."},
                }, ("name", "quantity", "unit_price", "unit", "source"))},
                "workers": n("Número de operarios, 0 si no aplica."),
                "hours_per_worker": n("Horas por operario, 0 si no aplica."),
                "hourly_rate": n("Tarifa de venta por hora SIN IVA, 0 si no aplica."),
                "extra_amount": n("Otros conceptos en euros sin IVA."),
                "markup_percent": n("Recargo comercial adicional porcentual (0-200), NO margen sobre venta."),
            }, ("materials", "workers", "hours_per_worker", "hourly_rate")),
        }})
        defs.append({"type": "function", "function": {
            "name": "get_customer_pricelist_price",
            "description": "Calcula en servidor la tarifa Odoo aplicable a un producto y cantidad para el cliente ya asignado al borrador o indicado por ID real. Devuelve moneda y precio unitario sin cálculo fiscal; no es precio de mercado externo.",
            "parameters": obj({
                "product_id": {"type": "integer", "description": "ID de product.product localizado en Odoo."},
                "quantity": n("Cantidad de venta, mayor que cero."),
                "customer_id": {"type": "integer", "description": "ID real del cliente, opcional si está seleccionado en el borrador."},
            }, ("product_id", "quantity")),
        }})
        if self._market_enabled():
            defs.append({"type": "function", "function": {
                "name": "search_market_prices",
                "description": "Busca UN material eléctrico específico por consulta (por ejemplo cable cobre 2,5 mm2, tubo corrugado 25 mm o caja estanca 100x100). NUNCA buscar solo 'precio', 'precios medios' o más de un material a la vez. Devuelve enlaces y extractos NO verificados, no cotizaciones. Sin información de clientes.",
                "parameters": obj({"query": {"type": "string", "description":
                    "Un material específico con sección/medida y tipo, 3-140 caracteres. NO incluyas clientes, direcciones ni datos personales."}}, ("query",)),
            }})
        return defs

    def execute(self, name, raw_arguments):
        if name not in {"calculate_cost_breakdown", "search_market_prices", "get_customer_pricelist_price"}:
            return super().execute(name, raw_arguments)
        import json
        if not isinstance(raw_arguments, str) or len(raw_arguments) > 3500:
            return {"error": "Argumentos inválidos o demasiado largos."}
        try:
            args = json.loads(raw_arguments)
            if not isinstance(args, dict):
                raise ValueError("Se requiere objeto JSON.")
            if name == "calculate_cost_breakdown":
                return self.calculate_cost_breakdown(args)
            if name == "get_customer_pricelist_price":
                if set(args) - {"product_id", "quantity", "customer_id"} or not (
                        {"product_id", "quantity"} <= set(args)):
                    raise ValueError("Campos inválidos para consulta de tarifa.")
                return self.get_customer_pricelist_price(**args)
            if set(args) != {"query"}:
                raise ValueError("Solo se permite el argumento query.")
            return self.search_market_prices(args["query"])
        except (ValueError, TypeError) as exc:
            return {"error": str(exc)[:220]}

    def get_customer_pricelist_price(self, product_id, quantity, customer_id=None):
        if type(product_id) is not int or product_id <= 0:
            raise ValueError("ID de producto inválido.")
        if customer_id is not None and (type(customer_id) is not int or customer_id <= 0):
            raise ValueError("ID de cliente inválido.")
        qty = _dec(quantity, "cantidad", 1000000)
        if qty == 0:
            raise ValueError("La cantidad debe ser mayor que cero.")
        product = self._real_product(product_id)
        partner = self._partner(customer_id) if customer_id else self.draft.partner_id
        if not partner:
            return {"error": "Primero identifica un cliente de Odoo para calcular su tarifa."}
        # Read with the current company and regular ORM access rules, never sudo.
        partner = partner.with_company(self.company)
        pricelist = self.draft.pricelist_id or partner.property_product_pricelist
        if not pricelist:
            return {"error": "No se encontró tarifa válida para el cliente."}
        pricelist = self.env["product.pricelist"].search([
            ("id", "=", pricelist.id), ("active", "=", True),
            ("company_id", "in", [False, self.company.id]),
        ], limit=1)
        if not pricelist:
            return {"error": "Tarifa no activa o no accesible en esta compañía."}
        price = pricelist.with_company(self.company)._get_product_price(
            product.with_company(self.company), float(qty), uom=product.uom_id)
        return {"source": "odoo.product.pricelist", "customer_id": partner.id,
                "product_id": product.id, "quantity": float(qty),
                "pricelist_id": pricelist.id, "pricelist": pricelist.display_name[:95],
                "unit_price": round(price, 4), "currency": pricelist.currency_id.name,
                "taxes": "NOT_CALCULATED",
                "warning": "Precio calculado según la tarifa Odoo actual para esta cantidad. Sin reglas fiscales de sale.order ni descuento adicional; revisar antes de emitir un presupuesto."}

    @staticmethod
    def calculate_cost_breakdown(args):
        allowed = {"materials", "workers", "hours_per_worker", "hourly_rate",
                   "extra_amount", "markup_percent"}
        if set(args) - allowed:
            raise ValueError("Parámetros no permitidos.")
        materials = args.get("materials")
        if not isinstance(materials, list) or len(materials) > 15:
            raise ValueError("Se admiten hasta 15 conceptos de material.")
        subtotal = Decimal(0)
        material_lines = []
        for item in materials:
            if not isinstance(item, dict) or set(item) != {
                    "name", "quantity", "unit_price", "unit", "source"}:
                raise ValueError("Concepto de material incorrecto.")
            if item["source"] not in ("odoo", "external_snippet", "user", "estimate"):
                raise ValueError("Origen desconocido.")
            name = str(item["name"]).strip()[:100]
            unit = str(item["unit"]).strip()[:18]
            if not name or not unit:
                raise ValueError("Material sin nombre o unidad.")
            qty = _dec(item["quantity"], "cantidad")
            price = _dec(item["unit_price"], "precio unitario")
            line_amount = qty * price
            subtotal += line_amount
            material_lines.append({"name": name, "unit": unit, "quantity": float(qty),
                                   "unit_price_eur": _money(price),
                                   "subtotal_eur": _money(line_amount), "source": item["source"]})
        workers = _dec(args.get("workers", 0), "operarios", 100)
        hours = _dec(args.get("hours_per_worker", 0), "horas", 2000)
        rate = _dec(args.get("hourly_rate", 0), "tarifa por hora", 100000)
        extra = _dec(args.get("extra_amount", 0), "otros conceptos")
        markup = _dec(args.get("markup_percent", 0), "recargo", 200)
        labor = workers * hours * rate
        initial = subtotal + labor + extra
        suggested = initial * (1 + markup / 100)
        return {
            "source": "deterministic_calculation_not_supplier_quote",
            "currency": "EUR", "taxes": "NOT_CALCULATED",
            "materials": material_lines,
            "materials_subtotal_eur": _money(subtotal),
            "labor_formula": "%s operarios × %s h × %s EUR/h" % (workers, hours, rate),
            "labor_subtotal_eur": _money(labor),
            "extra_eur": _money(extra), "reference_base_eur": _money(initial),
            "markup_percent": float(markup),
            "suggested_sales_base_eur": _money(suggested),
            "warning": "Los precios de entrada pueden ser estimaciones. NO es cotización contrastada. El IVA y las reglas fiscales los determinará Odoo; no se ha creado ningún sale.order.",
        }

    def search_market_prices(self, query):
        if not self._market_enabled():
            return {"error": "Búsqueda web no habilitada; configura Tavily y actívala en Conexión Vercel IA."}
        if not isinstance(query, str):
            raise ValueError("La consulta debe ser texto.")
        query = " ".join(query.strip().split())
        if not 3 <= len(query) <= 140 or any(ord(c) < 32 for c in query):
            raise ValueError("La consulta debe contener de 3 a 140 caracteres.")
        if re.search(r"https?://|www\.|@|\b\d{8}[A-Z]\b|\b(?:\+34)?[67]\d{8}\b", query, re.I):
            raise ValueError("No envíes direcciones web ni información personal de clientes.")
        family = _material_family(query)
        if not family:
            return {"error": "Búsqueda demasiado genérica o de varios materiales: indica UN material específico con medida, por ejemplo 'cable cobre 2,5 mm2' o 'tubo corrugado 25 mm'. No busques 'precio' solo."}
        # Protect the current customer's commercial identity from accidental
        # export to the search provider when the LLM disobeys instructions.
        partner = self.draft.partner_id
        protected = [partner.name if partner else "", self.company.name]
        simple_query = " ".join(query.casefold().split())
        for name in protected:
            simple_name = " ".join((name or "").casefold().split())
            if len(simple_name) >= 5 and simple_name in simple_query:
                raise ValueError("No incluyas el cliente o la compañía en búsquedas externas.")
        max_turn = _bounded_int(self.env, self.company.id, "per_turn", 4, 1, 12)
        max_session = _bounded_int(self.env, self.company.id, "per_session", 4, 1, 12)
        max_month = _bounded_int(self.env, self.company.id, "per_month", 60, 1, 1000)
        if self.market_queries_this_turn >= max_turn:
            return {"error": "Límite configurado de %s búsquedas por respuesta alcanzado." % max_turn}
        usage = self.env["sale.ai.market.usage"]
        # Serialize the quota check across simultaneous sessions for a company.
        self.env.cr.execute("SELECT id FROM res_company WHERE id = %s FOR UPDATE", [self.company.id])
        first_day = fields.Datetime.to_string(datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None))
        if usage.search_count([("company_id", "=", self.company.id),
                               ("queried_at", ">=", first_day)]) >= max_month:
            return {"error": "Cupo mensual de búsqueda web del asistente agotado."}
        if usage.search_count([("session_id", "=", self.session.id)]) >= max_session:
            return {"error": "Cupo de búsqueda web de esta conversación agotado."}
        key = market_setting(self.env, self.company.id, "api_key", "")
        timeout = _bounded_int(self.env, self.company.id, "timeout", 9, 3, 18)
        count = _bounded_int(self.env, self.company.id, "results", 4, 2, 5)
        self.market_queries_this_turn += 1
        try:
            response = requests.post(TAVILY_ENDPOINT,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"query": query + " comprar suministro material eléctrico precio por unidad euros España",
                      "search_depth": "basic", "max_results": count,
                      "exclude_domains": list(_EXCLUDED_MARKET_HOSTS),
                      "include_answer": False, "include_raw_content": False,
                      "include_images": False},
                timeout=timeout)
            if response.status_code == 429:
                return {"error": "Tavily ha limitado las peticiones o agotado el crédito. No se ha obtenido información web."}
            if response.status_code in (401, 403):
                return {"error": "Clave de Tavily no válida o sin permisos."}
            if response.status_code != 200:
                return {"error": "Servicio de búsqueda web no disponible (HTTP %s)." % response.status_code}
            payload = response.json()
            results = []
            for entry in (payload.get("results") or [])[:count]:
                if not isinstance(entry, dict):
                    continue
                url = str(entry.get("url") or "")[:380]
                parsed = urlparse(url)
                if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                    continue
                title = str(entry.get("title") or "")
                excerpt = str(entry.get("content") or "")
                if not _relevant_market_result(query, family, title, excerpt, url):
                    continue
                results.append({"title": title[:105], "url": url,
                                "excerpt": excerpt[:155],
                                "explicit_unit_price_text": _unit_price_signal(title + " " + excerpt),
                                "price_verified": False})
            usage.create({"company_id": self.company.id, "user_id": self.env.uid,
                          "session_id": self.session.id,
                          "query_hash": hashlib.sha256(query.encode("utf8")).hexdigest(),
                          "result_count": len(results)})
            self.market_sources_this_turn.extend(results[:2])
            return {"source": "tavily_web_search_snippets", "searched_at_utc":
                    fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "query": query, "results": results,
                    "warning": ("Enlaces filtrados por material y dimensión. Los precios indicados son texto de buscador, "
                                "NO verificados. Unidades, IVA y disponibilidad requieren revisión. "
                                "No inventes un precio si no hay dato explícito; usa estimate si necesitas presupuestar."),
                    "no_relevant_results": not bool(results)}
        except (requests.RequestException, ValueError):
            _logger.info("sale_ai_assistant: búsqueda Tavily no disponible, company=%s", self.company.id)
            return {"error": "No se pudo consultar Tavily. No se han verificado precios externos."}
