"""Tool permissions for ONE agent turn, not linguistic intent routing.

The language model decides the purpose of a turn using a structured plan.
These permissions ensure a valuation cannot silently turn into commercial
lines, and a technical description can only change technical notes.
"""
import unicodedata

READ_ONLY = "read_only"
TECHNICAL_NOTE = "technical_note"
COMMERCIAL_LINES = "commercial_lines"
HEADER_ONLY = "header_only"
FULL_DRAFT = "full_draft"
UNDO = "undo"

WRITE_OPERATIONS = frozenset({
    "set_draft_header", "add_draft_lines", "update_draft_line",
    "append_draft_line_text", "remove_draft_line", "undo_last_draft_change",
})

SCOPES = frozenset({READ_ONLY, TECHNICAL_NOTE, COMMERCIAL_LINES,
                    HEADER_ONLY, FULL_DRAFT, UNDO})

WRITE_BY_SCOPE = {
    READ_ONLY: frozenset(),
    TECHNICAL_NOTE: frozenset({"add_draft_lines", "update_draft_line",
                                "append_draft_line_text"}),
    COMMERCIAL_LINES: frozenset({"add_draft_lines", "update_draft_line",
                                 "append_draft_line_text", "remove_draft_line"}),
    HEADER_ONLY: frozenset({"set_draft_header"}),
    FULL_DRAFT: WRITE_OPERATIONS - {"undo_last_draft_change"},
    UNDO: frozenset({"undo_last_draft_change"}),
}


def _normalized(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _requests_free_product_line(user_text):
    """Safety opt-in, never a method for choosing the user's intent.

    The agent may *not* infer permission for an uncatalogued commercial item
    from a request to estimate the cost of materials or technical work.
    """
    user = _normalized(user_text)
    return any(phrase in user for phrase in (
        "partida libre", "concepto libre", "linea libre", "linea sin producto",
        "sin producto de catalogo", "sin producto del catalogo",
        "sin referencia de catalogo", "sin referencia en catalogo",
        "producto generico sin referencia", "partida sin producto",
    ))


def visible_tool_names(scope, all_names):
    if scope not in SCOPES:
        raise ValueError("Ámbito de escritura no válido.")
    permitted = WRITE_BY_SCOPE[scope]
    return {name for name in all_names
            if name not in WRITE_OPERATIONS or name in permitted}


def validate_write(scope, name, args, draft, user_text):
    """Return Spanish validation error or None. Called BEFORE ORM writes."""
    if name not in WRITE_OPERATIONS:
        return None
    if name not in WRITE_BY_SCOPE.get(scope, frozenset()):
        return "Operación no autorizada para la finalidad de este turno. No se ha modificado el borrador."
    if not isinstance(args, dict):
        return "Los argumentos de modificación deben ser un objeto."
    if name == "add_draft_lines":
        lines = args.get("lines")
        if not isinstance(lines, list):
            return "Se necesita una lista de líneas válida."
        if scope == TECHNICAL_NOTE and any(
                not isinstance(row, dict) or row.get("kind") != "line_note"
                for row in lines):
            return "Una petición de descripción técnica solo puede crear notas, no partidas económicas."
        if any(isinstance(row, dict) and row.get("kind") == "product" and
               (row.get("allow_unlinked") or not row.get("product_id"))
               for row in lines) and not _requests_free_product_line(user_text):
            return ("No se permite crear partidas sin referencia de catálogo sin "
                    "una solicitud explícita del usuario de crear una partida libre.")
    if name == "update_draft_line" and args.get("allow_unlinked") and not _requests_free_product_line(user_text):
        return "No se permite convertir una línea en partida libre sin petición expresa."
    if name == "update_draft_line" and scope == TECHNICAL_NOTE:
        line_id = args.get("line_id")
        line = draft.line_ids.filtered(lambda record: record.id == line_id)
        if len(line) != 1 or line.line_kind != "line_note" or (set(args) - {"line_id", "name"}):
            return "Solo se permite actualizar el texto de una nota técnica existente."
    if name == "append_draft_line_text" and scope == TECHNICAL_NOTE:
        line_id = args.get("line_id")
        line = draft.line_ids.filtered(lambda record: record.id == line_id)
        if len(line) != 1 or line.line_kind != "line_note":
            return "Solo se permite ampliar una nota técnica existente."
    return None
