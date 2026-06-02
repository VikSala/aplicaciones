"""Tests for owa.notification.rule._vals_matches_trigger + transition firing."""
from odoo.tests import tagged

from .common import OwaTestCase


@tagged('post_install', '-at_install', 'open_whatsapp_connector')
class TestNotificationRuleTrigger(OwaTestCase):

    def setUp(self):
        super().setUp()
        self.Rule = self.env['owa.notification.rule']
        partner_model = self.env['ir.model']._get('res.partner')
        active_field = self.env['ir.model.fields'].search([
            ('model_id', '=', partner_model.id), ('name', '=', 'active'),
        ], limit=1)
        self.rule = self.Rule.create({
            'name': 'test rule',
            'active': False,
            'model_id': partner_model.id,
            'trigger_field_id': active_field.id,
            'trigger_value': 'False',
            'phone_field': 'phone',
            'custom_body': 'archived',
            'wa_account_id': self.account.id,
        })

    def test_boolean_trigger_match(self):
        self.assertTrue(self.rule._vals_matches_trigger({'active': False}))

    def test_boolean_trigger_no_match(self):
        self.assertFalse(self.rule._vals_matches_trigger({'active': True}))

    def test_unrelated_field_no_match(self):
        self.assertFalse(self.rule._vals_matches_trigger({'name': 'X'}))

    def test_many2one_trigger_by_id(self):
        partner_model = self.env['ir.model']._get('res.partner')
        parent_field = self.env['ir.model.fields'].search([
            ('model_id', '=', partner_model.id), ('name', '=', 'parent_id'),
        ], limit=1)
        target = self.env['res.partner'].search([], limit=1)
        rule = self.Rule.create({
            'name': 'm2o rule',
            'active': False,
            'model_id': partner_model.id,
            'trigger_field_id': parent_field.id,
            'trigger_value': str(target.id),
            'phone_field': 'phone',
            'custom_body': 'x',
            'wa_account_id': self.account.id,
        })
        self.assertTrue(rule._vals_matches_trigger({'parent_id': target.id}))
        self.assertFalse(rule._vals_matches_trigger({'parent_id': target.id + 9999}))
