from lxml import etree

from odoo import api, models


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    @api.model
    def b2b_ensure_custom_stock_privacy_view(self):
        """Conditionally protect the supplied custom warehouse-stock QWeb view.

        The warehouse blocks live in a user-created/Studio-style inherited view,
        so there is no stable module XML ID we can depend on.  A normal static
        inherited view would make this module fail to upgrade if that custom
        view were missing or temporarily disabled.

        We therefore locate the exact view by its custom stock fields and create
        a child QWeb view only when the expected nodes are really present.
        The child is registered under this module's XML-ID so it is reused on
        future upgrades and removed with the module.
        """
        View = self.sudo()
        Data = self.env["ir.model.data"].sudo()

        xmlid_module = "website_b2b_private"
        xmlid_name = "custom_warehouse_stock_privacy_runtime"

        model_data = Data.search([
            ("module", "=", xmlid_module),
            ("name", "=", xmlid_name),
            ("model", "=", "ir.ui.view"),
        ], limit=1)
        runtime_view = View.browse(model_data.res_id).exists() if model_data else View

        candidates = View.search([
            ("active", "=", True),
            ("arch_db", "ilike", "x_almacen1_custom"),
            ("arch_db", "ilike", "x_almacen2_custom"),
            ("arch_db", "ilike", "x_transit_stock_custom"),
            ("arch_db", "ilike", "x_almacen_local"),
        ], order="priority asc, id asc")

        target = View
        for candidate in candidates:
            try:
                root = etree.fromstring(candidate.arch_db.encode("utf-8"))
            except (etree.XMLSyntaxError, AttributeError):
                continue
            if (
                root.xpath(".//div[@id='box_europeo']")
                and root.xpath(".//div[@id='box_nacional']")
                and root.xpath(".//div[@id='box_alicante']")
            ):
                target = candidate
                break

        if not target:
            # CSS remains as a visual fallback, but do not create a brittle
            # inheritance record when the expected custom view is not present.
            if runtime_view:
                runtime_view.write({"active": False})
            return False

        arch = """
<data>
    <xpath expr="//div[@id='box_europeo']" position="attributes">
        <attribute name="t-if">website.b2b_can_purchase()</attribute>
    </xpath>
    <xpath expr="//div[@id='box_nacional']" position="attributes">
        <attribute name="t-if">website.b2b_can_purchase()</attribute>
    </xpath>
    <xpath expr="//div[@id='box_alicante']" position="attributes">
        <attribute name="t-if">website.b2b_can_purchase()</attribute>
    </xpath>
</data>
""".strip()

        vals = {
            "name": "B2B protect custom warehouse stock",
            "type": "qweb",
            "inherit_id": target.id,
            "priority": 220,
            "arch_db": arch,
            "active": True,
        }

        if runtime_view:
            runtime_view.write(vals)
        else:
            runtime_view = View.create(vals)
            if model_data:
                model_data.write({"res_id": runtime_view.id})
            else:
                Data.create({
                    "module": xmlid_module,
                    "name": xmlid_name,
                    "model": "ir.ui.view",
                    "res_id": runtime_view.id,
                    "noupdate": False,
                })

        return runtime_view.id


    @api.model
    def b2b_ensure_custom_similar_price_privacy_view(self):
        """Protect direct ``sim_prod.list_price`` output in custom QWeb.

        The supplied product-page customization renders prices for its custom
        "Productos similares" cards directly instead of calling the standard
        website_sale price template.  Locate that custom view dynamically and
        add a server-side authorization condition without depending on its
        database/XML identifier.
        """
        View = self.sudo()
        Data = self.env["ir.model.data"].sudo()

        xmlid_module = "website_b2b_private"
        xmlid_name = "custom_similar_price_privacy_runtime"

        model_data = Data.search([
            ("module", "=", xmlid_module),
            ("name", "=", xmlid_name),
            ("model", "=", "ir.ui.view"),
        ], limit=1)
        runtime_view = View.browse(model_data.res_id).exists() if model_data else View

        candidates = View.search([
            ("active", "=", True),
            ("arch_db", "ilike", "similar_products"),
            ("arch_db", "ilike", "sim_prod.list_price"),
        ], order="priority asc, id asc")

        target = View
        for candidate in candidates:
            if runtime_view and candidate.id == runtime_view.id:
                continue
            try:
                root = etree.fromstring(candidate.arch_db.encode("utf-8"))
            except (etree.XMLSyntaxError, AttributeError):
                continue
            if root.xpath(".//span[@t-field='sim_prod.list_price']"):
                target = candidate
                break

        if not target:
            if runtime_view:
                runtime_view.write({"active": False})
            return False

        arch = """
<data>
    <xpath expr="//span[@t-field='sim_prod.list_price']" position="attributes">
        <attribute name="t-if">website.b2b_can_purchase()</attribute>
    </xpath>
</data>
""".strip()

        vals = {
            "name": "B2B protect custom similar product prices",
            "type": "qweb",
            "inherit_id": target.id,
            "priority": 230,
            "arch_db": arch,
            "active": True,
        }

        if runtime_view:
            runtime_view.write(vals)
        else:
            runtime_view = View.create(vals)
            if model_data:
                model_data.write({"res_id": runtime_view.id})
            else:
                Data.create({
                    "module": xmlid_module,
                    "name": xmlid_name,
                    "model": "ir.ui.view",
                    "res_id": runtime_view.id,
                    "noupdate": False,
                })

        return runtime_view.id

    @api.model
    def b2b_ensure_legacy_vz_price_cleanup_view(self):
        """Neutralize the old manual VZ-only product-page condition.

        Some databases contain a direct product-page customization such as::

            <div t-if="not 'VZ' in (product.name or '')"> ... </div>
            <div t-else="">PRECIO NO DISPONIBLE</div>

        The module now owns that business rule and additionally checks that the
        current variant cost is zero.  This runtime child view removes the old
        VZ-only decision without requiring a hard XML-ID for the custom view.
        If the customization is later restored to standard Odoo, this runtime
        view simply deactivates itself.
        """
        View = self.sudo()
        Data = self.env["ir.model.data"].sudo()

        xmlid_module = "website_b2b_private"
        xmlid_name = "legacy_vz_price_cleanup_runtime"

        model_data = Data.search([
            ("module", "=", xmlid_module),
            ("name", "=", xmlid_name),
            ("model", "=", "ir.ui.view"),
        ], limit=1)
        runtime_view = View.browse(model_data.res_id).exists() if model_data else View

        candidates = View.search([
            ("active", "=", True),
            ("arch_db", "ilike", "PRECIO NO DISPONIBLE"),
            ("arch_db", "ilike", "VZ"),
            ("arch_db", "ilike", "website_sale.product_price"),
        ], order="priority asc, id asc")

        target = View
        for candidate in candidates:
            if runtime_view and candidate.id == runtime_view.id:
                continue
            try:
                root = etree.fromstring(candidate.arch_db.encode("utf-8"))
            except (etree.XMLSyntaxError, AttributeError):
                continue

            legacy_wrappers = root.xpath(
                ".//div[contains(@t-if, 'VZ') and .//t[@t-call='website_sale.product_price']]"
            )
            legacy_else = root.xpath(
                ".//div[@t-else and .//span[contains(normalize-space(.), 'PRECIO NO DISPONIBLE')]]"
            )
            if legacy_wrappers and legacy_else:
                target = candidate
                break

        if not target:
            if runtime_view:
                runtime_view.write({"active": False})
            return False

        arch = """
<data>
    <xpath expr="//div[contains(@t-if, 'VZ') and .//t[@t-call='website_sale.product_price']]" position="attributes">
        <attribute name="t-if">True</attribute>
    </xpath>
    <xpath expr="//div[@t-else and .//span[contains(normalize-space(.), 'PRECIO NO DISPONIBLE')]]" position="replace"/>
</data>
""".strip()

        vals = {
            "name": "B2B remove legacy VZ-only price condition",
            "type": "qweb",
            "inherit_id": target.id,
            "priority": 240,
            "arch_db": arch,
            "active": True,
        }

        if runtime_view:
            runtime_view.write(vals)
        else:
            runtime_view = View.create(vals)
            if model_data:
                model_data.write({"res_id": runtime_view.id})
            else:
                Data.create({
                    "module": xmlid_module,
                    "name": xmlid_name,
                    "model": "ir.ui.view",
                    "res_id": runtime_view.id,
                    "noupdate": False,
                })

        return runtime_view.id
