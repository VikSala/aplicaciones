"""Exercise actual add_draft_lines with an in-memory ORM and value adapter."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
tree=ast.parse((ROOT/'models/sale_ai_draft_tools.py').read_text())
method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='add_draft_lines')
ns={'MAX_BATCH_LINES':8,'MAX_DRAFT_LINES':40}
exec(compile(ast.Module(body=[method],type_ignores=[]),'actual add lines','exec'),ns)
class Tools:
    add=ns['add_draft_lines']
    def __init__(self,kind):
        self.draft=NS(id=1,line_ids=[NS(sequence=10,line_kind=kind,name='Original')],amount_untaxed_estimate=0)
        self.env={'sale.ai.draft.line':self};self.raw=[]
    def _snapshot(self,draft): return None
    def _record_undo(self,*args): pass
    def _line_values(self,item):
        self.raw.append(item)
        return dict(sequence=max(l.sequence for l in self.draft.line_ids)+10,line_kind=item['kind'],name=item['name'])
    def create(self,vals):
        obj=NS(**vals,id=len(self.draft.line_ids)+1,product_id=NS(id=False,default_code=''))
        self.draft.line_ids.append(obj);return obj
class OrderTests(unittest.TestCase):
    def test_both_creation_orders_and_provider_sequence(self):
        for first,second in [('product','line_note'),('line_note','product')]:
            t=Tools(first);t.add([{'kind':second,'name':'Nueva','sequence':1}])
            self.assertEqual([l.line_kind for l in sorted(t.draft.line_ids,key=lambda l:l.sequence)],[first,second])
            self.assertNotIn('sequence',t.raw[0])
    def test_batch_keeps_supplied_order(self):
        t=Tools('line_note');t.add([{'kind':'product','name':'A','sequence':1},{'kind':'line_note','name':'B'}])
        self.assertEqual([l.sequence for l in t.draft.line_ids],[10,20,30])
    def test_no_notes_provider_product_target_is_new_note(self):
        tree=ast.parse((ROOT/'models/sale_ai_engine.py').read_text())
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=='not note_ids')
        scope={'note_ids':[],'target_id':99}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual fallback','exec'),scope)
        self.assertEqual(scope['target_id'],0)
        scope={'note_ids':[7],'target_id':7}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual fallback','exec'),scope)
        self.assertEqual(scope['target_id'],7)
if __name__=='__main__': unittest.main()
