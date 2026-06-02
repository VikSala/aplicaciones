from odoo import api, models
from odoo.osv import expression


# Extensión de páginas web para mejorar su selección dentro de la configuración del chat.
class WebsitePage(models.Model):
    _inherit = "website.page"

    # Genera una etiqueta clara para seleccionar páginas del sitio web.
    def _odoo_ai_chat_selector_label(self):
        self.ensure_one()

        name = self.name or "Página sin título"
        url = self.url or ""
        website = self.website_id.name if getattr(self, "website_id", False) else ""

        if url and not url.startswith("/"):
            url = "/" + url

        label_parts = [name]
        if url:
            label_parts.append(url)
        if website:
            label_parts.append(website)

        return " — ".join(label_parts)

    # Personaliza el nombre mostrado de páginas en el selector del addon.
    @api.depends("name", "url", "website_id.name")
    @api.depends_context("odoo_ai_chat_page_selector")
    def _compute_display_name(self):
        if not self.env.context.get("odoo_ai_chat_page_selector"):
            return super()._compute_display_name()

        for page in self:
            page.display_name = page._odoo_ai_chat_selector_label()

    # Devuelve nombres enriquecidos de páginas cuando se usa el selector del addon.
    def name_get(self):
        if self.env.context.get("odoo_ai_chat_page_selector"):
            return [(page.id, page._odoo_ai_chat_selector_label()) for page in self]
        return super().name_get()

    # Permite buscar páginas por nombre o URL en la configuración.
    @api.model
    def name_search(self, name="", args=None, operator="ilike", limit=100):
        if not self.env.context.get("odoo_ai_chat_page_selector") or not name:
            return super().name_search(name=name, args=args, operator=operator, limit=limit)

        args = args or []
        domain = ["|", ("name", operator, name), ("url", operator, name)]
        pages = self.search(expression.AND([domain, args]), limit=limit)
        return pages.name_get()
