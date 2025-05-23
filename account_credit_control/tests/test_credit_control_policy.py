# Copyright 2017 Okia SPRL (https://okia.be)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.base.tests.common import BaseCommon


@tagged("post_install", "-at_install")
class TestCreditControlPolicy(BaseCommon):
    def test_check_policy_against_account(self):
        """
        Test the model check_policy_against_account with several case
        """
        policy = self.env.ref("account_credit_control.credit_control_3_time")

        account = self.env["account.account"].create(
            {
                "code": "400001",
                "name": "Test",
                "account_type": "asset_receivable",
                "reconcile": True,
            }
        )

        # The account is not included in the policy
        with self.assertRaises(UserError):
            policy.check_policy_against_account(account)

        # We set the flag "do_nothing" to True
        policy.write({"account_ids": [(5, 0)], "do_nothing": True})
        result = policy.check_policy_against_account(account)
        self.assertTrue(result)

        # We add the account in the policy
        policy.write({"account_ids": [(6, 0, [account.id])]})
        result = policy.check_policy_against_account(account)
        self.assertTrue(result)

    def test_check_level_mode(self):
        """
        Check the method _check_level_mode on policy level
        """
        level_1 = self.env.ref("account_credit_control.3_time_1")

        with self.assertRaises(ValidationError):
            level_1.computation_mode = "previous_date"

    def test_previous_level(self):
        """
        Check the method _previous_level on policy level
        """
        level_1 = self.env.ref("account_credit_control.3_time_1")
        level_2 = self.env.ref("account_credit_control.3_time_2")

        previous_level = level_2._previous_level()
        self.assertEqual(previous_level, level_1)

    def test_get_sql_date_boundary_for_computation_mode(self):
        """
        Check the where clauses statement return by the method
        _get_sql_date_boundary_for_computation_mode
        according the computation mode
        """
        level_2 = self.env.ref("account_credit_control.3_time_2")

        level_2.computation_mode = "net_days"
        where_clause = level_2._net_days_get_boundary()
        result = level_2._get_sql_date_boundary_for_computation_mode()
        self.assertEqual(result, where_clause)

        level_2.computation_mode = "end_of_month"
        where_clause = level_2._end_of_month_get_boundary()
        result = level_2._get_sql_date_boundary_for_computation_mode()
        self.assertEqual(result, where_clause)

        level_2.computation_mode = "previous_date"
        where_clause = level_2._previous_date_get_boundary()
        result = level_2._get_sql_date_boundary_for_computation_mode()
        self.assertEqual(result, where_clause)
