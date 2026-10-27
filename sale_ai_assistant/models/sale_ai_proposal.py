"""Persistent proposals. Only the server creates them; acceptance never calls an LLM."""
import json
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from .sale_ai_market import SaleAICommercialTools
from .sale_ai_draft_tools import MAX_LINE_NAME


class SaleAIProposal(models.Model):
    _inherit = 'sale.ai.session'

    technical_proposal = fields.Json(copy=False, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any('technical_proposal' in v for v in vals_list):
            raise AccessError(_('Las propuestas solo pueden generarse desde el asistente.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'technical_proposal' in vals and not self.env.su:
            raise AccessError(_('Las propuestas solo pueden modificarse desde el asistente.'))
        return super().write(vals)

    def _ai_resolve_proposal_target(self, target_id=0):
        """Validate before redaction and again at storage; never guess among notes."""
        self.ensure_one()
        self._ensure_can_edit_draft()
        if type(target_id) is not int or target_id < 0:
            raise UserError(_('El identificador de la nota no es válido.'))
        notes = self.draft_id.line_ids.filtered(lambda line: line.line_kind == 'line_note')
        if target_id and target_id not in notes.ids:
            raise UserError(_('El destino seleccionado no es una nota de este borrador. Indica si quieres una nota nueva o cuál de las notas existentes quieres modificar.'))
        return target_id

    def _ai_store_proposal(self, text, author, target_id=0):
        target_id = self._ai_resolve_proposal_target(target_id)
        tools = SaleAICommercialTools(self)
        proposal = {'token': uuid.uuid4().hex, 'text': text, 'author': author.name,
                    'model_id': author.id, 'line_id': target_id,
                    'fingerprint': tools._digest(tools._snapshot(self.draft_id))}
        self.sudo().write({'technical_proposal': proposal})
        return proposal

    def _ai_apply_proposal(self, token):
        self.ensure_one()
        self._ensure_can_edit_draft()
        proposal = self.technical_proposal
        if not proposal or proposal['token'] != token:
            raise UserError(_('Esta propuesta ya no está pendiente. Actualiza la conversación.'))
        tools = SaleAICommercialTools(self)
        if proposal['fingerprint'] != tools._digest(tools._snapshot(self.draft_id)):
            raise UserError(_('El borrador ha cambiado. Pide revisar la propuesta antes de aceptarla.'))
        if proposal['line_id']:
            name = 'update_draft_line'
            args = {'line_id': proposal['line_id'], 'name': proposal['text']}
        else:
            name = 'add_draft_lines'
            args = {'lines': [{'kind': 'line_note', 'name': proposal['text']}]}
        with self.env.cr.savepoint():
            result = tools.execute(name, json.dumps(args, ensure_ascii=False))
            if result.get('error'):
                raise UserError(result['error'])
            self.sudo().write({'technical_proposal': False})
            self.env['sale.ai.message'].sudo().create({
                'session_id': self.id, 'role': 'assistant',
                'content': (_('Nota guardada en la vista previa con tus modificaciones manuales.')
                            if proposal.get('edited_by_user') else
                            _('Nota guardada en la vista previa, con el texto exacto de %s.') % proposal['author']),
                'model_id': proposal['model_id'],
            })
        return result

    def _ai_edit_proposal(self, text):
        self.ensure_one()
        self._ensure_can_edit_draft()
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_LINE_NAME:
            raise UserError(_('Escribe una propuesta válida de hasta %s caracteres.') % MAX_LINE_NAME)
        proposal = dict(self.technical_proposal)
        text = text.strip()
        if text == proposal['text']:
            return proposal['token']
        proposal.update(text=text, edited_by_user=True, token=uuid.uuid4().hex)
        # Remove obsolete review metadata from proposals created by older versions.
        for field in ('observations', 'validator', 'validator_model_id', 'reviewed_text'):
            proposal.pop(field, None)
        # The fingerprint is deliberately preserved: editing must not approve a stale draft.
        self.sudo().write({'technical_proposal': proposal})
        self.env['sale.ai.message'].create({
            'session_id': self.id, 'role': 'user',
            'content': _('Edición manual de la propuesta técnica:\n\n%s') % text,
        })
        return proposal['token']

    @api.model
    def assistant_panel_proposal_action(self, session_id, token, action, text=None):
        session = self._panel_find(session_id)
        session._ensure_can_edit_draft()
        session._ai_lock_session()
        proposal = session.technical_proposal
        if not proposal or proposal['token'] != token:
            raise UserError(_('La propuesta ha cambiado o ya se ha procesado.'))
        if action in ('accept', 'improve'):
            with self.env.cr.savepoint():
                if text is not None:
                    token = session._ai_edit_proposal(text)
                if action == 'accept':
                    session._ai_apply_proposal(token)
        elif action == 'discard':
            session.sudo().write({'technical_proposal': False})
            self.env['sale.ai.message'].sudo().create({
                'session_id': session.id, 'role': 'assistant',
                'content': _('Propuesta descartada. El borrador no se ha modificado.'),
            })
        else:
            raise UserError(_('Acción de propuesta no válida.'))
        return self._panel_details(session)
