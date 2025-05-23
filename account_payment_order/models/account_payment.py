# Copyright 2019 ACSONE SA/NV
# Copyright 2022 Tecnativa - Pedro M. Baeza
# Copyright 2023 Noviat
# Copyright 2024 Tecnativa - Víctor Martínez
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    payment_order_id = fields.Many2one(comodel_name="account.payment.order")
    payment_line_ids = fields.Many2many(comodel_name="account.payment.line")
    order_state = fields.Selection(
        related="payment_order_id.state", string="Payment Order State"
    )
    payment_line_date = fields.Date(compute="_compute_payment_line_date")

    @api.depends("payment_type", "journal_id")
    def _compute_payment_method_line_fields(self):
        res = super()._compute_payment_method_line_fields()
        for pay in self:
            if pay.payment_order_id:
                pay.available_payment_method_line_ids = (
                    pay.journal_id._get_available_payment_method_lines(pay.payment_type)
                )
            else:
                pay.available_payment_method_line_ids = (
                    pay.journal_id._get_available_payment_method_lines(
                        pay.payment_type
                    ).filtered(lambda x: not x.payment_method_id.payment_order_only)
                )
            to_exclude = pay._get_payment_method_codes_to_exclude()
            if to_exclude:
                pay.available_payment_method_line_ids = (
                    pay.available_payment_method_line_ids.filtered(
                        lambda x, y=to_exclude: x.code not in y
                    )
                )
        return res

    @api.depends("payment_line_ids", "payment_line_ids.date")
    def _compute_payment_line_date(self):
        for item in self:
            item.payment_line_date = item.payment_line_ids[:1].date

    @api.depends("payment_line_ids")
    def _compute_partner_bank_id(self):
        # Force the payment line bank account. The grouping function has already
        # assured that there's no more than one bank account in the group
        order_pays = self.filtered("payment_line_ids")
        for pay in order_pays:
            pay.partner_bank_id = pay.payment_line_ids.partner_bank_id
        return super(AccountPayment, self - order_pays)._compute_partner_bank_id()

    def update_payment_reference(self):
        view = self.env.ref("account_payment_order.account_payment_update_view_form")
        return {
            "name": self.env._("Update Payment Reference"),
            "view_type": "form",
            "view_mode": "form",
            "res_model": "account.payment.update",
            "view_id": view.id,
            "target": "new",
            "type": "ir.actions.act_window",
            "context": dict(
                self.env.context, default_payment_reference=self.payment_reference
            ),
        }

    def _prepare_move_line_default_vals(
        self, write_off_line_vals=None, force_balance=None
    ):
        """Overwrite date_maturity of the move_lines that are generated when related
        to a payment order.
        """
        vals_list = super()._prepare_move_line_default_vals(
            write_off_line_vals=write_off_line_vals, force_balance=force_balance
        )
        if not self.payment_order_id:
            return vals_list
        for vals in vals_list:
            vals["date_maturity"] = self.payment_line_ids[0].date
        return vals_list

    def _generate_journal_entry(
        self, write_off_line_vals=None, force_balance=None, line_ids=None
    ):
        res = super()._generate_journal_entry(
            write_off_line_vals=write_off_line_vals,
            force_balance=force_balance,
            line_ids=line_ids,
        )
        # propagate the payment order to the generated move
        # now account.payment does not inherit from account.move,
        # so this step is necessary.
        for payment in self:
            if payment.payment_order_id and payment.move_id:
                payment.move_id.payment_order_id = payment.payment_order_id
        return res
