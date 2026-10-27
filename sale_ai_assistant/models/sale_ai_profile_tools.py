"""Explicit, limited AI tools for company quotation profiles."""
import json

from odoo.exceptions import AccessError, UserError, ValidationError

from .sale_ai_draft_tools import SaleAIDraftTools


class SaleAIProfileTools(SaleAIDraftTools):
    def definitions(self):
        values = super().definitions()
        empty = {'type': 'object', 'properties': {}, 'additionalProperties': False}
        values += [
            {'type': 'function', 'function': {
                'name': 'find_quotation_profile',
                'description': 'Consulta la regla de ESTRUCTURA comercial apropiada para el trabajo actual. No estima precios ni escribe datos. Devuelve disponibilidad de productos exactos de Odoo.',
                'parameters': {'type': 'object', 'properties': {
                    'work_description': {'type': 'string', 'description': 'Trabajo técnico a presupuestar; evita datos de clientes.'}},
                    'required': ['work_description'], 'additionalProperties': False},
            }},
            {'type': 'function', 'function': {
                'name': 'get_historical_line_patterns',
                'description': 'Si no hay una regla clara, resume SOLO las estructuras de hasta 5 pedidos/presupuestos parecidos. No reutilices sus precios ni traigas sus notas completas.',
                'parameters': {'type': 'object', 'properties': {
                    'query': {'type': 'string', 'description': 'Tipo de trabajo (mínimo 5 caracteres).'}},
                    'required': ['query'], 'additionalProperties': False},
            }},
            {'type': 'function', 'function': {
                'name': 'apply_quotation_profile',
                'description': 'Compone SOLO el borrador provisional en producto principal + nota técnica + importe global. Conserva el desglose interno, reutiliza líneas sin duplicarlas. Úsala tras redactar la nota y calcular/aceptar el importe. No usar si el usuario pide expresamente un presupuesto desglosado. No crea sale.order.',
                'parameters': {'type': 'object', 'properties': {
                    'profile_id': {'type': 'integer', 'description': 'ID real devuelto por find_quotation_profile.'}},
                    'required': ['profile_id'], 'additionalProperties': False},
            }},
        ]
        if not self.history_limit:
            values = [item for item in values
                      if item['function']['name'] != 'get_historical_line_patterns']
        return values

    def execute(self, name, raw_arguments):
        if name not in ('find_quotation_profile', 'get_historical_line_patterns', 'apply_quotation_profile'):
            return super().execute(name, raw_arguments)
        if name == 'get_historical_line_patterns' and not self.history_limit:
            return {'error': 'Consulta de históricos deshabilitada.'}
        try:
            if not isinstance(raw_arguments, str) or len(raw_arguments) > 1200:
                raise ValueError('Argumentos demasiado largos.')
            args = json.loads(raw_arguments)
            if not isinstance(args, dict):
                raise ValueError('Argumentos inválidos.')
            Profile = self.env['sale.ai.quotation.profile']
            if name == 'find_quotation_profile':
                if set(args) != {'work_description'} or not isinstance(args['work_description'], str):
                    raise ValueError('Indica work_description.')
                if len(args['work_description']) > 1000:
                    raise ValueError('Descripción demasiado extensa.')
                profile = Profile._select_for_text(args['work_description'], self.company)
                if not profile:
                    return {'found': False, 'message': 'No existe regla comercial para este trabajo.'}
                result = {'found': True, 'profile_id': profile.id, 'name': profile.name,
                          'structure': profile.structure, 'main_product_code': profile.main_product_code,
                          'global_product_code': profile.global_product_code}
                for slot in ('main', 'global'):
                    try:
                        product = profile._resolve_product(slot, self.company)
                        result[slot + '_product_id'] = product.id
                    except UserError as exc:
                        result[slot + '_product_error'] = str(exc)[:160]
                return result
            if name == 'get_historical_line_patterns':
                if set(args) != {'query'} or not isinstance(args['query'], str):
                    raise ValueError('Indica query.')
                return self.get_historical_line_patterns(args['query'])
            if set(args) != {'profile_id'} or type(args['profile_id']) is not int:
                raise ValueError('Se requiere profile_id entero.')
            profile = Profile.search([('id', '=', args['profile_id']), ('active', '=', True),
                                      ('company_id', 'in', [False, self.company.id])], limit=1)
            if not profile:
                raise ValueError('Regla inaccesible en esta compañía.')
            # Tool execution must never override an explicit user's choice
            # of itemized billing merely because the model ignored that request.
            latest = self.env['sale.ai.message'].search([
                ('session_id', '=', self.session.id), ('role', '=', 'user')
            ], order='id desc', limit=1)
            from .sale_ai_profiles import _plain
            intent = _plain(latest.content or '')
            import re
            if re.search(r'\b(desglosad[oa]s?|cada material|partidas? independientes|'
                         r'por separado|lineas? separadas)\b', intent):
                raise ValueError('El usuario ha solicitado partidas desglosadas, no una regla global.')
            with self.env.cr.savepoint():
                return self.session._ai_compose_profile(profile, explicit=True)
        except AccessError:
            raise
        except (ValueError, TypeError, UserError, ValidationError) as exc:
            return {'error': str(exc)[:230]}

    def get_historical_line_patterns(self, query):
        # One compact company/ACL filtered shortlist. Never the 5 most recent
        # indiscriminately and never raw notes, amounts or customer information.
        if not self.history_limit:
            return {'results': [], 'message': 'Históricos deshabilitados.'}
        from .sale_ai_read_tools import _keywords
        if len(query) < 5 or len(query) > 90:
            raise ValueError('Especifica un tipo de trabajo concreto.')
        words = _keywords(query)[:5]
        if not words:
            return {'results': [], 'message': 'Consulta demasiado genérica.'}
        # Candidate search restricted by company, current user's read ACL.
        orders = self.env['sale.order'].search(self._order_domain(),
            order='date_order desc, id desc', limit=70)
        candidates = []
        for order in orders:
            if not order.order_line:
                continue
            representation = ' '.join([order.client_order_ref or '', order.origin or ''] +
                [(line.product_id.display_name or '')[:80] for line in order.order_line[:18]])
            import unicodedata
            plain = unicodedata.normalize('NFKD', representation.lower())
            plain = ''.join(c for c in plain if not unicodedata.combining(c))
            score = sum(1 for word in words if word in plain)
            if not score:
                continue
            structure = []
            for line in order.order_line.sorted(key=lambda l: (l.sequence, l.id))[:12]:
                structure.append({'type': line.display_type or 'product',
                    'product_ref': (line.product_id.default_code or '')[:26] if line.product_id else ''})
            candidates.append((score, order.id, structure))
        candidates.sort(key=lambda result: (-result[0], -result[1]))
        return self._bounded_result({'source': 'odoo.sale.order',
            'results': [{'order_id': ident, 'line_pattern': pattern}
                for score, ident, pattern in candidates[:min(5, self.history_limit)]],
            'note': 'Patrones de líneas, no precios actuales. Muestra acotada de presupuestos recientes.'})
