"""Phase 4: tightly scoped, reversible *provisional draft* operations.

No sale.order, product or customer is written here. Every operation uses the
caller's ORM permissions and the session's company, without sudo().
"""
import hashlib
import json
import math

from odoo import _, fields
from odoo.exceptions import AccessError, UserError, ValidationError

from .sale_ai_read_tools import SaleAIReadTools

MAX_DRAFT_LINES = 40
MAX_BATCH_LINES = 8
MAX_TOOL_ARGUMENT_CHARS = 600000
MAX_LINE_NAME = 500000
MAX_APPEND_TEXT = 500000
MAX_SNAPSHOT_BYTES = 4194304


def _valid_int(value, field):
    if type(value) is not int or value <= 0:
        raise ValueError("%s debe ser un ID entero positivo." % field)
    return value


def _short_text(value, name, limit, required=False):
    if not isinstance(value, str):
        raise ValueError("%s debe ser texto." % name)
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise ValueError("%s vacío o demasiado largo (máx. %s caracteres)." % (name, limit))
    return value


def _number(value, key, max_value, allow_zero=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("%s debe ser un número finito." % key)
    if value < 0 or value > max_value or (not allow_zero and value == 0):
        raise ValueError("%s está fuera de límites." % key)
    return float(value)


class SaleAIDraftTools(SaleAIReadTools):
    """Read tools from phase 3 + CRUD limited to this session's proposed draft."""

    def definitions(self):
        existing = super().definitions()
        obj = lambda properties, required=(): {
            "type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False,
        }
        s = lambda description: {"type": "string", "description": description}
        ident = lambda description: {"type": "integer", "description": description}
        line_fields = {
            "kind": {"type": "string", "enum": ["product", "line_note", "line_section"]},
            "name": s("Texto técnico completo o descripción del producto. Para notas usa line_note; para secciones line_section."),
            "product_id": ident("ID real verificado mediante search_products/get_product_details en ESTE turno. Obligatorio para un producto del catálogo."),
            "allow_unlinked": {"type": "boolean", "description": "Solo true cuando el usuario PIDA EXPRESAMENTE una partida libre sin artículo del catálogo. Nunca para buscar un producto real."},
            "quantity": {"type": "number", "description": "Cantidad para línea product; omitir en notas/secciones."},
            "price_unit": {"type": "number", "description": "Precio orientativo sin impuestos por unidad; omitir en notas/secciones."},
            "discount": {"type": "number", "description": "Porcentaje 0 a 100."},
            "price_source": {"type": "string", "enum": ["estimate", "odoo", "pricelist", "history", "user"],
                             "description": "estimate para hipótesis; odoo lee catálogo; pricelist calcula en servidor tarifa del cliente asignado (requiere producto y cliente); history requiere source_order_id."},
            "source_order_id": ident("Presupuesto histórico consultado que justifica el precio_source history."),
            "price_evidence": s("Origen o advertencia breve. Nunca afirmar búsqueda web inexistente."),
            "sequence": {"type": "integer", "description": "Orden de visualización opcional; 10, 20, 30..."},
        }
        existing.extend([
            {"type": "function", "function": {"name": "get_current_draft", "description":
                "Consulta SOLO el borrador provisional de esta conversación y sus IDs; nunca sale.order.",
                "parameters": obj({})}},
            {"type": "function", "function": {"name": "set_draft_header", "description":
                "Actualiza cliente/comentarios/hipótesis/cálculo interno de la propuesta. Solo campos aportados; customer_id ha de proceder de una búsqueda real. No crea un pedido.",
                "parameters": obj({
                    "customer_id": ident("ID cliente Odoo ya localizado; 0 no válido."),
                    "description": s("Comentarios del presupuesto, destinados a sale.order.x_comentarios; hasta 5000 caracteres. No son la referencia del cliente."),
                    "assumptions": s("Datos pendientes y verificaciones; puede ser texto vacío para limpiar."),
                    "estimate_details": s("Desglose privado orientativo de materiales y horas; puede ser vacío."),
                })}},
            {"type": "function", "function": {"name": "add_draft_lines", "description":
                "Añade 1-8 líneas provisionales al final, en el orden recibido. Si el usuario pide otra posición, usa después update_draft_line con sequence. Para cada producto del catálogo, primero llama search_products y usa el product_id REAL obtenido. No crees partidas sin referencia como sustituto de una búsqueda. Solo usa allow_unlinked=true cuando el usuario solicite expresamente una partida libre. Si hay varios resultados ambiguos, pregunta. Solo borrador IA.",
                "parameters": obj({"lines": {"type": "array", "items": obj({k: v for k, v in line_fields.items() if k != "sequence"}, ["kind", "name"]),
                                                   "minItems": 1, "maxItems": MAX_BATCH_LINES}}, ["lines"])}},
            {"type": "function", "function": {"name": "update_draft_line", "description":
                "Modifica una línea provisional existente usando su line_id real; no vuelve a añadir la línea.",
                "parameters": obj(dict({"line_id": ident("ID de línea obtenido de get_current_draft o del resumen de sesión.")},
                                       **line_fields), ["line_id"])}},
            {"type": "function", "function": {"name": "append_draft_line_text", "description":
                "Añade un párrafo a una NOTA técnica ya existente, manteniendo íntegro su texto. Preferible a sustituir descripciones largas al ampliar protecciones, materiales o alcance.",
                "parameters": obj({"line_id": ident("ID real de la nota existente."),
                                   "text": s("Párrafo técnico adicional (máx. 1200 caracteres). No repitas lo que ya está en la nota.")},
                                  ["line_id", "text"]) }},
            {"type": "function", "function": {"name": "remove_draft_line", "description":
                "Elimina una línea del borrador provisional de esta sesión, nunca de pedidos reales.",
                "parameters": obj({"line_id": ident("ID real de la línea provisional.")}, ["line_id"])}},
            {"type": "function", "function": {"name": "undo_last_draft_change", "description":
                "Deshace el cambio provisional más reciente. Puede repetirse varias veces (historial persistente por sesión). No afecta a sale.order.",
                "parameters": obj({})}},
        ])
        return existing

    def execute(self, name, raw_arguments):
        handlers = {
            "get_current_draft": self.get_current_draft,
            "set_draft_header": self.set_draft_header,
            "add_draft_lines": self.add_draft_lines,
            "update_draft_line": self.update_draft_line,
            "append_draft_line_text": self.append_draft_line_text,
            "remove_draft_line": self.remove_draft_line,
            "undo_last_draft_change": self.undo_last_draft_change,
        }
        if name not in handlers:
            return super().execute(name, raw_arguments)
        if not isinstance(raw_arguments, str) or len(raw_arguments) > MAX_TOOL_ARGUMENT_CHARS:
            return {"error": "Argumentos inválidos o demasiado largos."}
        try:
            args = json.loads(raw_arguments)
            if not isinstance(args, dict):
                raise ValueError("Los argumentos deben ser un objeto JSON.")
            if name == "get_current_draft" or name == "undo_last_draft_change":
                if args:
                    raise ValueError("Esta operación no admite argumentos.")
            elif name == "set_draft_header":
                self._validate_keys(args, {"customer_id", "description", "assumptions", "estimate_details"})
                if not args:
                    raise ValueError("No se han indicado cambios.")
            elif name == "add_draft_lines":
                self._validate_keys(args, {"lines"})
                if "lines" not in args:
                    raise ValueError("Faltan las líneas.")
                # Enforce evidence of a real product read *in this agent turn*.
                # Explicit deterministic UI SKU commands bypass execute and
                # validate through their independent exact SKU lookup.
                if isinstance(args["lines"], list):
                    for item in args["lines"]:
                        if not isinstance(item, dict):
                            continue
                        if item.get("kind") == "product" and item.get("product_id"):
                            if item["product_id"] not in self.verified_product_ids:
                                raise ValueError(
                                    "Busca primero el producto real con search_products o "
                                    "get_product_details; no inventes el product_id.")
            elif name == "append_draft_line_text":
                self._validate_keys(args, {"line_id", "text"})
                if set(args) != {"line_id", "text"}:
                    raise ValueError("La ampliación requiere line_id y text.")
            elif name == "update_draft_line":
                if args.get("product_id") and args["product_id"] not in self.verified_product_ids:
                    raise ValueError("Busca y verifica el producto real antes de cambiar la referencia.")
                self._validate_keys(args, {"line_id", "kind", "name", "product_id", "allow_unlinked", "quantity", "price_unit",
                                           "discount", "price_source", "price_evidence", "source_order_id", "sequence"})
                if len(args) < 2 or "line_id" not in args:
                    raise ValueError("Indica el ID y al menos un cambio.")
            else:
                self._validate_keys(args, {"line_id"})
                if "line_id" not in args:
                    raise ValueError("Falta el ID de línea.")
            with self.env.cr.savepoint():
                result = handlers[name](**args)
            return self._bounded_result(result)
        except AccessError:
            raise
        except (ValueError, TypeError, UserError, ValidationError) as exc:
            return {"error": str(exc)[:230]}
        # AccessError propagates and aborts response: never turn data-access failures
        # into business data or silently bypass access rules.

    @staticmethod
    def _validate_keys(data, allowed):
        if set(data) - allowed:
            raise ValueError("Parámetros no reconocidos.")

    @property
    def draft(self):
        self.session.ensure_one()
        self.session._ensure_can_edit_draft()
        draft = self.session.draft_id
        if not draft or draft.company_id != self.company:
            raise AccessError(_("No se puede acceder al borrador de esta compañía."))
        return draft

    def _snapshot(self, draft):
        data = {
            "description": draft.description or "",
            "partner_id": draft.partner_id.id or False,
            "pricelist_id": draft.pricelist_id.id or False,
            "currency_id": draft.currency_id.id,
            "assumptions": draft.assumptions or "",
            "estimate_details": draft.estimate_details or "",
            "lines": [{"id": line.id, "source_line_id": line.source_sale_line_id or False, "kind": line.line_kind, "name": line.name,
                       "product_id": line.product_id.id or False,
                       "uom_id": line.product_uom_id.id or False,
                       "quantity": line.product_uom_qty, "price_unit": line.price_unit,
                       "discount": line.discount, "price_source": line.price_source,
                       "price_evidence": line.price_evidence or "", "sequence": line.sequence}
                      for line in draft.line_ids.sorted(key=lambda l: (l.sequence, l.id))],
        }
        return data

    @staticmethod
    def _digest(data):
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _record_undo(self, draft, before):
        # Persist a new journal entry for EACH operation rather than overwriting
        # the sole undo_snapshot field of the older versions.
        data = json.dumps(before, ensure_ascii=False)
        if len(data.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Borrador demasiado grande para guardar un cambio reversible.")
        after = self._snapshot(draft)
        if self._digest(before) == self._digest(after):
            return  # No write took place; don't add a meaningless undo step.
        self.env["sale.ai.draft.change"].create({
            "draft_id": draft.id, "before_snapshot": data,
            "after_fingerprint": self._digest(after),
        })
        # Legacy one-level fields remain for already persisted old sessions;
        # clearing them on a new write prevents incorrectly undoing an old state.
        if draft.undo_snapshot or draft.undo_after_fingerprint:
            draft.write({"undo_snapshot": False, "undo_after_fingerprint": False})

    def _get_line(self, line_id):
        line_id = _valid_int(line_id, "line_id")
        line = self.env["sale.ai.draft.line"].search([
            ("id", "=", line_id), ("draft_id", "=", self.draft.id),
        ], limit=1)
        if not line:
            raise ValueError("No existe esa línea en el borrador de esta conversación.")
        return line

    def _real_product(self, product_id):
        product = self.env["product.product"].with_company(self.company).search([
            ("id", "=", _valid_int(product_id, "product_id"))] + self._product_domain(), limit=1)
        if not product:
            raise ValueError("Producto no encontrado, no vendible o fuera de la compañía.")
        return product

    def _line_values(self, raw, previous=None):
        self._validate_keys(raw, {"kind", "name", "product_id", "allow_unlinked", "quantity", "price_unit", "discount",
                                  "price_source", "source_order_id", "price_evidence", "sequence"})
        kind = raw.get("kind", previous.line_kind if previous else "product")
        if kind not in ("product", "line_note", "line_section"):
            raise ValueError("Tipo de línea inválido.")
        name = _short_text(raw.get("name", previous.name if previous else ""), "name", MAX_LINE_NAME, required=True)
        values = {"line_kind": kind, "name": name}
        if "sequence" in raw:
            number = _valid_int(raw["sequence"], "sequence")
            if number > 100000:
                raise ValueError("Orden demasiado grande.")
            values["sequence"] = number
        elif previous is None:
            last = max(self.draft.line_ids.mapped("sequence") or [0])
            values["sequence"] = last + 10
        if kind != "product":
            if any(k in raw for k in ("product_id", "quantity", "price_unit", "discount", "source_order_id")):
                raise ValueError("Notas y secciones no pueden contener producto, cantidades ni importes.")
            if "price_source" in raw:
                raise ValueError("Notas y secciones no tienen origen de precio.")
            values.update({"product_id": False, "product_uom_id": False, "product_uom_qty": 0,
                           "price_unit": 0, "discount": 0, "price_source": "estimate", "price_evidence": ""})
            return values

        existing_product = previous.product_id if previous and previous.line_kind == "product" else False
        product = self._real_product(raw["product_id"]) if "product_id" in raw else existing_product
        if not product and not (previous and previous.line_kind == "product") and not raw.get("allow_unlinked"):
            raise ValueError(
                "Para añadir un producto del catálogo, búscalo primero en Odoo y "
                "pasa su product_id. Una partida sin producto solo puede crearse "
                "si el usuario lo pidió expresamente (allow_unlinked=true).")
        if raw.get("allow_unlinked") and product:
            raise ValueError("Una línea con product_id real no necesita allow_unlinked.")
        if product:
            values["product_id"] = product.id
            values["product_uom_id"] = product.uom_id.id
        source = raw.get("price_source", previous.price_source if previous and previous.line_kind == "product" else "estimate")
        if source not in ("estimate", "odoo", "pricelist", "history", "user"):
            raise ValueError("Origen de precio no permitido sin verificación externa.")
        amount = raw.get("price_unit", previous.price_unit if previous and previous.line_kind == "product" else 0)
        evidence = raw.get("price_evidence", previous.price_evidence if previous and previous.line_kind == "product" else "")
        if source == "pricelist" and "price_unit" in raw:
            if "price_source" in raw or not previous or previous.price_source != "pricelist":
                raise ValueError("Para precio de tarifa no especifiques importe: lo calcula Odoo.")
            # A manual price edit is not a price computed by a real pricelist.
            source = "estimate"
            evidence = "Precio cambiado manualmente frente a la tarifa Odoo: revisar."
        if source == "pricelist":
            if not product or not self.draft.partner_id:
                raise ValueError("Precio de tarifa requiere producto y cliente asignados al borrador.")
            customer = self.draft.partner_id.with_company(self.company)
            pricelist = self.draft.pricelist_id or customer.property_product_pricelist
            pricelist = self.env["product.pricelist"].search([
                ("id", "=", pricelist.id), ("active", "=", True),
                ("company_id", "in", [False, self.company.id]),
            ], limit=1) if pricelist else False
            if not pricelist:
                raise ValueError("Tarifa de cliente no encontrada o no permitida en esta compañía.")
            qty = _number(raw.get("quantity", previous.product_uom_qty if previous else 1),
                          "quantity", 10000000, allow_zero=False)
            amount = pricelist.with_company(self.company)._get_product_price(
                product.with_company(self.company), qty, uom=product.uom_id)
            evidence = "Tarifa Odoo %s para cliente %s, cantidad %s; sin cálculo fiscal." % (
                pricelist.display_name[:90], customer.display_name[:60], qty)
            if pricelist.currency_id != self.draft.currency_id:
                amount = pricelist.currency_id._convert(amount, self.draft.currency_id,
                    self.company, fields.Date.context_today(self.env.user))
                evidence += " Convertido de %s a %s según Odoo." % (
                    pricelist.currency_id.name, self.draft.currency_id.name)
        if source == "odoo":
            if not product:
                raise ValueError("Precio Odoo requiere un producto real.")
            if "price_unit" in raw:
                raise ValueError("Para precio Odoo no especifiques importe: se lee del catálogo en el servidor.")
            amount = product.lst_price
            evidence = "Precio de lista Odoo (orientativo; no tarifa del cliente ni mercado)."
        if ("price_unit" in raw and "price_source" not in raw and previous and
                previous.price_source in ("odoo", "history", "pricelist") and
                raw["price_unit"] != previous.price_unit):
            # Once manually adjusted, a catalogue/historical price no longer
            # truthfully represents the literal figure in the proposal.
            source = "estimate"
            evidence = "Importe modificado frente a la referencia previa: revisar."
        if source == "history":
            source_order_id = raw.get("source_order_id")
            if source_order_id is None and previous and previous.price_source == "history":
                # Quantity/description edits should not destroy an already recorded source.
                if "price_source" not in raw:
                    values["price_source"] = "history"
                    evidence = raw.get("price_evidence", previous.price_evidence or "")
                    source = "history"
                    source_order_id = None
                else:
                    raise ValueError("Indica source_order_id al cambiar el origen a histórico.")
            elif source_order_id is None:
                raise ValueError("Para origen histórico, especifica un presupuesto real en source_order_id.")
            if source_order_id is not None:
                prior = self.env["sale.order"].search(self._order_domain() + [
                    ("id", "=", _valid_int(source_order_id, "source_order_id"))], limit=1)
                if not prior:
                    raise ValueError("Presupuesto histórico no accesible en esta compañía.")
                evidence = "Histórico %s (%s). No implica precio vigente. %s" % (
                    prior.name, str(prior.date_order.date()) if prior.date_order else "fecha no disponible", evidence)
        values["price_source"] = source
        values["price_unit"] = _number(amount, "price_unit", 100000000)
        values["product_uom_qty"] = _number(raw.get("quantity", previous.product_uom_qty if previous and previous.line_kind == "product" else 1),
                                              "quantity", 10000000, allow_zero=False)
        values["discount"] = _number(raw.get("discount", previous.discount if previous and previous.line_kind == "product" else 0), "discount", 100)
        values["price_evidence"] = _short_text(evidence, "price_evidence", 800)
        return values

    def get_current_draft(self):
        draft = self.draft
        snapshot = self._snapshot(draft)
        return {"proposal_id": draft.id, "customer": draft.partner_id.display_name if draft.partner_id else "",
                "currency": draft.currency_id.name, "amount_untaxed_estimate": draft.amount_untaxed_estimate,
                "draft": snapshot, "review_required": True, "not_a_sale_order": True}

    def set_draft_header(self, **kwargs):
        draft = self.draft
        before = self._snapshot(draft)
        values = {}
        if "customer_id" in kwargs:
            customer_id = _valid_int(kwargs["customer_id"], "customer_id")
            customer = self.env["res.partner"].search([
                ("id", "=", customer_id), "|", ("company_id", "=", False),
                ("company_id", "=", self.company.id)], limit=1)
            if not customer:
                raise ValueError("Cliente inexistente o no accesible en esta compañía.")
            values["partner_id"] = customer.id
        for key, limit in (("description", 5000), ("assumptions", 2200), ("estimate_details", 3000)):
            if key in kwargs:
                values[key] = _short_text(kwargs[key], key, limit)
        if values:
            draft.write(values)
            self._record_undo(draft, before)
        return {"updated": list(values), "proposal_id": draft.id,
                "customer": draft.partner_id.display_name if draft.partner_id else "",
                "amount_untaxed_estimate": draft.amount_untaxed_estimate}

    def add_draft_lines(self, lines):
        draft = self.draft
        if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_BATCH_LINES:
            raise ValueError("Añade entre 1 y 8 líneas por petición.")
        if len(draft.line_ids) + len(lines) > MAX_DRAFT_LINES:
            raise ValueError("El borrador admite como máximo 40 líneas.")
        before = self._snapshot(draft)
        created = []
        for item in lines:
            if not isinstance(item, dict) or "kind" not in item or "name" not in item:
                raise ValueError("Cada línea debe indicar kind y name.")
            # Creation always appends. Explicit reordering is a separate update,
            # so a model-supplied default sequence cannot move a new product above notes.
            values = self._line_values({k: v for k, v in item.items() if k != 'sequence'})
            # Assigned sequence takes previous created lines into account.
            created.append(self.env["sale.ai.draft.line"].create(dict(values, draft_id=draft.id)))
        self._record_undo(draft, before)
        return {"created": [{"id": item.id, "kind": item.line_kind, "name": item.name[:95],
                              "product_id": item.product_id.id or False,
                              "sku": item.product_id.default_code if item.product_id else ""}
                            for item in created], "amount_untaxed_estimate": draft.amount_untaxed_estimate}

    def update_draft_line(self, line_id, **kwargs):
        line = self._get_line(line_id)
        draft = self.draft
        before = self._snapshot(draft)
        values = self._line_values(kwargs, previous=line)
        line.write(values)
        self._record_undo(draft, before)
        return {"updated_id": line.id, "kind": line.line_kind, "amount_untaxed_estimate": draft.amount_untaxed_estimate}

    def append_draft_line_text(self, line_id, text):
        line = self._get_line(line_id)
        if line.line_kind != "line_note":
            raise ValueError("Solo se pueden ampliar notas técnicas mediante esta herramienta.")
        extra = _short_text(text, "text", MAX_APPEND_TEXT, required=True)
        previous_text = (line.name or "").rstrip()
        # Repeated provider calls must not paste the same paragraph twice.
        if extra.casefold() in previous_text.casefold():
            return {"unchanged_id": line.id, "reason": "El texto ya existe en la nota."}
        if len(previous_text) + len(extra) + 2 > MAX_LINE_NAME:
            raise ValueError("La nota supera el límite; resume la descripción antes de ampliarla.")
        draft = self.draft
        before = self._snapshot(draft)
        line.write({"name": previous_text + "\n\n" + extra})
        self._record_undo(draft, before)
        return {"updated_id": line.id, "kind": "line_note", "appended": True,
                "amount_untaxed_estimate": draft.amount_untaxed_estimate}

    def remove_draft_line(self, line_id):
        line = self._get_line(line_id)
        draft = self.draft
        before = self._snapshot(draft)
        line.unlink()
        self._record_undo(draft, before)
        return {"removed_id": line_id, "amount_untaxed_estimate": draft.amount_untaxed_estimate}

    def _restore_snapshot(self, draft, previous):
        """Restore only provisional data; validation runs under the active user.

        IDs of previously deleted lines can change when restored. The new head
        fingerprint is recalculated after every undo, so the stack stays valid.
        """
        if not isinstance(previous, dict) or not isinstance(previous.get("lines"), list):
            raise ValueError("Instantánea de borrador dañada: no se ha deshecho nada.")
        for item in previous["lines"]:
            if item.get("product_id"):
                self._real_product(item["product_id"])
        draft.line_ids.unlink()
        draft.write({
            "description": previous["description"],
            "partner_id": previous["partner_id"],
            "pricelist_id": previous.get("pricelist_id") or False,
            "currency_id": previous["currency_id"],
            "assumptions": previous["assumptions"],
            "estimate_details": previous["estimate_details"],
            "undo_snapshot": False, "undo_after_fingerprint": False,
        })
        for item in previous["lines"]:
            values = {
                "draft_id": draft.id, "source_sale_line_id": item.get("source_line_id") or False, "line_kind": item["kind"], "name": item["name"],
                "sequence": item["sequence"], "product_id": item["product_id"],
                "product_uom_qty": item["quantity"], "price_unit": item["price_unit"],
                "discount": item["discount"], "price_source": item["price_source"],
                "price_evidence": item["price_evidence"],
            }
            if item["product_id"]:
                values["product_uom_id"] = item.get("uom_id") or False
            self.env["sale.ai.draft.line"].with_context(sale_ai_internal_edit=True).create(values)

    def undo_last_draft_change(self):
        draft = self.draft
        head = self.env["sale.ai.draft.change"].search(
            [("draft_id", "=", draft.id)], order="id desc", limit=1)
        legacy = not head and draft.undo_snapshot and draft.undo_after_fingerprint
        if not head and not legacy:
            raise ValueError("No hay más cambios del borrador que se puedan deshacer.")
        expected = head.after_fingerprint if head else draft.undo_after_fingerprint
        if self._digest(self._snapshot(draft)) != expected:
            raise ValueError(
                "El borrador se modificó fuera de este historial; deshacer podría sobrescribir cambios ajenos.")
        previous = json.loads(head.before_snapshot if head else draft.undo_snapshot)
        self._restore_snapshot(draft, previous)
        if head:
            head.unlink()
            # Restoring deleted lines may assign new IDs; rebase the new top
            # fingerprint without altering the actual previous snapshots.
            older = self.env["sale.ai.draft.change"].search(
                [("draft_id", "=", draft.id)], order="id desc", limit=1)
            if older:
                older.write({"after_fingerprint": self._digest(self._snapshot(draft))})
        remaining = self.env["sale.ai.draft.change"].search_count([("draft_id", "=", draft.id)])
        return {
            "undone": True, "proposal_id": draft.id,
            "undo_available": bool(remaining), "remaining_changes": remaining,
            "note": "Cambio deshecho. Puedes repetir Deshacer; los ID de líneas restauradas pueden variar.",
            "amount_untaxed_estimate": draft.amount_untaxed_estimate,
        }
