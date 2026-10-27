"""Isolated execution of real proposal methods with in-memory ORM doubles."""
import ast
import json
import uuid
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from contextlib import nullcontext
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
class UserError(Exception): pass
class GatewayError(Exception): pass
class Tools:
    def __init__(self, session): self.session=session
    def _snapshot(self, draft): return self.session.fingerprint
    def _digest(self, snapshot): return snapshot

source=ast.parse((ROOT/'models/sale_ai_proposal.py').read_text())
names={'_ai_review_pending_proposal','_ai_edit_proposal','assistant_panel_proposal_action'}
methods=[n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name in names]
for method in methods:
    method.decorator_list=[]
    method.body=[n for n in method.body if not isinstance(n,ast.ImportFrom)]
ns=dict(json=json,uuid=uuid,UserError=UserError,MAX_LINE_NAME=500000,
        SaleAICommercialTools=Tools,sale_ai_gateway=NS(GatewayError=GatewayError),
        COMMERCIAL_CRITERIA='',_=lambda x:x)
exec(compile(ast.Module(body=methods,type_ignores=[]),'<proposal methods>','exec'),ns)
class Session:
    _ai_review_pending_proposal=ns['_ai_review_pending_proposal']
    _ai_edit_proposal=ns['_ai_edit_proposal']
    assistant_panel_proposal_action=ns['assistant_panel_proposal_action']
    def __init__(self):
        self.id=1; self.fingerprint='original'; self.draft_id=object(); self.locked=False
        self.technical_proposal=dict(token='first',text='Texto inicial',fingerprint='original',
                                     author='Redactor',model_id=1,line_id=9)
        self.messages=Mock()
        self.env=Env(self.messages)
        self.calls=[]; self.reply={'content':'Sin errores; comprobar intensidad.', 'finish_reason':'stop'}
        self.reviewer=NS(id=2,name='Revisor')
    def ensure_one(self): pass
    def _ensure_can_edit_draft(self): pass
    def _panel_find(self, sid): assert sid==self.id; return self
    def _panel_details(self, session): return {'proposal':dict(session.technical_proposal)}
    def _ai_lock_session(self): self.locked=True
    def sudo(self): return self
    def write(self, vals): self.technical_proposal=vals['technical_proposal']
    def _ai_context_messages(self): return [{'role':'user','content':'Datos confirmados'}]
    def invoke(self, stage, model, messages):
        self.calls.append((stage,model,messages))
        if isinstance(self.reply,Exception): raise self.reply
        return self.reply,self.reviewer
    def _ai_generate_for(self, proposal_review=False):
        assert proposal_review and self.locked
        try: self._ai_review_pending_proposal(self.invoke,self.reviewer)
        except GatewayError: return {'error':'Fallo controlado. Referencia: test'}
        return {'proposal':self.technical_proposal}
class Env:
    def __init__(self,messages): self.messages=messages; self.cr=NS(savepoint=nullcontext)
    def __getitem__(self,key): assert key=='sale.ai.message'; return self.messages

class OptionalReviewTests(unittest.TestCase):
    def test_review_exact_edited_text_single_call_no_rewrite(self):
        s=Session(); old=dict(s.technical_proposal)
        result=s.assistant_panel_proposal_action(1,'first','review','Mi edición')
        self.assertEqual(len(s.calls),1)
        sent=json.loads(s.calls[0][2][1]['content'])
        self.assertEqual(sent['note'],'Mi edición')
        p=result['proposal']
        for key in ('fingerprint','line_id','author','model_id'): self.assertEqual(p[key],old[key])
        self.assertEqual(p['text'],'Mi edición')
        self.assertEqual(p['reviewed_text'],'Mi edición')
        self.assertEqual(p['validator'],'Revisor')
        self.assertNotEqual(p['token'],'first')
    def test_edit_invalidates_review(self):
        s=Session(); s.assistant_panel_proposal_action(1,'first','review')
        s._ai_edit_proposal('Nueva edición')
        for key in ('observations','validator','validator_model_id','reviewed_text'):
            self.assertNotIn(key,s.technical_proposal)
    def test_unchanged_edit_retains_review(self):
        s=Session(); s.assistant_panel_proposal_action(1,'first','review')
        p=dict(s.technical_proposal); s._ai_edit_proposal(p['text'])
        self.assertEqual(p,s.technical_proposal)
    def test_stale_token_rejected_without_call(self):
        s=Session()
        with self.assertRaises(UserError): s.assistant_panel_proposal_action(1,'old','review','Edit')
        self.assertEqual(s.calls,[])
        self.assertEqual(s.technical_proposal['text'],'Texto inicial')
    def test_changed_draft_rejected_without_call(self):
        s=Session(); s.fingerprint='changed'
        with self.assertRaises(UserError): s.assistant_panel_proposal_action(1,'first','review')
        self.assertEqual(s.calls,[])
    def test_failure_retains_edit_and_returns_error(self):
        s=Session(); s.reply=GatewayError('timeout')
        result=s.assistant_panel_proposal_action(1,'first','review','Edición conservada')
        self.assertEqual(result['proposal']['text'],'Edición conservada')
        self.assertIn('Referencia',result['proposal_review_error'])
        self.assertNotIn('observations',result['proposal'])
    def test_empty_and_truncated_review_do_not_replace_proposal(self):
        for reply in ({'content':''},{'content':'Partial','finish_reason':'length'}):
            s=Session(); old=dict(s.technical_proposal); s.reply=reply
            result=s.assistant_panel_proposal_action(1,'first','review')
            self.assertTrue(result['proposal_review_error'])
            self.assertEqual(s.technical_proposal,old)
    def test_normal_redaction_branch_calls_only_redactor(self):
        tree=ast.parse((ROOT/'models/sale_ai_engine.py').read_text())
        branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If)
                    and ast.unparse(n.test).startswith("response_role == 'description' and"))
        stages=[n.args[0].value for n in ast.walk(branch) if isinstance(n,ast.Call)
                and isinstance(n.func,ast.Name) and n.func.id=='invoke']
        self.assertEqual(stages,['description'])

if __name__=='__main__': unittest.main()
