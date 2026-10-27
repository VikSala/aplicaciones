"""Isolated checks of production target resolution and error handling."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
class UserError(Exception): pass
class GatewayError(Exception): pass
source=ast.parse((ROOT/'models/sale_ai_proposal.py').read_text())
method=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='_ai_resolve_proposal_target')
ns={'UserError':UserError,'_':lambda x:x}
exec(compile(ast.Module(body=[method],type_ignores=[]),'actual resolver','exec'),ns)
class Notes:
    def __init__(self,ids): self.ids=ids
    def filtered(self,fn): return self
    def __bool__(self): return bool(self.ids)
    def __len__(self): return len(self.ids)
    @property
    def id(self): assert len(self.ids)==1; return self.ids[0]
class Session:
    resolve=ns['_ai_resolve_proposal_target']
    def __init__(self,ids=(),closed=False): self.draft_id=NS(line_ids=Notes(list(ids))); self.closed=closed
    def ensure_one(self): pass
    def _ensure_can_edit_draft(self):
        if self.closed: raise UserError('Borrador cerrado')
    def _ai_error_or_saved_draft_notice(self,message,before): return message
engine=ast.parse((ROOT/'models/sale_ai_engine.py').read_text())
outer=next(n for n in ast.walk(engine) if isinstance(n,ast.Try) and any(isinstance(h.type,ast.Tuple) and 'UserError' in ast.unparse(h.type) for h in n.handlers))
wrapper=ast.parse('def handle(self, exc):\n    pass').body[0]
wrapper.body=[ast.Try(body=[ast.Raise(exc=ast.Name(id='exc',ctx=ast.Load()))],handlers=outer.handlers,orelse=[],finalbody=[])]
env=dict(UserError=UserError,sale_ai_gateway=NS(GatewayError=GatewayError),
         record_turn_failure=lambda e:'Referencia: test',before_signature='before',_=lambda x:x)
exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[])),'actual handlers','exec'),env)
class PreflightTests(unittest.TestCase):
    def test_new_note(self): self.assertEqual(Session().resolve(0),0)
    def test_single_existing_note(self): self.assertEqual(Session([7]).resolve(0),0)
    def test_explicit_note_among_multiple(self): self.assertEqual(Session([7,8]).resolve(8),8)
    def test_ambiguous_or_unknown_target(self):
        for ids,target,message in [([7],9,'no es una nota')]:
            with self.assertRaisesRegex(UserError,message): Session(ids).resolve(target)
    def test_new_note_with_multiple_existing_notes(self):
        self.assertEqual(Session([7,8]).resolve(0),0)
    def test_invalid_target_or_closed_draft(self):
        for target in (-1,True,'7',None):
            with self.assertRaises(UserError): Session().resolve(target)
        with self.assertRaisesRegex(UserError,'cerrado'): Session(closed=True).resolve()
    def test_expected_error_visible_with_reference(self):
        for exc in (UserError('Hay varias notas'),GatewayError('Conexión fallida')):
            message=env['handle'](Session(),exc)
            self.assertIn(str(exc),message); self.assertIn('Referencia: test',message)
    def test_unexpected_error_remains_generic(self):
        message=env['handle'](Session(),RuntimeError('internal details'))
        self.assertNotIn('internal details',message); self.assertIn('Referencia: test',message)
    def test_preflight_before_description_and_storage_rechecks(self):
        branch=next(n for n in ast.walk(engine) if isinstance(n,ast.If) and ast.unparse(n.test).startswith("response_role == 'description' and"))
        text=ast.unparse(branch)
        self.assertLess(text.index('_ai_resolve_proposal_target'),text.index("invoke('description'"))
        store=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='_ai_store_proposal')
        self.assertIn('_ai_resolve_proposal_target',ast.unparse(store.body[0]))
if __name__=='__main__': unittest.main()
