"""Standalone TXT/attachment tests using production methods, without Odoo."""
import base64
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
odoo = types.ModuleType('odoo')
odoo._ = lambda text: text
odoo.models = types.SimpleNamespace(Model=object)
odoo.api = types.SimpleNamespace()
odoo.fields = types.SimpleNamespace()
exceptions = types.ModuleType('odoo.exceptions')
class UserError(Exception): pass
exceptions.UserError = UserError
odoo.exceptions = exceptions
sys.modules['odoo'] = odoo
sys.modules['odoo.exceptions'] = exceptions
for name, directory in [('sale_ai_assistant', ROOT), ('sale_ai_assistant.models', ROOT/'models')]:
    module=types.ModuleType(name)
    module.__path__=[str(directory)]
    sys.modules[name]=module

def load(name):
    fullname='sale_ai_assistant.models.' + name
    spec=importlib.util.spec_from_file_location(fullname, ROOT/'models'/ (name+'.py'))
    module=importlib.util.module_from_spec(spec)
    sys.modules[fullname]=module
    spec.loader.exec_module(module)
    return module

load('sale_ai_gateway')
limits_module=load('sale_ai_attachment_limits')
files_module=load('sale_ai_files')

class Params:
    def sudo(self): return self
    def get_param(self, key, default=None): return default

class FilesTests(unittest.TestCase):
    def session(self):
        s=Mock()
        s.id=42
        s.company_id.id=7
        s.env={'ir.attachment': Mock(), 'ir.config_parameter': Params()}
        return s

    def test_txt_exact_and_scoped_attachment(self):
        s=self.session()
        data=base64.b64encode('Medición 2,5 mm²\n250 m'.encode()).decode()
        result=files_module.SaleAIFileSession._ai_prepare_files(s, [dict(name='medicion.txt', data=data)])
        self.assertIn('Medición 2,5 mm²\n250 m', result)
        values=s.env['ir.attachment'].create.call_args.args[0]
        self.assertEqual(values['res_id'],42)
        self.assertFalse(values['public'])

    def test_invalid_data_and_formats(self):
        for attachments in (
                [dict(name='a.exe', data='YQ==')],
                [dict(name='a.txt', data='!')],
                [dict(name='a.txt', data='')],
                [dict(name='a.txt', data=base64.b64encode(b'a'*50001).decode())],
                [dict(name=str(i)+'.txt', data='YQ==') for i in range(6)]):
            s=self.session()
            with self.assertRaises(UserError):
                files_module.SaleAIFileSession._ai_prepare_files(s, attachments)
            s.env['ir.attachment'].create.assert_not_called()

if __name__=='__main__':
    unittest.main(verbosity=2)
