# Copyright 2018 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.tests import Form

from .common import CommonTestCase


class TestSaleOrder(CommonTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def create_sale_order(self, payment_mode=None):
        with Form(self.env["sale.order"]) as sale_form:
            sale_form.partner_id = self.base_partner
            for _, p in self.products.items():
                with sale_form.order_line.new() as order_line:
                    order_line.product_id = p
                    order_line.name = p.name
                    order_line.product_uom_qty = 2
                    order_line.product_uom = p.uom_id
                    order_line.price_unit = p.list_price
        sale = sale_form.save()
        self.assertEqual(
            sale.payment_mode_id, self.base_partner.customer_payment_mode_id
        )
        sale_form = Form(sale)

        # force payment mode
        if payment_mode:
            sale_form.payment_mode_id = payment_mode
        return sale_form.save()

    def create_invoice_and_check(
        self, order, expected_payment_mode, expected_partner_bank
    ):
        order.action_confirm()
        order._create_invoices()
        invoice = order.invoice_ids
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.payment_mode_id, expected_payment_mode)
        self.assertEqual(invoice.partner_bank_id, expected_partner_bank)

    def test_sale_to_invoice_payment_mode(self):
        """
        Data:
            A partner with a specific payment_mode
            A sale order created with the payment_mode of the partner
        Test case:
            Create the invoice from the sale order
        Expected result:
            The invoice must be created with the payment_mode of the partner
        """
        order = self.create_sale_order()
        self.create_invoice_and_check(order, self.payment_mode, self.bank)

    def test_sale_to_invoice_payment_mode_2(self):
        """
        Data:
            A partner with a specific payment_mode
            A sale order created with an other payment_mode
        Test case:
            Create the invoice from the sale order
        Expected result:
            The invoice must be created with the specific payment_mode
        """
        order = self.create_sale_order(payment_mode=self.payment_mode_2)
        self.create_invoice_and_check(order, self.payment_mode_2, self.bank)

    def test_sale_to_invoice_payment_mode_via_payment(self):
        """
        Data:
            A partner with a specific payment_mode
            A sale order created with an other payment_mode
        Test case:
            Create the invoice from sale.advance.payment.inv
        Expected result:
            The invoice must be created with the specific payment_mode
        """
        order = self.create_sale_order(payment_mode=self.payment_mode_2)
        context = {
            "active_model": "sale.order",
            "active_ids": [order.id],
            "active_id": order.id,
        }
        order.action_confirm()
        payment = self.env["sale.advance.payment.inv"].create(
            {
                "advance_payment_method": "fixed",
                "fixed_amount": 5,
                "sale_order_ids": order,
            }
        )
        payment.with_context(**context).create_invoices()
        invoice = order.invoice_ids
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.payment_mode_id, self.payment_mode_2)
        self.assertFalse(invoice.partner_bank_id)

    def test_several_sale_to_invoice_payment_mode(self):
        """
        Data:
            A partner with a specific payment_mode
            A sale order created with the payment_mode of the partner
            A sale order created with another payment mode
        Test case:
            Create the invoice from the sale orders
        Expected result:
            Two invoices should be generated
        """
        payment_mode_2 = self.env["account.payment.mode"].create(
            {
                "name": "Direct Debit of suppliers from Société Générale",
                "bank_account_link": "variable",
                "payment_method_id": self.env.ref(
                    "account.account_payment_method_manual_out"
                ).id,
            }
        )
        order_1 = self.create_sale_order()
        order_2 = self.create_sale_order(payment_mode_2)
        orders = order_1 | order_2
        orders.action_confirm()
        invoices = orders._create_invoices()
        self.assertEqual(2, len(invoices))

    def test_change_sale_company(self):
        order = self.create_sale_order()
        other_company = self.env["res.company"].create({"name": "other company"})
        order.company_id = other_company
        self.assertFalse(order.payment_mode_id)
