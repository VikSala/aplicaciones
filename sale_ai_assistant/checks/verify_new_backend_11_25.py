"""Execute the actual panel-new method with simulated Odoo records for all actions."""
from pathlib import Path
from types import SimpleNamespace
import ast

source = (Path(__file__).parents[1] / 'models/sale_ai_panel.py').read_text()
cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'SaleAISessionPanel')
func = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'assistant_panel_new')
func.decorator_list = []
class ValidationError(Exception): pass
class UserError(Exception): pass
ns = {'ValidationError': ValidationError, 'UserError': UserError, '_': lambda s: s}
exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), '<assistant_panel_new>', 'exec'), ns)
method = ns['assistant_panel_new']

class Active:
    def __init__(self, edit=False):
        self.state = 'active'
        self.sale_order_id = False
        self.edit_order_id = edit
        self.closed = self.deleted = False
        self.locked = False
    def _ai_lock_session(self): self.locked = True
    def action_close(self): self.closed = True
    def unlink(self): self.deleted = True

class Panel:
    def __init__(self, session, work):
        self.session, self.work = session, work
        self.env = SimpleNamespace()
        self.created = []
    def _panel_find(self, session_id):
        assert session_id == 42
        return self.session
    def _panel_session_has_work(self, session): return self.work
    def create(self, values):
        self.created.append(values)
        return SimpleNamespace(id=43)
    def _panel_details(self, session): return {'id':session.id}

for edit in [False, True]:
    for work in [False, True]:
        for mode in ['auto','archive','discard']:
            session=Active(edit)
            panel=Panel(session, work)
            new=method(panel,42,mode)
            expect_archive = work and (mode == 'archive' or mode == 'auto' and edit)
            assert session.closed == expect_archive, (edit,work,mode,'archive')
            assert session.deleted != expect_archive, (edit,work,mode,'discard')
            assert session.locked and new['id'] == 43
            assert panel.created == [{'name':'Nuevo presupuesto IA'}]
for invalid in ('bad',True,None):
    session=Active(edit=True)
    try: method(Panel(session,True),42,invalid)
    except ValidationError: pass
    else: raise AssertionError('Invalid replace_mode accepted')
print('OK: 11.25 backend archive/discard/auto matrix, pristine baseline, mode validation')
