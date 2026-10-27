"""Optional, explicit Odoo draft line/customer shortcuts from the conversational UI.

- Producto uses quoted *literal* text fields, numeric price/quantity and exact
  SKU or unambiguous name lookup; it never calls an LLM to choose a product.
- Nota / Sección use exactly one whole quoted string for a literal line.
  Any other nonempty body is an instruction for the selected LLM.
- Cliente (or `cliente segalca`) resolves an accessible, unambiguous Odoo contact
  and stores the real partner_id; the LLM never guesses whether it was saved.
- All writes target sale.ai.draft, never sale.order, and remain reversible.
"""
import math
import re
import unicodedata

from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .sale_ai_draft_tools import SaleAIDraftTools
from . import sale_ai_gateway


_COMMAND = re.compile(r"^\s*(producto|secci[oó]n|nota|deshacer|cliente)\s*:\s*(.*)$", re.I | re.S)
# Natural short-hand previously went to the LLM, which sometimes claimed an
# assignment despite never calling set_draft_header. Only accept a clearly
# dedicated customer instruction, not an arbitrary chat message about clients.
_CUSTOMER_SHORT = re.compile(
    r"^\s*(?:cliente\s+|(?:pon|asigna|establece|selecciona)\s+(?:el\s+)?cliente\s+|"
    r"el\s+cliente\s+es\s+)(.+?)\s*$", re.I | re.S
)
_FIELD_KEY = re.compile(r"(sku|nombre|precio|cantidad|descripci[oó]n)(?=\s|[:=]|$)", re.I)
_QUOTE_END = {'"': '"', "'": "'", '“': '”', '«': '»'}
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*(?:\s*€)?")


def _fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text).casefold())
                   if not unicodedata.combining(c))


def _read_quoted(text, start):
    """Read a quoted value without altering spaces, punctuation or newlines.

    Escaped delimiters/backslashes are unescaped, but other backslashes are
    preserved so that technical content is not silently modified.
    """
    opener = text[start]
    closer = _QUOTE_END.get(opener)
    if not closer:
        raise ValueError(_("El texto debe comenzar entre comillas."))
    chars = []
    at = start + 1
    while at < len(text):
        char = text[at]
        if char == "\\" and at + 1 < len(text) and text[at + 1] in (closer, "\\"):
            chars.append(text[at + 1])
            at += 2
        elif char == closer:
            return "".join(chars), at + 1
        else:
            chars.append(char)
            at += 1
    raise ValueError(_("Hay comillas sin cerrar; comprueba el texto del comando."))


def _fully_quoted(text):
    """Return literal content only if one pair of quotes encloses ALL text.

    E.g. Nota: "un texto" is literal, while Nota: Escribe "un texto" is an
    LLM instruction that must retain the quoted wording inside its prompt.
    """
    if text and text[0] in _QUOTE_END:
        literal, end = _read_quoted(text, 0)
        if not text[end:].strip():
            return literal
    return None


def _parse_decimal(raw, key):
    raw = raw.strip().replace("€", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    elif "." in raw and len(raw.rsplit(".", 1)[-1]) == 3:
        raw = raw.replace(".", "")
    try:
        number = float(raw)
        if not math.isfinite(number):
            raise ValueError()
        return number
    except ValueError:
        raise ValueError(_("El campo %s requiere un número, por ejemplo 1290 o 1.290,50.") % key) from None


def _parse_product_spec(spec):
    """Tokenize by named fields OUTSIDE quotes, not by the words in a quote.

    ``shlex.split`` discards quote boundaries, so descriptions like
    ``"Incluye precio y cantidad"`` used to be misread as extra fields.
    """
    if not spec or len(spec) > 1800:
        raise ValueError(_("Cada producto necesita al menos «sku» o «nombre» y menos de 1.800 caracteres."))
    result = {}
    pos = 0
    while pos < len(spec):
        while pos < len(spec) and spec[pos].isspace():
            pos += 1
        if pos == len(spec):
            break
        match = _FIELD_KEY.match(spec, pos)
        if not match:
            raise ValueError(_("Usa campos sku, nombre, precio, cantidad y descripcion. "
                               "Encierra nombre y descripcion entre comillas."))
        key = _fold(match.group(1))
        if key in result:
            raise ValueError(_("El campo %s aparece dos veces; separa los productos por líneas.") % key)
        pos = match.end()
        while pos < len(spec) and spec[pos].isspace():
            pos += 1
        if pos < len(spec) and spec[pos] in ":=":
            pos += 1
            while pos < len(spec) and spec[pos].isspace():
                pos += 1
        if pos == len(spec):
            raise ValueError(_("El campo %s está vacío.") % key)
        if key in ("nombre", "descripcion"):
            if spec[pos] not in _QUOTE_END:
                raise ValueError(_("Escribe el valor de «%s» entre comillas, por ejemplo %s \"TOTAL\".") % (key, key))
            value, pos = _read_quoted(spec, pos)
        elif key == "sku":
            if spec[pos] in _QUOTE_END:
                value, pos = _read_quoted(spec, pos)
            else:
                start = pos
                while pos < len(spec) and not spec[pos].isspace():
                    pos += 1
                value = spec[start:pos]
        else:
            number = _NUMBER.match(spec, pos)
            if not number:
                raise ValueError(_("El campo %s requiere un número sin comillas.") % key)
            value = number.group(0)
            pos = number.end()
        if pos < len(spec) and not spec[pos].isspace():
            raise ValueError(_("Separa los campos con un espacio después de cada valor."))
        if not value or not value.strip():
            raise ValueError(_("El campo %s no puede estar vacío.") % key)
        result[key] = value
    if not (result.get("sku") or result.get("nombre")):
        raise ValueError(_("Falta un SKU o un nombre de producto."))
    return result


def _split_product_specs(body):
    """One product per line / semicolon, except delimiters inside quotes."""
    parts = []
    current = []
    quote_end = None
    pos = 0
    while pos < len(body):
        char = body[pos]
        if quote_end:
            if char == "\\" and pos + 1 < len(body) and body[pos + 1] in (quote_end, "\\"):
                current.extend((char, body[pos + 1]))
                pos += 2
                continue
            if char == quote_end:
                quote_end = None
        elif char in _QUOTE_END:
            quote_end = _QUOTE_END[char]
        elif char in ";\n":
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            pos += 1
            continue
        current.append(char)
        pos += 1
    if quote_end:
        raise ValueError(_("Hay comillas sin cerrar; comprueba los productos."))
    part = "".join(current).strip()
    if part:
        parts.append(part)
    cleaned = []
    for part in parts:
        part = re.sub(r"^[-*]\s+", "", part)
        part = re.sub(r"^producto\s*:\s*", "", part, flags=re.I).strip()
        if part:
            cleaned.append(part)
    if not 1 <= len(cleaned) <= 8:
        raise ValueError(_("Indica entre 1 y 8 productos, cada uno en una línea."))
    return [_parse_product_spec(piece) for piece in cleaned]


class SaleAIQuickCommands(models.Model):
    _inherit = "sale.ai.session"

    def _quick_response(self, content, model=False, usage=None):
        usage = usage or {}
        estimated_cost = (
            (usage.get("input_tokens", 0) * model.price_input_m_usd +
             usage.get("output_tokens", 0) * model.price_output_m_usd) / 1000000.0
        ) if model else 0.0
        record = self.env["sale.ai.message"].sudo().create({
            "session_id": self.id, "role": "assistant", "content": content,
            **({"model_id": model.id} if model else {}),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "latency_ms": usage.get("latency_ms", 0),
            "reported_cost_usd": usage.get("reported_cost_usd", 0),
            "estimated_cost_usd": estimated_cost,
        })
        return {"assistant_message": {
            "id": record.id, "role": "assistant", "content": content,
            "created_at": fields.Datetime.to_string(record.create_date) if record.create_date else "",
            "model": model.name if model else "Asistente de Ventas",
            "input_tokens": record.input_tokens, "output_tokens": record.output_tokens,
            "latency_ms": record.latency_ms,
            "reported_cost_usd": record.reported_cost_usd, "estimated_cost_usd": record.estimated_cost_usd,
        }}

    def _quick_find_product(self, tools, criteria):
        model = self.env["product.product"].with_company(self.company_id)
        domain = tools._product_domain()
        if criteria.get("sku"):
            # SKU must match EXACTLY; never accept a similar internal reference.
            found = model.search(domain + [("default_code", "=", criteria["sku"])], limit=6)
        else:
            text = criteria["nombre"].strip()
            if len(text) < 3:
                raise ValueError(_("Para buscar por nombre introduce al menos tres caracteres."))
            words = re.findall(r"[\w-]+", _fold(text))[:6]
            found = model.search(domain + [("name", "ilike", words[0])], limit=100)
            found = found.filtered(lambda product: all(word in _fold(product.name) for word in words))
            exact = found.filtered(lambda product: _fold(product.name).strip() == _fold(text).strip())
            if len(exact) == 1:
                found = exact
        if len(found) == 1 and criteria.get("sku") and criteria.get("nombre"):
            expected_words = re.findall(r"[\w-]+", _fold(criteria["nombre"]))
            if not all(word in _fold(found[0].name) for word in expected_words):
                raise ValueError(_("El SKU coincide, pero el nombre indicado no corresponde a ese producto. Corrige uno de los dos."))
        if len(found) != 1:
            if not found:
                raise ValueError(_("No encuentro un producto vendible que coincida con «%s». Prueba el SKU exacto.") %
                                 (criteria.get("sku") or criteria.get("nombre"))[:100])
            examples = ", ".join("[%s] %s" % (p.default_code or "sin SKU", p.name[:65]) for p in found[:5])
            raise ValueError(_("Hay varios productos posibles (%s). Indica el SKU exacto.") % examples)
        return found[0]

    def _quick_find_customer(self, query):
        """Find one accessible commercial contact without guessing among matches.

        A partial name may refer to delivery contacts of the same company.
        When ALL matches share one commercial entity, selecting that commercial
        contact is safe; matches belonging to different companies are ambiguous.
        """
        query = query.strip()
        if not 2 <= len(query) <= 120 or "\n" in query:
            raise ValueError(_("Indica un nombre de cliente o referencia de 2 a 120 caracteres."))
        domain = [
            "|", ("company_id", "=", False), ("company_id", "=", self.company_id.id),
            "|", ("name", "ilike", query), ("ref", "=ilike", query),
        ]
        candidates = self.env["res.partner"].with_company(self.company_id).search(
            domain, order="name, id", limit=31,
        )
        if not candidates:
            raise ValueError(_("No encuentro clientes para «%s». Indica otro nombre o referencia.") % query)
        folded = _fold(query).strip()
        exact = candidates.filtered(
            lambda p: _fold(p.name or "").strip() == folded or
            (p.ref and _fold(p.ref).strip() == folded)
        )
        if len(exact) == 1:
            return exact
        matches = exact if exact else candidates
        if len(matches) == 1:
            return matches
        # Never resolve incomplete results from the 31-record search cap.
        if len(candidates) < 31:
            commercial_ids = set(matches.mapped("commercial_partner_id").ids)
            if len(commercial_ids) == 1:
                partner = self.env["res.partner"].with_company(self.company_id).search([
                    ("id", "=", commercial_ids.pop()),
                    "|", ("company_id", "=", False),
                    ("company_id", "=", self.company_id.id),
                ], limit=1)
                if partner:
                    return partner
        examples = ", ".join("%s (ID %s)" % (p.display_name[:60], p.id)
                             for p in matches[:5])
        raise ValueError(_("Hay varios clientes posibles (%s). Especifica el nombre completo o una referencia única.") % examples)

    def _quick_set_customer(self, tools, body):
        """Set the actual draft partner, and only then acknowledge the result."""
        body = body.strip()
        if body and body[0] in _QUOTE_END:
            # Quotes may delimit the full exact search text, as for other shortcuts.
            literal = _fully_quoted(body)
            if literal is None:
                raise ValueError(_("Encierra el nombre completo del cliente entre comillas, sin texto adicional."))
            body = literal
        partner = self._quick_find_customer(body)
        if self.draft_id.partner_id.id != partner.id:
            with self.env.cr.savepoint():
                tools.set_draft_header(customer_id=partner.id)
        # Explicit server-side verification; no LLM assertion may substitute it.
        if self.draft_id.partner_id.id != partner.id:
            raise ValueError(_("No ha sido posible guardar el cliente en el borrador."))
        return _("Cliente «%s» asignado al borrador y comprobado en Odoo. Revisa la vista previa.") % (
            self.draft_id.partner_id.display_name,
        )

    def _quick_prepare_products(self, tools, body):
        specs = _split_product_specs(body)
        lines = []
        for spec in specs:
            product = self._quick_find_product(tools, spec)
            line = {"kind": "product", "product_id": product.id,
                    "name": spec.get("descripcion") or product.name,
                    "quantity": _parse_decimal(spec["cantidad"], "cantidad") if "cantidad" in spec else 1}
            if "precio" in spec:
                line.update({"price_unit": _parse_decimal(spec["precio"], "precio"),
                             "price_source": "user", "price_evidence": "Precio indicado explícitamente por el usuario."})
            else:
                line["price_source"] = "pricelist" if self.draft_id.partner_id else "odoo"
            lines.append(line)
        return lines

    def _quick_generate_line_text(self, text, kind, last_user):
        model = self.model_id or self.company_id.sale_ai_model_id
        if not model or not model.active or model.provider != "vercel_gateway":
            raise sale_ai_gateway.GatewayError(_("Configura un modelo activo para interpretar %s.") % kind)
        key = sale_ai_gateway.get_gateway_key(self.env, self.company_id.id)
        if not key:
            raise sale_ai_gateway.GatewayError(_("Configura la API key de Vercel para interpretar el texto."))
        if kind == "line_note":
            instruction = (
                "Eres un redactor técnico de presupuestos profesionales. Redacta SOLO el texto de una nota "
                "para una línea de presupuesto en español. Usa los datos aportados por el usuario: "
                "no inventes potencias, protecciones, mediciones ni requisitos no confirmados. "
                "Respeta literalmente cualquier fragmento ENTRE COMILLAS que aparezca en la instrucción. "
                "Marca las verificaciones pendientes. No propongas precios, no uses Markdown. "
                "Redacta el texto completo sin cortarlo por longitud."
            )
            limit = None
        else:
            instruction = (
                "Eres un asistente de ventas. Devuelve EXCLUSIVAMENTE el título breve de una sección "
                "de presupuesto en español, UNA sola línea y máximo 150 caracteres. "
                "Interpreta la intención del usuario y usa el contexto de esta conversación si ayuda. "
                "Respeta literalmente cualquier texto ENTRE COMILLAS. Sin Markdown ni explicaciones."
            )
            limit = 1000
        # Same mode as the main agent: complete current conversation in
        # experimental mode. No hidden 6-message/650-character restrictions.
        context = self._ai_context_messages()[1:]
        configured_tokens = self.company_id.sale_ai_max_output_tokens
        concrete_model = model._role_model('description')
        result = sale_ai_gateway.call_gateway(
            key, concrete_model.external_model_id,
            [{"role": "system", "content": instruction}] + context,
            timeout=self.company_id.sale_ai_request_timeout,
            max_tokens=configured_tokens,
        )
        self.env['sale.ai.model.usage'].sudo().create({
            'session_id': self.id, 'model_id': concrete_model.id,
            'stage': 'description', 'status': 'ok',
            'input_tokens': result['input_tokens'], 'output_tokens': result['output_tokens'],
            'latency_ms': result['latency_ms'],
            'reported_cost_usd': result['reported_cost_usd'],
            'estimated_cost_usd': (
                result['input_tokens'] * concrete_model.price_input_m_usd +
                result['output_tokens'] * concrete_model.price_output_m_usd) / 1000000.0,
        })
        generated = (result.get("content") or "").strip()
        # Providers normally report finish_reason='length' when their response
        # reaches the output limit. Some compatible models omit that field;
        # use token usage close to the cap as a conservative fallback.
        finish_reason = (result.get("finish_reason") or "").lower()
        output_tokens = result.get("output_tokens") or 0
        if finish_reason in ("length", "max_tokens", "max_output_tokens") or (
                not finish_reason and output_tokens >= configured_tokens):
            raise ValueError(_(
                "La IA ha alcanzado el límite de tokens y el texto puede estar "
                "incompleto. No se ha añadido la línea. Prueba con una nota más "
                "breve o un modelo con mayor capacidad de salida."
            ))
        if kind == "line_section":
            generated = generated.strip(" \"'“”«»\n")
        if not generated or (limit is not None and len(generated) > limit) or (kind == "line_section" and "\n" in generated):
            raise ValueError(_("La IA no ha devuelto un texto válido; vuelve a indicar el contenido de la línea."))
        return generated, concrete_model, result

    def _ai_handle_quick_command(self, last_user):
        message = last_user.content or ""
        match = _COMMAND.match(message)
        if match:
            action = _fold(match.group(1))
            body = match.group(2).strip()
        else:
            customer = _CUSTOMER_SHORT.match(message)
            if not customer or len(message) > 150 or "\n" in message:
                return None
            action = "cliente"
            body = customer.group(1).strip()
        tools = SaleAIDraftTools(self)
        model = False
        usage = None
        try:
            if action == "deshacer":
                if body and _fold(body) not in ("ultimo cambio", "ultimo", "cambio"):
                    raise ValueError(_("El comando Deshacer solo revierte el último cambio del borrador."))
                with self.env.cr.savepoint():
                    tools.undo_last_draft_change()
                content = _("He deshecho el último cambio del borrador. La vista previa ya refleja el estado anterior.")
            elif action == "cliente":
                content = self._quick_set_customer(tools, body)
            elif action == "producto":
                lines = self._quick_prepare_products(tools, body)
                with self.env.cr.savepoint():
                    result = tools.add_draft_lines(lines)
                labels = ", ".join("[%s]" % self.env["product.product"].browse(line["product_id"]).default_code
                                   for line in lines)
                content = _("Se han añadido %s producto(s) reales al borrador: %s. Base provisional: %.2f %s. Revisa la vista previa.") % (
                    len(result["created"]), labels, result["amount_untaxed_estimate"], self.draft_id.currency_id.name)
            elif action in ("seccion", "nota"):
                if not body:
                    raise ValueError(_("Escribe el contenido de la línea, entre comillas para texto literal o sin comillas para pedir redacción a la IA."))
                literal = _fully_quoted(body)
                if literal is not None:
                    line_text = literal
                else:
                    kind = "line_section" if action == "seccion" else "line_note"
                    line_text, model, usage = self._quick_generate_line_text(body, kind, last_user)
                if not line_text.strip():
                    raise ValueError(_("La línea no puede estar vacía."))
                kind = "line_section" if action == "seccion" else "line_note"
                if len(line_text) > (150 if kind == "line_section" else 3500):
                    raise ValueError(_("Texto demasiado largo para este tipo de línea."))
                with self.env.cr.savepoint():
                    tools.add_draft_lines([{"kind": kind, "name": line_text}])
                content = (_("Sección añadida al borrador: %s") % line_text[:130]
                           if action == "seccion" else
                           _("Nota añadida al borrador. Puedes revisarla en la vista previa."))
            else:
                return None
        except (ValueError, UserError, ValidationError) as exc:
            content = _("No he modificado el borrador: %s") % str(exc)[:350]
            model = False
            usage = None
        except sale_ai_gateway.GatewayError as exc:
            return {"error": str(exc)}
        return self._quick_response(content, model=model, usage=usage)

    def _ai_generate_for(self):
        self.ensure_one()
        self._ensure_can_edit_draft()
        last = self.env["sale.ai.message"].search([
            ("session_id", "=", self.id), ("role", "=", "user")], order="id desc", limit=1)
        if last:
            result = self._ai_handle_quick_command(last)
            if result is not None:
                return result
        return super()._ai_generate_for()
