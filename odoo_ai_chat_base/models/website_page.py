from odoo import api, models
from odoo.osv import expression


class WebsitePage(models.Model):
    """Mejora el selector de páginas usado por la configuración del chatbot."""

    _inherit = "website.page"

    def _odoo_ai_chat_base_selector_label(self):
        self.ensure_one()
        name = self.name or "Página sin título"
        url = self.url or ""
        website = self.website_id.name if self.website_id else ""

        if url and not url.startswith("/"):
            url = "/" + url

        parts = [name]
        if url:
            parts.append(url)
        if website:
            parts.append(website)
        return " — ".join(parts)

    @api.depends("name", "url", "website_id.name")
    @api.depends_context("odoo_ai_chat_base_page_selector")
    def _compute_display_name(self):
        if not self.env.context.get("odoo_ai_chat_base_page_selector"):
            return super()._compute_display_name()
        for page in self:
            page.display_name = page._odoo_ai_chat_base_selector_label()

    def name_get(self):
        if self.env.context.get("odoo_ai_chat_base_page_selector"):
            return [(page.id, page._odoo_ai_chat_base_selector_label()) for page in self]
        return super().name_get()

    @api.model
    def name_search(self, name="", args=None, operator="ilike", limit=100):
        if not self.env.context.get("odoo_ai_chat_base_page_selector") or not name:
            return super().name_search(name=name, args=args, operator=operator, limit=limit)

        args = args or []
        domain = ["|", ("name", operator, name), ("url", operator, name)]
        pages = self.search(expression.AND([domain, args]), limit=limit)
        return pages.name_get()
