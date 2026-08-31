from odoo import _, fields, http
from odoo.http import request
from odoo.osv import expression
from odoo.exceptions import UserError

from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.sale.controllers.portal import CustomerPortal
from odoo.addons.website_sale_wishlist.controllers.main import WebsiteSaleWishlist


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

        # IMPORTANTE: /my/counters llama también a este método y espera que la
        # respuesta contenga ÚNICAMENTE los contadores solicitados. Si añadimos
        # aquí claves propias como ``cabrera_home_orders_count``, el JS nativo
        # de Odoo intenta buscar un elemento [data-placeholder_count] para esa
        # clave y, al no existir, termina haciendo ``null.textContent = ...``.
        #
        # Esto se manifiesta especialmente con usuarios internos porque suelen
        # tener más tarjetas/contadores de portal activos que un usuario portal.
        if counters:
            return values

        # En la carga HTML de /my y /my/home Odoo llama con counters=[]; ahí sí
        # añadimos los datos específicos de nuestro dashboard personalizado.
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

    # -------------------------------------------------------------------------
    # Listas de productos / favoritos
    # -------------------------------------------------------------------------

    def _cabrera_wishlist_context(self):
        partner = request.env.user.partner_id.sudo()
        website = request.website.sudo()
        return partner, website

    def _cabrera_current_wishes(self):
        """Favoritos visibles del usuario actual, manteniendo el criterio de Odoo."""
        partner, website = self._cabrera_wishlist_context()
        wishes = request.env["product.wishlist"].sudo().search([
            ("partner_id", "=", partner.id),
            ("website_id", "=", website.id),
            ("active", "=", True),
        ], order="create_date desc, id desc")
        return wishes.filtered(
            lambda wish: wish.product_id.product_tmpl_id.website_published
            and wish.product_id.product_tmpl_id._can_be_added_to_cart()
        )

    def _cabrera_product_lists(self):
        partner, website = self._cabrera_wishlist_context()
        return request.env["product.wishlist.list"].sudo().search([
            ("partner_id", "=", partner.id),
            ("website_id", "=", website.id),
        ], order="sequence, id")

    def _cabrera_get_product_list(self, list_id):
        partner, website = self._cabrera_wishlist_context()
        return request.env["product.wishlist.list"].sudo().search([
            ("id", "=", list_id),
            ("partner_id", "=", partner.id),
            ("website_id", "=", website.id),
        ], limit=1)

    def _cabrera_prepare_lists_values(self):
        values = self._prepare_portal_layout_values()
        wishes = self._cabrera_current_wishes()
        product_lists = self._cabrera_product_lists()
        current_ids = set(wishes.ids)
        list_wishes = {
            product_list.id: product_list.wish_ids.filtered(lambda wish: wish.id in current_ids)
            for product_list in product_lists
        }
        values.update({
            "page_name": "product_lists",
            # Estas páginas ya tienen su propia navegación (sidebar + volver a listas).
            # Desactivar breadcrumbs evita el bloque superior vacío con solo el icono Home.
            "no_breadcrumbs": True,
            "cabrera_wishes": wishes,
            "cabrera_product_lists": product_lists,
            "cabrera_list_wishes": list_wishes,
            "cabrera_website": request.website.sudo(),
        })
        return values

    def _cabrera_prepare_active_list_sale_values(self, values, active_wishes, list_ref):
        """Prepara precios y disponibilidad de compra para una lista concreta."""
        wish_infos = {}
        list_total = 0.0
        cart_wish_ids = []

        for wish in active_wishes:
            combination_info = wish.product_id._get_combination_info_variant()
            price = float(combination_info.get("price") or 0.0)
            prevent_zero_price_sale = bool(combination_info.get("prevent_zero_price_sale"))
            can_add_to_cart = (
                not prevent_zero_price_sale
                and wish.product_id._is_add_to_cart_allowed()
            )
            wish_infos[wish.id] = {
                "price": price,
                "prevent_zero_price_sale": prevent_zero_price_sale,
                "can_add_to_cart": can_add_to_cart,
            }
            if can_add_to_cart:
                cart_wish_ids.append(wish.id)
                list_total += price

        values.update({
            "cabrera_active_wish_infos": wish_infos,
            "cabrera_active_list_total": list_total,
            "cabrera_cart_wishes_count": len(cart_wish_ids),
            "cabrera_list_ref": str(list_ref),
        })
        return values

    def _cabrera_wishes_from_list_ref(self, list_ref):
        current_wishes = self._cabrera_current_wishes()
        if list_ref == "favorites":
            return current_wishes
        if str(list_ref or "").isdigit():
            product_list = self._cabrera_get_product_list(int(list_ref))
            if product_list:
                allowed_ids = set(current_wishes.ids)
                return product_list.wish_ids.filtered(lambda wish: wish.id in allowed_ids)
        return request.env["product.wishlist"]

    def _cabrera_list_return_url(self, list_ref):
        if list_ref == "favorites":
            return "/my/product-lists/favorites"
        if str(list_ref or "").isdigit() and self._cabrera_get_product_list(int(list_ref)):
            return f"/my/product-lists/{int(list_ref)}"
        return "/my/product-lists"

    def _cabrera_cart_order(self):
        order = request.website.sale_get_order(force_create=True)
        if order.state != "draft":
            request.website.sale_reset()
            order = request.website.sale_get_order(force_create=True)
        return order

    @http.route(
        ["/my/product-lists"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_product_lists(self, **kwargs):
        values = self._cabrera_prepare_lists_values()
        return request.render("mi_cuenta_extendida_usuario.portal_product_lists", values)

    @http.route(
        ["/my/product-lists/favorites"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_product_list_favorites(self, **kwargs):
        values = self._cabrera_prepare_lists_values()
        wishes = values["cabrera_wishes"]
        values.update({
            "cabrera_list_is_favorites": True,
            "cabrera_active_list": False,
            "cabrera_active_list_name": _("Favoritos"),
            "cabrera_active_wishes": wishes,
            "cabrera_assignable_wishes": request.env["product.wishlist"],
        })
        self._cabrera_prepare_active_list_sale_values(values, wishes, "favorites")
        return request.render("mi_cuenta_extendida_usuario.portal_product_list_detail", values)

    @http.route(
        ["/my/product-lists/<int:list_id>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_product_list_detail(self, list_id, **kwargs):
        product_list = self._cabrera_get_product_list(list_id)
        if not product_list:
            return request.redirect("/my/product-lists")

        values = self._cabrera_prepare_lists_values()
        current_wishes = values["cabrera_wishes"]
        current_ids = set(current_wishes.ids)
        list_wishes = product_list.wish_ids.filtered(lambda wish: wish.id in current_ids)
        assignable_wishes = current_wishes.filtered(lambda wish: wish.id not in set(list_wishes.ids))
        values.update({
            "cabrera_list_is_favorites": False,
            "cabrera_active_list": product_list,
            "cabrera_active_list_name": product_list.name,
            "cabrera_active_wishes": list_wishes,
            "cabrera_assignable_wishes": assignable_wishes,
        })
        self._cabrera_prepare_active_list_sale_values(values, list_wishes, product_list.id)
        return request.render("mi_cuenta_extendida_usuario.portal_product_list_detail", values)

    @http.route(
        "/my/product-lists/cart/add",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_cart_add(self, wish_id=None, quantity=1, list_ref="favorites", **post):
        return_url = self._cabrera_list_return_url(list_ref)
        if not str(wish_id or "").isdigit():
            return request.redirect(f"{return_url}?cart_error=1")

        try:
            quantity = max(1, min(int(quantity or 1), 9999))
        except (TypeError, ValueError):
            quantity = 1

        allowed_wishes = self._cabrera_wishes_from_list_ref(list_ref)
        wish = allowed_wishes.filtered(lambda current: current.id == int(wish_id))[:1]
        if not wish:
            return request.redirect(f"{return_url}?cart_error=1")

        try:
            order = self._cabrera_cart_order()
            cart_result = order._cart_update(product_id=wish.product_id.id, add_qty=quantity)
            request.session["website_sale_cart_quantity"] = order.cart_quantity
        except UserError:
            return request.redirect(f"{return_url}?cart_error=1")

        if not cart_result.get("quantity"):
            return request.redirect(f"{return_url}?cart_error=1")
        return request.redirect(f"{return_url}?cart_added={quantity}")

    @http.route(
        "/my/product-lists/cart/add-all",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_cart_add_all(self, list_ref="favorites", **post):
        return_url = self._cabrera_list_return_url(list_ref)
        wishes = self._cabrera_wishes_from_list_ref(list_ref)
        if not wishes:
            return request.redirect(f"{return_url}?cart_error=1")

        order = self._cabrera_cart_order()
        added = 0
        for wish in wishes:
            combination_info = wish.product_id._get_combination_info_variant()
            if combination_info.get("prevent_zero_price_sale"):
                continue
            if not wish.product_id._is_add_to_cart_allowed():
                continue
            try:
                cart_result = order._cart_update(product_id=wish.product_id.id, add_qty=1)
                if cart_result.get("quantity"):
                    added += 1
            except UserError:
                continue

        request.session["website_sale_cart_quantity"] = order.cart_quantity
        if not added:
            return request.redirect(f"{return_url}?cart_error=1")
        return request.redirect(f"{return_url}?cart_all_added={added}")

    @http.route(
        "/my/product-lists/create",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_create(self, name=None, **post):
        name = (name or "").strip()[:80]
        if not name:
            return request.redirect("/my/product-lists?list_error=empty")

        partner, website = self._cabrera_wishlist_context()
        ListModel = request.env["product.wishlist.list"].sudo()
        existing = ListModel.search([
            ("partner_id", "=", partner.id),
            ("website_id", "=", website.id),
            ("name", "=ilike", name),
        ], limit=1)
        if existing:
            return request.redirect("/my/product-lists?list_error=duplicate")

        product_list = ListModel.create({
            "name": name,
            "partner_id": partner.id,
            "website_id": website.id,
        })
        return request.redirect(f"/my/product-lists/{product_list.id}?created=1")

    @http.route(
        "/my/product-lists/<int:list_id>/rename",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_rename(self, list_id, name=None, **post):
        product_list = self._cabrera_get_product_list(list_id)
        if not product_list:
            return request.redirect("/my/product-lists")

        name = (name or "").strip()[:80]
        if not name:
            return request.redirect(f"/my/product-lists/{list_id}?list_error=empty")

        partner, website = self._cabrera_wishlist_context()
        duplicate = request.env["product.wishlist.list"].sudo().search([
            ("id", "!=", product_list.id),
            ("partner_id", "=", partner.id),
            ("website_id", "=", website.id),
            ("name", "=ilike", name),
        ], limit=1)
        if duplicate:
            return request.redirect(f"/my/product-lists/{list_id}?list_error=duplicate")

        product_list.name = name
        return request.redirect(f"/my/product-lists/{list_id}?renamed=1")

    @http.route(
        "/my/product-lists/<int:list_id>/delete",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_delete(self, list_id, **post):
        product_list = self._cabrera_get_product_list(list_id)
        if product_list:
            product_list.unlink()
        return request.redirect("/my/product-lists?deleted=1")

    @http.route(
        "/my/product-lists/<int:list_id>/add",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_add(self, list_id, **post):
        product_list = self._cabrera_get_product_list(list_id)
        if not product_list:
            return request.redirect("/my/product-lists")

        raw_ids = request.httprequest.form.getlist("wish_ids")
        wish_ids = [int(wish_id) for wish_id in raw_ids if str(wish_id).isdigit()]
        current_wishes = self._cabrera_current_wishes()
        allowed = current_wishes.filtered(lambda wish: wish.id in set(wish_ids))
        if allowed:
            product_list.write({"wish_ids": [(4, wish.id) for wish in allowed]})
        return request.redirect(f"/my/product-lists/{list_id}?products_added=1")

    @http.route(
        "/my/product-lists/assign",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_assign(self, wish_id=None, list_id=None, **post):
        if not (str(wish_id or "").isdigit() and str(list_id or "").isdigit()):
            return request.redirect("/my/product-lists/favorites")
        product_list = self._cabrera_get_product_list(int(list_id))
        current_wishes = self._cabrera_current_wishes()
        wish = current_wishes.filtered(lambda current: current.id == int(wish_id))[:1]
        if product_list and wish:
            product_list.write({"wish_ids": [(4, wish.id)]})
        return request.redirect("/my/product-lists/favorites?assigned=1")

    @http.route(
        "/my/product-lists/<int:list_id>/add-one/<int:wish_id>",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_add_one(self, list_id, wish_id, **post):
        product_list = self._cabrera_get_product_list(list_id)
        current_wishes = self._cabrera_current_wishes()
        wish = current_wishes.filtered(lambda current: current.id == wish_id)[:1]
        if product_list and wish:
            product_list.write({"wish_ids": [(4, wish.id)]})
        return request.redirect("/my/product-lists/favorites?assigned=1")

    @http.route(
        "/my/product-lists/<int:list_id>/remove/<int:wish_id>",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_remove(self, list_id, wish_id, **post):
        product_list = self._cabrera_get_product_list(list_id)
        if product_list and wish_id in product_list.wish_ids.ids:
            product_list.write({"wish_ids": [(3, wish_id)]})
        return request.redirect(f"/my/product-lists/{list_id}?product_removed=1")

    @http.route(
        "/my/product-lists/favorites/remove/<int:wish_id>",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_product_list_remove_favorite(self, wish_id, **post):
        current_wishes = self._cabrera_current_wishes()
        wish = current_wishes.filtered(lambda current: current.id == wish_id)[:1]
        if wish:
            wish.unlink()
        return request.redirect("/my/product-lists/favorites?favorite_removed=1")


class WebsiteSaleWishlistExtended(WebsiteSaleWishlist):
    """Lleva la wishlist estándar al área profesional para usuarios autenticados."""

    @http.route()
    def get_wishlist(self, count=False, **kw):
        # La petición count=1 la usa el JS nativo para mantener el contador.
        if count or request.website.is_public_user():
            return super().get_wishlist(count=count, **kw)
        return request.redirect("/my/product-lists/favorites")

