"""Run directly with Python; isolated checks, not Odoo integration."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import Mock
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
class UserError(Exception): pass
source=ast.parse((ROOT/'models/sale_ai_proposal.py').read_text())
method=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='assistant_panel_proposal_action')
method.decorator_list=[]
ns={'UserError':UserError,'_':lambda text:text}
exec(compile(ast.Module(body=[method],type_ignores=[]),'actual action','exec'),ns)
class Session:
    action=ns['assistant_panel_proposal_action']
    id=1
    def __init__(self):
        self.technical_proposal={'token':'current','text':'Original'}
        self.env=SimpleNamespace(cr=SimpleNamespace(savepoint=nullcontext))
        self._ai_edit_proposal=Mock(return_value='edited')
        self._ai_apply_proposal=Mock()
    def _panel_find(self, sid): return self
    def _ensure_can_edit_draft(self): pass
    def _ai_lock_session(self): pass
    def _panel_details(self, session): return session.technical_proposal
class ActionsTests(unittest.TestCase):
    def test_removed_actions_do_not_mutate(self):
        for action in ('save','review'):
            s=Session()
            with self.assertRaises(UserError): s.action(1,'current',action,'Edit')
            s._ai_edit_proposal.assert_not_called()
            s._ai_apply_proposal.assert_not_called()
    def test_improve_preserves_edit_without_accepting(self):
        s=Session(); s.action(1,'current','improve','Edit')
        s._ai_edit_proposal.assert_called_once_with('Edit')
        s._ai_apply_proposal.assert_not_called()
    def test_accept_uses_edited_version(self):
        s=Session(); s.action(1,'current','accept','Edit')
        s._ai_edit_proposal.assert_called_once_with('Edit')
        s._ai_apply_proposal.assert_called_once_with('edited')
    def test_old_token_cannot_edit(self):
        s=Session()
        with self.assertRaises(UserError): s.action(1,'old','improve','Edit')
        s._ai_edit_proposal.assert_not_called()
    def test_only_three_proposal_buttons(self):
        xml=ET.parse(ROOT/'static/src/xml/sale_ai_chat.xml')
        actions=[n.attrib['t-on-click'] for n in xml.iter('button') if 'proposalAction' in n.attrib.get('t-on-click','')]
        self.assertEqual(actions,["() => this.proposalAction('accept')","() => this.proposalAction('improve')","() => this.proposalAction('discard')"])
    def test_no_optional_or_automatic_review_route(self):
        source=(ROOT/'models/sale_ai_engine.py').read_text()
        self.assertNotIn('proposal_review',source)
        tree=ast.parse(source)
        branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test).startswith("response_role == 'description' and"))
        calls=[n.args[0].value for n in ast.walk(branch) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='invoke']
        self.assertEqual(calls,['description'])
        self.assertNotIn('_ai_review_pending_proposal',(ROOT/'models/sale_ai_proposal.py').read_text())
if __name__=='__main__': unittest.main()
