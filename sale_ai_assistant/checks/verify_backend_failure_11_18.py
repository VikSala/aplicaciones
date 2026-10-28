"""Mock Odoo cursor and model to prove failed attachments return normal RPC data."""
import contextlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_audio_11_16 as earlier

earlier.odoo.api.model = lambda f: f
class AccessError(Exception):
    pass
class ValidationError(Exception):
    pass
earlier.exceptions.AccessError=AccessError
earlier.exceptions.ValidationError=ValidationError
panel = earlier.load('sale_ai_panel')

class Cursor:
    def __init__(self): self.savepoint_called=False
    @contextlib.contextmanager
    def savepoint(self):
        self.savepoint_called=True
        try: yield
        except Exception: raise

class Messages:
    def create(self, vals): raise AssertionError('Message must not be saved on failure')

class Environment(dict):
    def __init__(self):
        super().__init__({'sale.ai.message': Messages()})
        self.cr=Cursor()

class Session:
    id=321
    def _ensure_can_edit_draft(self): pass
    def _ai_lock_session(self): pass
    def _ai_prepare_files(self, files):
        assert files[0]['name']=='audio.mp3'
        raise earlier.UserError('Vercel rechazó MP3 (HTTP 415).')

obj=panel.SaleAISessionPanel()
obj.env=Environment()
obj._panel_find=lambda x: Session()
result=obj.assistant_panel_send(321,'Reformula este texto',[{'name':'audio.mp3','data':'SUQz'}])
assert result=={'file_error':'Vercel rechazó MP3 (HTTP 415).'},result
assert obj.env.cr.savepoint_called
print('11.18 backend: rechazo de transcripción devuelve error controlado sin guardar mensaje.')
