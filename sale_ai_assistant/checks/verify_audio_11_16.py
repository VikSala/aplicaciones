"""Legacy tests updated for company-scoped attachment settings."""
import base64
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]

odoo = types.ModuleType('odoo')
odoo._ = lambda text: text
odoo.models = types.SimpleNamespace(Model=object)
odoo.api = types.SimpleNamespace()
odoo.fields = types.SimpleNamespace()
exceptions = types.ModuleType('odoo.exceptions')
class UserError(Exception):
    pass
exceptions.UserError = UserError
odoo.exceptions = exceptions
sys.modules['odoo'] = odoo
sys.modules['odoo.exceptions'] = exceptions
root_pkg = types.ModuleType('sale_ai_assistant')
root_pkg.__path__ = [str(ROOT)]
models_pkg = types.ModuleType('sale_ai_assistant.models')
models_pkg.__path__ = [str(ROOT / 'models')]
sys.modules['sale_ai_assistant'] = root_pkg
sys.modules['sale_ai_assistant.models'] = models_pkg

def load(name):
    path = ROOT / 'models' / (name + '.py')
    name = 'sale_ai_assistant.models.' + name
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

gateway = load('sale_ai_gateway')
audio = load('sale_ai_audio')
files = load('sale_ai_files')

class Response:
    def __init__(self, value): self.value = value
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, n): return self.value[:n]

class FakeAttachments:
    def __init__(self): self.created=[]
    def create(self, values):
        self.created.append(values)
        return values

class Params:
    def __init__(self, vals=None): self.vals = vals or {}
    def sudo(self): return self
    def get_param(self, key, default=None): return self.vals.get(key, default)

class Session(audio.SaleAIAudio, files.SaleAIFileSession):
    def __init__(self):
        self.id = 42
        self.company_id = types.SimpleNamespace(id=7, sale_ai_request_timeout=60)
        self.attachments = FakeAttachments()
        self.params = Params()
        self.env = {'ir.attachment': self.attachments, 'ir.config_parameter': self.params}
    def ensure_one(self): pass
    def _ensure_can_edit_draft(self): pass

class GatewayAudioTests(unittest.TestCase):
    def test_request_contract_and_text(self):
        def fake_urlopen(req, timeout):
            self.assertEqual(req.full_url, 'https://ai-gateway.vercel.sh/v4/ai/transcription-model')
            self.assertEqual(req.get_header('Authorization'), 'Bearer prueba')
            self.assertEqual(req.get_header('Ai-model-id'), 'microsoft/mai-transcribe-2')
            self.assertEqual(req.get_header('Ai-transcription-model-specification-version'), '4')
            self.assertEqual(req.get_header('Ai-gateway-protocol-version'), '0.0.1')
            self.assertEqual(req.get_header('Ai-gateway-auth-method'), 'api-key')
            self.assertEqual(timeout, 51)
            payload = json.loads(req.data)
            self.assertEqual(payload['mediaType'], 'audio/mpeg')
            self.assertEqual(base64.b64decode(payload['audio']), b'ID3audio')
            return Response(json.dumps({'text': '  Tres luminarias de 2000 mm. ', 'language':'es'}).encode())
        with patch.object(gateway, 'urlopen', side_effect=fake_urlopen):
            self.assertEqual(gateway.transcribe_audio_gateway('prueba', b'ID3audio', model_id='microsoft/mai-transcribe-2', timeout=51),
                             'Tres luminarias de 2000 mm.')

    def test_http400_reports_upstream_message_without_leaking_secrets(self):
        import io
        upstream_body = json.dumps({'error': {
            'message': 'Missing required ai-gateway-protocol-version header. Credential: demo-secret-123',
            'type': 'invalid_request_error',
        }}).encode()
        with patch.object(gateway, 'urlopen', side_effect=HTTPError(
            'url', 400, 'Bad request', None, io.BytesIO(upstream_body)
        )):
            with self.assertRaises(gateway.GatewayError) as caught:
                gateway.transcribe_audio_gateway('demo-secret-123', b'ID3', model_id='microsoft/mai-transcribe-2')
        self.assertIn('HTTP 400', str(caught.exception))
        self.assertIn('ai-gateway-protocol-version', str(caught.exception))
        self.assertIn('invalid_request_error', str(caught.exception))
        self.assertNotIn('demo-secret-123', str(caught.exception))

    def test_http400_handles_non_json_body_and_suspicious_tokens(self):
        import io
        with patch.object(gateway, 'urlopen', side_effect=HTTPError('url', 400, 'Bad request', None,
                        io.BytesIO(b'<html>do not echo unexpected raw body</html>'))):
            with self.assertRaises(gateway.GatewayError) as caught:
                gateway.transcribe_audio_gateway('key', b'ID3')
        self.assertIn('HTTP 400', str(caught.exception))
        self.assertNotIn('do not echo', str(caught.exception))
        suspicious = json.dumps({'error': {'message': 'Invalid audio: ' + ('a' * 120)}}).encode()
        with patch.object(gateway, 'urlopen', side_effect=HTTPError('url', 400, 'Bad request', None,
                        io.BytesIO(suspicious))):
            with self.assertRaises(gateway.GatewayError) as caught:
                gateway.transcribe_audio_gateway('key', b'ID3')
        self.assertIn('[datos ocultos]', str(caught.exception))
        self.assertNotIn('a' * 120, str(caught.exception))

    def test_configurable_audio_model_validation(self):
        for model_id in ('microsoft/mai-transcribe-1.5', 'microsoft/mai-transcribe-2',
                         'openai/gpt-4o-mini-transcribe', 'openai/whisper-1'):
            gateway.validate_transcription_model(model_id)
        for model_id in ('', 'gpt-4o-transcribe', 'bad/id/extra', 'bad\nInjected', 'a/b '):
            with self.assertRaises(gateway.GatewayError):
                gateway.validate_transcription_model(model_id)

    def test_transcription_company_setting(self):
        class Params:
            def __init__(self): self.vals = {'sale_ai_assistant.transcription_model.7': 'openai/whisper-1'}
            def sudo(self): return self
            def get_param(self, key, default): return self.vals.get(key, default)
        env = {'ir.config_parameter': Params()}
        self.assertEqual(gateway.get_transcription_model(env, 7), 'openai/whisper-1')
        self.assertEqual(gateway.get_transcription_model(env, 8), 'microsoft/mai-transcribe-1.5')

    def test_errors_are_safe(self):
        with self.assertRaisesRegex(gateway.GatewayError, 'clave'):
            gateway.transcribe_audio_gateway('', b'ID3')
        with patch.object(gateway, 'urlopen', side_effect=HTTPError('url', 429, 'rate', None, None)):
            with self.assertRaisesRegex(gateway.GatewayError, '429'):
                gateway.transcribe_audio_gateway('key', b'ID3')
        with patch.object(gateway, 'urlopen', return_value=Response(b'{"unexpected": "secret"}')):
            with self.assertRaisesRegex(gateway.GatewayError, 'incompatible'):
                gateway.transcribe_audio_gateway('key', b'ID3')
        with patch.object(gateway, 'urlopen', return_value=Response(b'{"text":""}')):
            with self.assertRaisesRegex(gateway.GatewayError, 'voz'):
                gateway.transcribe_audio_gateway('key', b'ID3')

    def test_session_saves_mp3_and_private_txt(self):
        session = Session()
        encoded = base64.b64encode(b'ID3data').decode()
        with patch.object(audio, 'get_gateway_key', return_value='test-key'), \
             patch.object(audio, 'get_transcription_model', return_value='openai/gpt-4o-mini-transcribe'), \
             patch.object(audio, 'transcribe_audio_gateway', return_value='Necesito 10 metros de cable.') as transcriber:
            context = session._ai_prepare_files([{'name':'nota.mp3', 'data': encoded}])
        self.assertIn('Necesito 10 metros de cable.', context)
        transcriber.assert_called_once_with('test-key', b'ID3data', model_id='openai/gpt-4o-mini-transcribe',
            timeout=60, max_response_bytes=1024 * 1024, max_transcript_chars=50000)
        self.assertEqual(len(session.attachments.created), 2)
        self.assertEqual(session.attachments.created[0]['name'], 'nota.mp3.transcripcion.txt')
        self.assertEqual(session.attachments.created[0]['public'], False)
        self.assertEqual(session.attachments.created[1]['mimetype'], 'audio/mpeg')

    def test_mp4_rejected_without_ffmpeg(self):
        session = Session()
        with self.assertRaisesRegex(UserError, 'Formatos admitidos'):
            session._ai_prepare_files([{'name':'video.mp4', 'data': base64.b64encode(b'video').decode()}])
        # MP3 codec validation belongs to the selected remote provider; no
        # longer reject non-standard headers locally before an API request.
        with patch.object(audio, 'get_gateway_key', return_value='test-key'), \
             patch.object(audio, 'get_transcription_model', return_value='microsoft/mai-transcribe-2'), \
             patch.object(audio, 'transcribe_audio_gateway', side_effect=gateway.GatewayError('HTTP 415')) as remote:
            with self.assertRaisesRegex(UserError, 'HTTP 415'):
                session._ai_prepare_files([{'name':'falso.mp3', 'data': base64.b64encode(b'not mp3').decode()}])
            remote.assert_called_once()

    def test_upload_limits_prevent_billing_before_any_remote_call(self):
        session = Session()
        many = [{'name': f'{i}.txt', 'data': base64.b64encode(b'a').decode()} for i in range(6)]
        with self.assertRaisesRegex(UserError, '5 archivos'):
            session._ai_prepare_files(many)
        # An oversized image should be rejected by the application before Pillow.
        img = base64.b64encode(b'x' * (10 * 1024 * 1024 + 1)).decode()
        with self.assertRaisesRegex(UserError, '10 MiB'):
            session._ai_prepare_files([{'name': 'grande.jpg', 'data': img}])
        # 25MB MP3 + 6MB of additional files exceeds 30MB total, even though
        # each individual file is within its permitted size.
        mp3 = base64.b64encode(b'ID3' + b'a' * (25 * 1024 * 1024 - 3)).decode()
        b3mb = base64.b64encode(b'x' * (3 * 1024 * 1024)).decode()
        docs = [{'name': 'nota.mp3', 'data': mp3},
                {'name':'uno.txt', 'data': b3mb},
                {'name':'dos.txt', 'data': b3mb}]
        with patch.object(audio, 'transcribe_audio_gateway') as remote:
            with self.assertRaisesRegex(UserError, '30 MiB'):
                session._ai_prepare_files(docs)
            remote.assert_not_called()

    def test_custom_limits_really_apply(self):
        session = Session()
        prefix = 'sale_ai_assistant.attachment.'
        session.params.vals = {
            prefix+'max_files.7': '2',
            prefix+'txt_mb.7': '1',
            prefix+'total_mb.7': '2',
            prefix+'text_chars.7': '6',
        }
        with self.assertRaisesRegex(UserError, '2 archivos'):
            session._ai_prepare_files([{'name': str(i)+'.txt','data': 'YQ=='} for i in range(3)])
        with self.assertRaisesRegex(UserError, '1 MiB'):
            session._ai_prepare_files([{'name':'a.txt','data':base64.b64encode(b'x' * (1024*1024+1)).decode()}])
        with self.assertRaisesRegex(UserError, '6 caracteres'):
            session._ai_prepare_files([{'name':'a.txt','data':base64.b64encode(b'abcdefg').decode()}])

    def test_zero_removes_application_limits(self):
        session = Session()
        prefix = 'sale_ai_assistant.attachment.'
        session.params.vals = {
            prefix+'max_files.7':'0', prefix+'total_mb.7':'0',
            prefix+'txt_mb.7':'0', prefix+'text_chars.7':'0',
        }
        docs=[{'name':f'{i}.txt','data':base64.b64encode(b'z'*11).decode()} for i in range(9)]
        self.assertEqual(session._ai_prepare_files(docs).count('[Adjunto:'), 9)

    def test_gateway_413_from_provider_is_reported(self):
        session=Session()
        with patch.object(audio, 'get_gateway_key', return_value='key'), \
             patch.object(audio, 'get_transcription_model', return_value='microsoft/mai-transcribe-2'), \
             patch.object(gateway, 'urlopen', side_effect=HTTPError('url',413,'too large',None,None)):
            with self.assertRaisesRegex(UserError, 'HTTP 413'):
                session._ai_prepare_files([{'name':'audio.mp3','data':base64.b64encode(b'ID3audio').decode()}])

    def test_five_valid_documents(self):
        session = Session()
        docs = [{'name': f'{i}.txt', 'data': base64.b64encode(b'texto').decode()}
                for i in range(5)]
        result = session._ai_prepare_files(docs)
        self.assertEqual(result.count('[Adjunto:'), 5)
        self.assertEqual(len(session.attachments.created), 5)

    def test_existing_txt_still_works(self):
        session = Session()
        txt = session._ai_prepare_files([{'name':'detalle.txt', 'data': base64.b64encode(b'Detalle original').decode()}])
        self.assertIn('Detalle original', txt)
        self.assertEqual(session.attachments.created[0]['mimetype'], 'text/plain')

if __name__ == '__main__':
    unittest.main(verbosity=2)
