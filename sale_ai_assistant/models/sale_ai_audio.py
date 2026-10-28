"""Remote MP3 transcription over Vercel AI Gateway; no local audio software required."""
import base64

from odoo import models, _
from odoo.exceptions import UserError

from .sale_ai_gateway import GatewayError, get_gateway_key, get_transcription_model, transcribe_audio_gateway
from .sale_ai_attachment_limits import get_attachment_limits, over_limit


class SaleAIAudio(models.Model):
    _inherit = 'sale.ai.session'

    def _ai_transcribe_audio(self, raw, name):
        """Use the company's existing Vercel key; keep audio out of DeepSeek."""
        self.ensure_one()
        # Defer codec/header validation to the selected remote transcription
        # provider. Some legitimate MP3 exports have nonstandard prefixes; the
        # former two-signature check rejected them before reaching Vercel.
        # We never execute or decode these bytes locally.
        limits = get_attachment_limits(self.env, self.company_id.id)
        key = get_gateway_key(self.env, self.company_id.id)
        model_id = get_transcription_model(self.env, self.company_id.id)
        try:
            transcript = transcribe_audio_gateway(
                key,
                raw,
                model_id=model_id,
                timeout=int(self.company_id.sale_ai_request_timeout or 90),
                max_response_bytes=limits['transcription_response_kb'] * 1024,
                max_transcript_chars=limits['text_chars'],
            )
        except GatewayError as exc:
            raise UserError(_('No se ha podido transcribir el MP3: %s') % exc) from None

        if over_limit(len(transcript), limits['text_chars']):
            raise UserError(_('La transcripción supera el límite configurado de %s caracteres.') % limits['text_chars'])
        self.env['ir.attachment'].create({
            'name': name + '.transcripcion.txt',
            'datas': base64.b64encode(transcript.encode('utf-8')).decode('ascii'),
            'mimetype': 'text/plain',
            'res_model': 'sale.ai.session',
            'res_id': self.id,
            'public': False,
        })
        return 'Transcripción automática del audio (revisar medidas y referencias):\n' + transcript
