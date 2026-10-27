"""Isolated validation of custom sale.order comment mapping."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
class UserError(Exception): pass
tree=ast.parse((ROOT/'models/sale_ai_quotation.py').read_text())
method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_quote_comment_values')
ns={'UserError':UserError,'_':lambda x:x}
exec(compile(ast.Module(body=[method],type_ignores=[]),'actual mapping','exec'),ns)
def map_comment(text,field=None):
    session=NS(env={'sale.order':NS(_fields={'x_comentarios':field} if field else {})})
    return ns['_quote_comment_values'](session,NS(description=text))
class CommentTests(unittest.TestCase):
    def test_text_exact(self):
        field=NS(type='text',compute=False,inverse=False)
        text='Comentarios del cliente\nSegunda línea: ñ y 2,5 mm²'
        self.assertEqual(map_comment(text,field),{'x_comentarios':text})
    def test_empty_without_custom_field(self): self.assertEqual(map_comment('',None),{})
    def test_missing_field_is_explicit(self):
        with self.assertRaisesRegex(UserError,'x_comentarios'): map_comment('Comentario')
    def test_wrong_type_or_computed_field(self):
        for field in (NS(type='integer'),NS(type='text',compute=True,inverse=False)):
            with self.assertRaises(UserError): map_comment('Comentario',field)
    def test_char_limit(self):
        field=NS(type='char',compute=False,inverse=False,size=5)
        self.assertEqual(map_comment('12345',field),{'x_comentarios':'12345'})
        with self.assertRaises(UserError): map_comment('123456',field)
    def test_customer_reference_no_longer_used(self):
        text=(ROOT/'models/sale_ai_quotation.py').read_text()
        self.assertNotIn("'client_order_ref':",text)
        self.assertIn("values.update(session._quote_comment_values(preflight['_draft']))",text)
if __name__=='__main__': unittest.main()
