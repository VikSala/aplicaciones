"""Exercise the unmodified Python work-detection method without Odoo installed."""
import ast
from pathlib import Path
from types import SimpleNamespace

src = (Path(__file__).parents[1] / 'models' / 'sale_ai_panel.py').read_text()
class_node = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == 'SaleAISessionPanel')
func = next(n for n in class_node.body if isinstance(n, ast.FunctionDef) and n.name == '_panel_session_has_work')
func.decorator_list = []
namespace = {"UserError": type("UserError", (Exception,), {}), "ValidationError": type("ValidationError", (Exception,), {})}
exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), '<real_method>', 'exec'), namespace)
method = namespace['_panel_session_has_work']

def record(**attrs):
    return SimpleNamespace(**attrs)

class EditingSession:
    def __init__(self, change_count=0, messages=None, change_ids=None, comments='', assumptions='', broken=False):
        self.message_ids = messages or []
        self.technical_proposal = False
        self.edit_order_id = 52
        self.draft_id = record(line_ids=['already loaded line'], partner_id=1, pricelist_id=3,
            description=comments, assumptions=assumptions, estimate_details='', change_ids=change_ids or [])
        self.change_count = change_count
        self.broken = broken
    def _edit_original(self):
        if self.broken: raise ValueError('corrupt')
        return {'baseline':'old'}
    def _edit_plan(self, original, current):
        assert original is current
        return {'changes_count':self.change_count}

assert not method(None,EditingSession()),'PV seed lines are not user work'
assert method(None,EditingSession(change_count=1)), 'Real draft changes do count'
assert method(None,EditingSession(messages=['hello'])), 'Chat messages count'
assert method(None,EditingSession(change_ids=[1])), 'Undo history counts'
assert method(None,EditingSession(assumptions='manual')), 'Manual annotations count'
assert method(None,EditingSession(broken=True)), 'Corrupt baseline is protected'
new_chat=record(message_ids=[],technical_proposal=False,edit_order_id=False,
    draft_id=record(line_ids=[],partner_id=False,pricelist_id=False,description='',assumptions='',estimate_details=''))
assert not method(None,new_chat), 'Fresh chat is empty'
new_chat.draft_id.description = 'some text'
assert method(None,new_chat), 'New chat with written proposal has work'
print('OK: 11.24 real backend method distinguishes original PV data from edits')
