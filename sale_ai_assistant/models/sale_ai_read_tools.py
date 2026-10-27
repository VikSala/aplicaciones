"""Read-only, bounded Odoo tool catalogue for the AI conversation (Phase 3).

No sudo on commercial data. The model never sends Odoo domains or field names:
all model names, search domains and returned fields are server-defined.
"""
import json
import re
import unicodedata

from odoo import _
from odoo.exceptions import AccessError, UserError


MAX_TOOL_ARGUMENT_CHARS = 120000


def _text(value, limit=160):
    """Bound untrusted database text before sending it to the provider."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _search_text(value):
    if not isinstance(value, str):
        raise ValueError("La búsqueda debe ser texto.")
    value = _text(value, 90)
    if len(value) < 2:
        raise ValueError("Especifica al menos dos caracteres para buscar.")
    return value


def _int_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Indica un ID válido de Odoo.")
    return value


def _keywords(value):
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    ignore = {"para", "sobre", "unos", "unas", "desde", "instalacion", "presupuesto",
              "pedido", "cliente", "lineas", "trabajo", "quiero", "hacer", "necesito"}
    return [word for word in re.findall(r"[\w-]{3,}", normalized)
            if word not in ignore][:5]


class SaleAIReadTools:
    """One instance per current session. Access to data always uses session.env."""

    def __init__(self, session):
        session.ensure_one()
        session._ensure_can_edit_draft()
        if not session.env.user.has_group("sales_team.group_sale_manager"):
            raise AccessError(_("Solo administradores de Ventas pueden utilizar herramientas IA."))
        if session.company_id != session.env.company:
            raise AccessError(_("Esta conversación pertenece a otra compañía."))
        self.session = session
        self.env = session.env
        self.company = session.company_id
        self.history_limit = max(0, self.company.sale_ai_history_limit)
        # IDs actually returned by Odoo to this turn, never model-invented IDs.
        self.verified_product_ids = set()
        self.ambiguous_product_ids = set()

    def definitions(self):
        def string_search(name, description):
            return {"type": "function", "function": {
                "name": name, "description": description,
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "Palabras de búsqueda concretas (2 a 90 caracteres)."}},
                    "required": ["query"], "additionalProperties": False}}}

        def id_lookup(name, description, field):
            return {"type": "function", "function": {
                "name": name, "description": description,
                "parameters": {"type": "object", "properties": {
                    field: {"type": "integer", "description": "ID que haya devuelto previamente otra herramienta."}},
                    "required": [field], "additionalProperties": False}}}

        tools = [
            string_search("search_customers", "Busca clientes por nombre o referencia interna. Devuelve IDs y nombres, no información privada."),
            string_search("search_products", "Busca productos vendibles por nombre o referencia. El precio devuelto es precio de lista Odoo, no una cotización actual de mercado."),
            id_lookup("get_product_details", "Consulta unidad de medida, descripción comercial y precio de lista de un producto por ID.", "product_id"),
        ]
        if self.history_limit:
            tools += [
                string_search("search_quotations", "Encuentra presupuestos y pedidos anteriores similares por referencia, cliente o texto técnico; devuelve unos pocos candidatos y sus IDs. No implica que sus precios sigan vigentes."),
                id_lookup("get_quotation_lines", "Lee las líneas (producto, sección o nota) de un presupuesto histórico cuyo ID ya se conoce.", "order_id"),
                id_lookup("get_customer_history", "Consulta una selección breve de presupuestos/pedidos anteriores del cliente identificado por su ID.", "customer_id"),
            ]
        return tools

    def execute(self, name, raw_arguments):
        permitted = {item["function"]["name"] for item in self.definitions()}
        if name not in permitted:
            return {"error": "Herramienta desconocida o deshabilitada."}
        if not isinstance(raw_arguments, str) or len(raw_arguments) > MAX_TOOL_ARGUMENT_CHARS:
            return {"error": "Argumentos demasiado grandes o inválidos."}
        try:
            args = json.loads(raw_arguments)
            if not isinstance(args, dict) or len(args) != 1:
                raise ValueError("La herramienta necesita un único argumento.")
            method, key = {
                "search_customers": (self.search_customers, "query"),
                "search_products": (self.search_products, "query"),
                "get_product_details": (self.get_product_details, "product_id"),
                "search_quotations": (self.search_quotations, "query"),
                "get_quotation_lines": (self.get_quotation_lines, "order_id"),
                "get_customer_history": (self.get_customer_history, "customer_id"),
            }[name]
            if set(args) != {key}:
                raise ValueError("Argumento no permitido.")
            result = method(args[key])
            return self._bounded_result(result)
        except (ValueError, TypeError) as exc:
            return {"error": _text(exc, 140)}
        # ORM AccessError/UserError deliberately propagate to the caller's
        # safe error handler; no privilege escalation or SQL fallback.

    def _bounded_result(self, data):
        serialized = json.dumps(data, ensure_ascii=False, default=str)
        limit = self.company._sale_ai_get_agent_parameter(self.company.id, "tool_result_chars")
        if len(serialized) > limit:
            return {"data_excerpt": serialized[:max(0, limit - 150)],
                    "truncated": True, "note": "Resultado recortado según configuración visible."}
        return data

    def _partner(self, partner_id):
        return self.env["res.partner"].search([
            ("id", "=", _int_id(partner_id)),
            "|", ("company_id", "=", False), ("company_id", "=", self.company.id),
        ], limit=1)

    def search_customers(self, query):
        query = _search_text(query)
        partners = self.env["res.partner"].search([
            "&", "|", ("company_id", "=", False), ("company_id", "=", self.company.id),
            "|", ("name", "ilike", query), ("ref", "ilike", query),
        ], order="name, id", limit=6)
        return {"source": "odoo.res.partner", "results": [
            {"id": p.id, "name": _text(p.display_name, 100), "ref": _text(p.ref, 40)}
            for p in partners], "more_may_exist": len(partners) == 6}

    def _product_domain(self):
        return [("sale_ok", "=", True),
                "|", ("company_id", "=", False), ("company_id", "=", self.company.id)]

    def search_products(self, query):
        query = _search_text(query)
        products = self.env["product.product"].with_company(self.company).search(
            self._product_domain() + ["|", ("name", "ilike", query), ("default_code", "ilike", query)],
            limit=6, order="default_code, id")
        # A broad query can return multiple legitimate articles. Do not hand
        # the agent permission to choose one arbitrarily based on this list.
        # A single result or a uniquely matching exact SKU/name is resolved;
        # otherwise the agent must disambiguate with the user or consult details.
        exact_ref = products.filtered(lambda rec: (rec.default_code or "").casefold() == query.casefold())
        exact_name = products.filtered(lambda rec: (rec.name or "").casefold() == query.casefold())
        selected = (products if len(products) == 1 else
                    exact_ref if len(exact_ref) == 1 else
                    exact_name if len(exact_name) == 1 else self.env["product.product"])
        self.verified_product_ids.update(selected.ids)
        self.ambiguous_product_ids.update(set(products.ids) - set(selected.ids))
        self.ambiguous_product_ids.difference_update(self.verified_product_ids)
        return {"requires_clarification": not bool(selected),
                "source": "odoo.product.product", "currency": self.company.currency_id.name,
                "price_type": "Precio de lista orientativo, sin tarifa de cliente ni impuestos calculados",
                "results": [{"id": p.id, "ref": _text(p.default_code, 60),
                             "name": _text(p.name, 100), "list_price": round(p.lst_price, 2),
                             "uom": _text(p.uom_id.name, 25)} for p in products],
                "more_may_exist": len(products) == 6}

    def get_product_details(self, product_id):
        product = self.env["product.product"].with_company(self.company).search(
            [("id", "=", _int_id(product_id))] + self._product_domain(), limit=1)
        if not product:
            return {"not_found_or_denied": True}
        # Reviewing one of several ambiguous candidates does not constitute a
        # user selection. An exact SKU search is needed to authorize that ID.
        if product.id not in self.ambiguous_product_ids:
            self.verified_product_ids.add(product.id)
        return {"source": "odoo.product.product", "id": product.id,
                "ref": _text(product.default_code, 60), "name": _text(product.name, 150),
                "description_sale": _text(product.description_sale, 350),
                "list_price": round(product.lst_price, 2), "currency": self.company.currency_id.name,
                "price_type": "Precio de lista Odoo, NO precio neto de tarifa ni precio actual de mercado",
                "uom": _text(product.uom_id.name, 35), "weight_kg": product.weight}

    def _order_domain(self):
        return [("company_id", "=", self.company.id),
                ("state", "in", ["draft", "sent", "sale", "done"])]

    def _summary(self, order):
        return {"id": order.id, "reference": _text(order.name, 50),
                "customer": _text(order.partner_id.display_name, 80),
                "date": str(order.date_order.date()) if order.date_order else "",
                "state": order.state,
                "total_untaxed": round(order.amount_untaxed, 2), "currency": order.currency_id.name,
                "line_count": len(order.order_line)}

    def search_quotations(self, query):
        query = _search_text(query)
        if not self.history_limit:
            return {"disabled": True}
        # ORM query is capped; only the short candidate set is scored in Python.
        words = _keywords(query)
        # Search meaningful individual terms instead of requiring the full
        # natural-language prompt to occur verbatim in an old line.
        terms = list(dict.fromkeys((words[:3] or [query])))
        criteria = [(field, "ilike", term)
                    for term in terms
                    for field in ("name", "partner_id.name", "order_line.name")]
        match_domain = (["|"] * (len(criteria) - 1)) + criteria
        candidates = self.env["sale.order"].search(
            self._order_domain() + match_domain,
            order="date_order desc, id desc", limit=18)
        def score(order):
            text = " ".join([_text(order.name, 100), _text(order.partner_id.name, 100)] +
                            [_text(l.name, 220) for l in order.order_line[:8]])
            text = unicodedata.normalize("NFKD", text.lower())
            return sum(1 for w in words if w in text)
        ordered = sorted(candidates, key=lambda rec: (score(rec), rec.date_order or rec.create_date, rec.id), reverse=True)
        return {"source": "odoo.sale.order", "price_warning": "Histórico no implica precio actual",
                "results": [self._summary(o) for o in ordered[:self.history_limit]],
                "searched_candidates": len(candidates),
                "result_limit": self.history_limit}

    def get_quotation_lines(self, order_id):
        order = self.env["sale.order"].search(
            self._order_domain() + [("id", "=", _int_id(order_id))], limit=1)
        if not order:
            return {"not_found_or_denied": True}
        lines = order.order_line.sorted(key=lambda line: (line.sequence, line.id))[:12]
        return {"source": "odoo.sale.order", "order": self._summary(order),
                "lines": [{"kind": line.display_type or "product",
                           "product_id": line.product_id.id or False,
                           "ref": _text(line.product_id.default_code, 35) if line.product_id else "",
                           "description": _text(line.name, 230),
                           "quantity": line.product_uom_qty if not line.display_type else 0,
                           "price_unit": round(line.price_unit, 2) if not line.display_type else 0,
                           "subtotal": round(line.price_subtotal, 2) if not line.display_type else 0}
                          for line in lines],
                "lines_omitted": max(0, len(order.order_line) - len(lines)),
                "historical_not_current_price": True}

    def get_customer_history(self, customer_id):
        if not self.history_limit:
            return {"disabled": True}
        partner = self._partner(customer_id)
        if not partner:
            return {"not_found_or_denied": True}
        orders = self.env["sale.order"].search(
            self._order_domain() + [("partner_id", "child_of", partner.commercial_partner_id.id)],
            order="date_order desc, id desc", limit=self.history_limit)
        return {"source": "odoo.sale.order", "customer_id": partner.id,
                "price_warning": "Los precios históricos pueden haber cambiado",
                "orders": [self._summary(order) for order in orders]}
