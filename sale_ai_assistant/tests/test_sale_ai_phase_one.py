from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleAIPhaseOne(TransactionCase):
    def setUp(self):
        super().setUp()
        # Previous tests ran as admin. Explicitly grant the native Sales
        # Administrator group so access doesn't depend on demo user defaults.
        group = self.env.ref("sales_team.group_sale_manager")
        if group not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, group.id)]})

    def test_panel_creates_single_active_session(self):
        panel = self.env["sale.ai.session"]
        self.assertTrue(panel.assistant_panel_bootstrap()["allowed"])
        self.assertFalse(panel.assistant_panel_bootstrap()["active"])
        first = panel.assistant_panel_get_or_create()
        self.assertEqual(first["state"], "active")
        self.assertFalse(first["messages"])
        self.assertFalse(first["draft"]["lines"])
        self.assertEqual(panel.assistant_panel_get_or_create()["id"], first["id"])

    def test_panel_denies_non_sales_user_without_reading_sessions(self):
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Usuario sin ventas (IA)",
            "login": "sale_ai_phase1_no_sales_test",
            "email": "sale_ai_phase1_no_sales_test@example.invalid",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        result = self.env["sale.ai.session"].with_user(user).assistant_panel_bootstrap()
        self.assertFalse(result["allowed"])
        self.assertFalse(result["active"])
        self.assertFalse(result["history"])

    def test_salesperson_cannot_access_panel_or_models(self):
        # Ordinary Sales users must not see the button and must not be able
        # to reach chat sessions or models through the ORM either.
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Vendedor no administrador (IA)",
            "login": "sale_ai_phase1_salesperson_test",
            "email": "sale_ai_phase1_salesperson_test@example.invalid",
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("sales_team.group_sale_salesman").id,
            ])],
        })
        panel = self.env["sale.ai.session"].with_user(user)
        self.assertFalse(panel.assistant_panel_bootstrap()["allowed"])
        with self.assertRaises(AccessError):
            panel.assistant_panel_get_or_create()
        with self.assertRaises(AccessError):
            panel.search([])
        with self.assertRaises(AccessError):
            self.env["sale.ai.model"].with_user(user).search([])

    def test_sales_administrator_can_use_panel(self):
        group = self.env.ref("sales_team.group_sale_manager")
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Administrador de Ventas (IA)",
            "login": "sale_ai_phase1_salesadmin_test",
            "email": "sale_ai_phase1_salesadmin_test@example.invalid",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id, group.id])],
        })
        panel = self.env["sale.ai.session"].with_user(user)
        self.assertTrue(panel.assistant_panel_bootstrap()["allowed"])
        session = panel.assistant_panel_get_or_create()
        self.assertEqual(session["state"], "active")

    def test_send_persist_and_cancel_is_permanent(self):
        panel = self.env["sale.ai.session"]
        first = panel.assistant_panel_get_or_create()
        first_id = first["id"]
        draft_id = self.env["sale.ai.session"].browse(first_id).draft_id.id
        created = panel.assistant_panel_send(first_id, " Instalación eléctrica ")
        self.assertEqual(created["content"], "Instalación eléctrica")
        self.assertEqual(panel.assistant_panel_open(first_id)["messages"][0]["content"], "Instalación eléctrica")
        new_session = panel.assistant_panel_new(first_id)
        self.assertNotEqual(new_session["id"], first_id)
        self.assertFalse(panel.browse(first_id).exists())
        self.assertFalse(self.env["sale.ai.draft"].browse(draft_id).exists())
        self.assertFalse(self.env["sale.ai.message"].browse(created["id"]).exists())
        self.assertFalse(new_session["messages"])
        self.assertFalse(panel.assistant_panel_bootstrap()["history"])

    def test_cancel_rejects_archived_session(self):
        panel = self.env["sale.ai.session"]
        session = panel.create({"name": "Archivada"})
        session.action_close()
        with self.assertRaises(UserError):
            panel.assistant_panel_new(session.id)
        self.assertTrue(session.exists())

    def test_invalid_messages_and_id(self):
        panel = self.env["sale.ai.session"]
        sid = panel.assistant_panel_get_or_create()["id"]
        with self.assertRaises(ValidationError):
            panel.assistant_panel_send(sid, "  ")
        with self.assertRaises(ValidationError):
            panel.assistant_panel_send(sid, "x" * 12001)
        with self.assertRaises(AccessError):
            panel.assistant_panel_open(999999999)
        with self.assertRaises(AccessError):
            panel.assistant_panel_send(999999999, "No autorizado")

    def test_history_limit_is_display_only(self):
        panel = self.env["sale.ai.session"]
        company = self.env.company
        old = company.sale_ai_chat_history_limit
        try:
            company.sale_ai_chat_history_limit = 1
            for name in ["Primera", "Segunda", "Tercera"]:
                panel.create({"name": name}).action_close()
            bootstrap = panel.assistant_panel_bootstrap()
            self.assertEqual(len(bootstrap["history"]), 1)
            self.assertEqual(panel.search_count([
                ("company_id", "=", company.id),
                ("user_id", "=", self.env.uid),
                ("state", "=", "archived"),
            ]), 3)
        finally:
            company.sale_ai_chat_history_limit = old
