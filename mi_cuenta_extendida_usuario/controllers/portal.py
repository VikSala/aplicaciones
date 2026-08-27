from odoo import _, fields, http
from odoo.http import request
from odoo.osv import expression

from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.sale.controllers.portal import CustomerPortal


class CustomerPortalExtended(CustomerPortal):
    """Portal B2B enriquecido para pedidos, presupuestos y devoluciones."""

    # -------------------------------------------------------------------------
    # Valores comunes / Inicio
    # -------------------------------------------------------------------------

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        partner = request.env.user.partner_id.sudo()
        commercial_partner = partner.commercial_partner_id
        separate_billing = bool(partner.portal_separate_billing)

        invoice_partner = commercial_partner.child_ids.filtered(
            lambda p: p.type == "invoice" and p.active
        )[:1]

        # Si el usuario mantiene activado "Mismos datos de facturación", la
        # dirección efectiva es la de sus datos personales. Solo usamos el
        # contacto invoice independiente cuando ha elegido separarlos.
        billing_partner = invoice_partner if separate_billing and invoice_partner else partner

        # El usuario comercial llega desde portal, pero un usuario portal no
        # tiene permisos genéricos para leer res.users/res.partner internos.
        # Pasamos el comercial en sudo y renderizamos la imagen como data URI.
        sales_user = values.get("sales_user")
        if sales_user:
            sales_user = sales_user.sudo()

        values.update({
            "sales_user": sales_user,
            "portal_partner": partner,
            "portal_commercial_partner": commercial_partner,
            "portal_invoice_partner": invoice_partner,
            "portal_billing_partner": billing_partner,
            "portal_same_billing": not separate_billing,
        })
        return values

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id
        SaleOrder = request.env["sale.order"]

        home_orders = SaleOrder
        if SaleOrder.has_access("read"):
            domain = expression.AND([
                self._cabrera_orders_base_domain(partner),
                self._cabrera_status_domain("ongoing"),
            ])
            home_orders = SaleOrder.search(domain, order="date_order desc", limit=3).sudo()

        values.update({
            "cabrera_home_orders": home_orders,
            "cabrera_home_orders_count": len(home_orders),
        })
        return values

    # -------------------------------------------------------------------------
    # Pedidos
    # -------------------------------------------------------------------------

    def _cabrera_orders_base_domain(self, partner):
        return [
            ("message_partner_ids", "child_of", [partner.commercial_partner_id.id]),
            ("state", "in", ["sale", "cancel"]),
        ]

    def _cabrera_status_domain(self, status):
        if status == "ongoing":
            return [("state", "=", "sale"), ("delivery_status", "!=", "full")]
        if status == "done":
            return [("state", "=", "sale"), ("delivery_status", "=", "full")]
        if status == "cancel":
            return [("state", "=", "cancel")]
        return []

    def _cabrera_search_domain(self, search):
        if not search:
            return []
        return expression.OR([
            [("name", "ilike", search)],
            [("client_order_ref", "ilike", search)],
            [("order_line.product_id.name", "ilike", search)],
            [("order_line.product_id.default_code", "ilike", search)],
        ])

    def _cabrera_period_domain(self, date_from=None, date_to=None, field_name="date_order"):
        domain = []
        if date_from:
            try:
                start = fields.Date.to_date(date_from)
                domain.append((field_name, ">=", fields.Datetime.to_string(fields.Datetime.to_datetime(start))))
            except (TypeError, ValueError):
                date_from = None
        if date_to:
            try:
                end = fields.Date.to_date(date_to)
                end_dt = fields.Datetime.to_datetime(end).replace(hour=23, minute=59, second=59)
                domain.append((field_name, "<=", fields.Datetime.to_string(end_dt)))
            except (TypeError, ValueError):
                date_to = None
        return domain, date_from, date_to

    @http.route(
        ["/my/orders", "/my/orders/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_orders(
        self,
        page=1,
        status="all",
        search=None,
        sortby="date_desc",
        date_from=None,
        date_to=None,
        **kwargs,
    ):
        SaleOrder = request.env["sale.order"]
        partner = request.env.user.partner_id

        if status not in {"all", "ongoing", "done", "cancel"}:
            status = "all"

        sortings = {
            "date_desc": {"label": _("Más recientes"), "order": "date_order desc"},
            "date_asc": {"label": _("Más antiguos"), "order": "date_order asc"},
            "total_desc": {"label": _("Mayor importe"), "order": "amount_total desc"},
            "total_asc": {"label": _("Menor importe"), "order": "amount_total asc"},
            "name": {"label": _("Referencia"), "order": "name desc"},
        }
        if sortby not in sortings:
            sortby = "date_desc"

        values = self._prepare_portal_layout_values()
        base_domain = self._cabrera_orders_base_domain(partner)
        search_domain = self._cabrera_search_domain(search)
        period_domain, date_from, date_to = self._cabrera_period_domain(date_from, date_to)

        domain = expression.AND([
            base_domain,
            self._cabrera_status_domain(status),
            search_domain,
            period_domain,
        ])

        can_read = SaleOrder.has_access("read")
        total = SaleOrder.search_count(domain) if can_read else 0

        url_args = {"status": status, "sortby": sortby}
        if search:
            url_args["search"] = search
        if date_from:
            url_args["date_from"] = date_from
        if date_to:
            url_args["date_to"] = date_to

        pager = portal_pager(
            url="/my/orders",
            total=total,
            page=page,
            step=self._items_per_page,
            url_args=url_args,
        )

        orders = (
            SaleOrder.search(
                domain,
                order=sortings[sortby]["order"],
                limit=self._items_per_page,
                offset=pager["offset"],
            )
            if can_read
            else SaleOrder
        )

        def count(extra_domain):
            if not can_read:
                return 0
            return SaleOrder.search_count(expression.AND([base_domain, extra_domain]))

        status_counts = {
            "all": count([]),
            "ongoing": count(self._cabrera_status_domain("ongoing")),
            "done": count(self._cabrera_status_domain("done")),
            "cancel": count(self._cabrera_status_domain("cancel")),
        }

        orders_sudo = orders.sudo()
        request.session["my_orders_history"] = orders_sudo.ids[:100]

        values.update({
            "orders": orders_sudo,
            "page_name": "order",
            "pager": pager,
            "default_url": "/my/orders",
            "status_filter": status,
            "status_counts": status_counts,
            "search": search or "",
            "sortby": sortby,
            "cabrera_sortings": sortings,
            "date_from": date_from or "",
            "date_to": date_to or "",
        })
        return request.render("sale.portal_my_orders", values)

    # -------------------------------------------------------------------------
    # Presupuestos
    # -------------------------------------------------------------------------

    def _prepare_quotations_domain(self, partner):
        """Incluye borradores, aunque todavía no hayan sido enviados."""
        customer_scope = expression.OR([
            [("message_partner_ids", "child_of", [partner.commercial_partner_id.id])],
            [("partner_id", "child_of", [partner.commercial_partner_id.id])],
        ])
        return expression.AND([
            [("state", "in", ["draft", "sent"])],
            customer_scope,
        ])

    @http.route(
        ["/my/quotes", "/my/quotes/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_quotes(self, page=1, date_begin=None, date_end=None, **kwargs):
        """Lista presupuestos en borrador y enviados.

        Se usa sudo únicamente después de acotar explícitamente por la cuenta
        comercial del usuario. Esto evita que la regla portal estándar oculte
        un borrador que todavía no ha sido enviado/followed.
        """
        SaleOrder = request.env["sale.order"].sudo()
        partner = request.env.user.partner_id
        domain = [
            ("partner_id", "child_of", [partner.commercial_partner_id.id]),
            ("state", "in", ["draft", "sent"]),
        ]
        if date_begin and date_end:
            domain += [("create_date", ">", date_begin), ("create_date", "<=", date_end)]

        total = SaleOrder.search_count(domain)
        pager = portal_pager(
            url="/my/quotes",
            total=total,
            page=page,
            step=self._items_per_page,
            url_args={"date_begin": date_begin, "date_end": date_end},
        )
        quotations = SaleOrder.search(
            domain,
            order="date_order desc",
            limit=self._items_per_page,
            offset=pager["offset"],
        )
        request.session["my_quotations_history"] = quotations.ids[:100]

        values = self._prepare_portal_layout_values()
        values.update({
            "date": date_begin,
            "quotations": quotations,
            "orders": request.env["sale.order"],
            "page_name": "quote",
            "pager": pager,
            "default_url": "/my/quotes",
        })
        return request.render("sale.portal_my_quotations", values)

    @http.route()
    def portal_order_page(
        self,
        order_id,
        report_type=None,
        access_token=None,
        message=False,
        download=False,
        downpayment=None,
        **kw,
    ):
        # Permite abrir desde el portal un presupuesto propio todavía en draft.
        # Para cualquier otro caso se conserva exactamente la seguridad estándar.
        if not access_token and not request.env.user._is_public():
            order_sudo = request.env["sale.order"].sudo().browse(order_id).exists()
            if (
                order_sudo
                and order_sudo.state == "draft"
                and order_sudo.partner_id.commercial_partner_id
                == request.env.user.partner_id.commercial_partner_id
            ):
                access_token = order_sudo._portal_ensure_token()

        return super().portal_order_page(
            order_id,
            report_type=report_type,
            access_token=access_token,
            message=message,
            download=download,
            downpayment=downpayment,
            **kw,
        )

    @http.route(
        "/my/orders/<int:order_id>/detail",
        type="http",
        auth="user",
        website=True,
    )
    def portal_order_custom_detail(self, order_id, **kwargs):
        """Detalle B2B propio sin sustituir la vista estándar imprimible de Odoo."""
        partner = request.env.user.partner_id
        SaleOrder = request.env["sale.order"].sudo()
        order = SaleOrder.search(expression.AND([
            self._cabrera_orders_base_domain(partner),
            [("id", "=", order_id)],
        ]), limit=1)
        if not order:
            return request.redirect("/my/orders")

        product_lines = order.order_line.filtered(
            lambda line: not line.display_type and line.product_id
        )
        posted_invoices = order.invoice_ids.filtered(
            lambda inv: inv.state == "posted" and inv.move_type in ("out_invoice", "out_refund")
        )
        all_invoices_paid = bool(posted_invoices) and all(
            inv.payment_state in ("paid", "in_payment", "reversed") for inv in posted_invoices
        )

        values = self._prepare_portal_layout_values()
        values.update({
            "sale_order": order,
            "product_lines": product_lines,
            "posted_invoices": posted_invoices,
            "all_invoices_paid": all_invoices_paid,
            "page_name": "order",
        })
        return request.render("mi_cuenta_extendida_usuario.portal_order_custom_detail", values)

    # -------------------------------------------------------------------------
    # Devoluciones
    # -------------------------------------------------------------------------

    def _cabrera_returns_base_domain(self, partner):
        customer_scope = expression.OR([
            [("sale_id.message_partner_ids", "child_of", [partner.commercial_partner_id.id])],
            [("partner_id", "child_of", [partner.commercial_partner_id.id])],
        ])
        return expression.AND([
            [("move_ids.origin_returned_move_id", "!=", False)],
            [("location_id.usage", "=", "customer")],
            customer_scope,
        ])

    def _cabrera_return_status_domain(self, status):
        if status == "ongoing":
            return [("state", "not in", ["done", "cancel"])]
        if status == "done":
            return [("state", "=", "done")]
        if status == "cancel":
            return [("state", "=", "cancel")]
        return []

    def _cabrera_return_search_domain(self, search):
        if not search:
            return []
        return expression.OR([
            [("name", "ilike", search)],
            [("origin", "ilike", search)],
            [("sale_id.name", "ilike", search)],
            [("move_ids.product_id.name", "ilike", search)],
            [("move_ids.product_id.default_code", "ilike", search)],
        ])

    @http.route(
        ["/my/returns", "/my/returns/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_returns(
        self,
        page=1,
        status="all",
        search=None,
        sortby="date_desc",
        date_from=None,
        date_to=None,
        **kwargs,
    ):
        Picking = request.env["stock.picking"].sudo()
        partner = request.env.user.partner_id

        if status not in {"all", "ongoing", "done", "cancel"}:
            status = "all"

        sortings = {
            "date_desc": {"label": _("Más recientes"), "order": "create_date desc"},
            "date_asc": {"label": _("Más antiguas"), "order": "create_date asc"},
            "name": {"label": _("Referencia"), "order": "name desc"},
        }
        if sortby not in sortings:
            sortby = "date_desc"

        values = self._prepare_portal_layout_values()
        base_domain = self._cabrera_returns_base_domain(partner)
        search_domain = self._cabrera_return_search_domain(search)
        period_domain, date_from, date_to = self._cabrera_period_domain(
            date_from, date_to, field_name="create_date"
        )
        domain = expression.AND([
            base_domain,
            self._cabrera_return_status_domain(status),
            search_domain,
            period_domain,
        ])

        total = Picking.search_count(domain)
        url_args = {"status": status, "sortby": sortby}
        if search:
            url_args["search"] = search
        if date_from:
            url_args["date_from"] = date_from
        if date_to:
            url_args["date_to"] = date_to

        pager = portal_pager(
            url="/my/returns",
            total=total,
            page=page,
            step=self._items_per_page,
            url_args=url_args,
        )
        returns = Picking.search(
            domain,
            order=sortings[sortby]["order"],
            limit=self._items_per_page,
            offset=pager["offset"],
        )

        def count(extra_domain):
            return Picking.search_count(expression.AND([base_domain, extra_domain]))

        status_counts = {
            "all": count([]),
            "ongoing": count(self._cabrera_return_status_domain("ongoing")),
            "done": count(self._cabrera_return_status_domain("done")),
            "cancel": count(self._cabrera_return_status_domain("cancel")),
        }

        values.update({
            "returns": returns,
            "page_name": "return",
            "pager": pager,
            "default_url": "/my/returns",
            "status_filter": status,
            "status_counts": status_counts,
            "search": search or "",
            "sortby": sortby,
            "cabrera_sortings": sortings,
            "date_from": date_from or "",
            "date_to": date_to or "",
        })
        return request.render("mi_cuenta_extendida_usuario.portal_my_returns", values)

    @http.route(
        "/my/returns/<int:picking_id>",
        type="http",
        auth="user",
        website=True,
    )
    def portal_return_detail(self, picking_id, **kwargs):
        Picking = request.env["stock.picking"].sudo()
        partner = request.env.user.partner_id
        picking = Picking.search(expression.AND([
            self._cabrera_returns_base_domain(partner),
            [("id", "=", picking_id)],
        ]), limit=1)
        if not picking:
            return request.redirect("/my/returns")

        values = self._prepare_portal_layout_values()
        values.update({
            "return_picking": picking,
            "page_name": "return",
        })
        return request.render("mi_cuenta_extendida_usuario.portal_return_detail", values)

    # -------------------------------------------------------------------------
    # Datos personales / dirección de facturación
    # -------------------------------------------------------------------------

    def _sync_existing_billing_from_partner(self, partner):
        """Mantiene coherente un contacto invoice existente cuando ambas direcciones son iguales."""
        partner = partner.sudo()
        commercial_partner = partner.commercial_partner_id
        invoice_partner = commercial_partner.child_ids.filtered(
            lambda p: p.type == "invoice" and p.active
        )[:1]
        if not invoice_partner:
            return

        invoice_partner.write({
            "name": partner.name,
            "street": partner.street,
            "street2": partner.street2,
            "zip": partner.zip,
            "city": partner.city,
            "state_id": partner.state_id.id or False,
            "country_id": partner.country_id.id or False,
            "phone": partner.phone,
            "email": partner.email,
        })

    @http.route()
    def account(self, redirect=None, **post):
        """Añade el selector de facturación sin romper la validación nativa del portal."""
        same_billing = post.pop("same_billing", None)
        is_cabrera_form = post.pop("cabrera_account_form", None)

        if request.httprequest.method == "POST" and is_cabrera_form and not redirect:
            redirect = "/my/account?personal_saved=1"

        response = super().account(redirect=redirect, **post)

        # El controlador nativo devuelve redirección únicamente cuando la
        # validación y la escritura han terminado correctamente.
        if (
            request.httprequest.method == "POST"
            and is_cabrera_form
            and getattr(response, "status_code", 0) in (301, 302, 303)
        ):
            partner = request.env.user.partner_id.sudo()
            partner.portal_separate_billing = not bool(same_billing)
            if same_billing:
                self._sync_existing_billing_from_partner(partner)

        return response

    @http.route(
        "/my/account/billing",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_update_billing_address(self, **post):
        partner = request.env.user.partner_id.sudo()
        commercial_partner = partner.commercial_partner_id
        Partner = request.env["res.partner"].sudo()

        invoice_partner = commercial_partner.child_ids.filtered(
            lambda p: p.type == "invoice" and p.active
        )[:1]

        def clean(value):
            return (value or "").strip()

        vals = {
            "name": clean(post.get("billing_name")) or commercial_partner.name,
            "type": "invoice",
            "street": clean(post.get("billing_street")),
            "street2": clean(post.get("billing_street2")),
            "zip": clean(post.get("billing_zip")),
            "city": clean(post.get("billing_city")),
            "phone": clean(post.get("billing_phone")),
            "email": clean(post.get("billing_email")),
        }

        country_id = post.get("billing_country_id")
        state_id = post.get("billing_state_id")
        vals["country_id"] = int(country_id) if country_id and str(country_id).isdigit() else False
        vals["state_id"] = int(state_id) if state_id and str(state_id).isdigit() else False

        if invoice_partner:
            invoice_partner.write(vals)
        else:
            vals["parent_id"] = commercial_partner.id
            Partner.create(vals)

        partner.portal_separate_billing = True
        return request.redirect("/my/account?billing_saved=1")
