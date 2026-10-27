"""Company-aware quotation structures, distinct from estimating materials/labour.

A company may override a shared rule. Real products are resolved by explicit IDs
or *unique* exact default_code, never fabricated or matched by fuzzy names.
"""
import json
import re
import unicodedata

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


def _plain(text):
    chars = unicodedata.normalize('NFKD', (text or '').lower())
    return ''.join(c for c in chars if not unicodedata.combining(c))


class SaleAIQuotationProfile(models.Model):
    _name = 'sale.ai.quotation.profile'
    _description = 'Regla comercial de composición de presupuestos IA'
    _order = 'priority desc, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Compañía (vacío = modelo compartido)',
                                 default=lambda self: self.env.company, index=True)
    priority = fields.Integer(default=50)
    code = fields.Char(required=True, index=True, help='Identificador técnico de la regla.')
    keywords = fields.Text(required=True, string='Expresiones que identifican el trabajo',
                           help='Una expresión por línea; se requieren coincidencias descriptivas.')
    structure = fields.Selection([
        ('main_note_global', 'Producto principal + nota técnica + partida global'),
    ], required=True, default='main_note_global')
    main_product_id = fields.Many2one('product.product', string='Producto principal',
                                      domain="[('sale_ok','=',True)]")
    global_product_id = fields.Many2one('product.product', string='Producto importe global',
                                        domain="[('sale_ok','=',True)]")
    main_product_code = fields.Char(default='IE', string='Referencia interna principal',
                                    help='Se usa SOLO si existe exactamente un producto vendible con esa referencia.')
    global_product_code = fields.Char(default='TLMEF', string='Referencia interna de la partida global',
                                      help='Se usa SOLO si existe exactamente un producto vendible con esa referencia.')
    global_line_label = fields.Char(default='TOTAL', string='Descripción de importe global')
    main_line_label = fields.Char(string='Descripción principal (opcional)',
                                  help='Vacío: se utiliza la descripción de venta del producto.')
    notes = fields.Text(string='Observaciones de la regla')

    @api.constrains('main_product_id', 'global_product_id', 'company_id')
    def _check_products_company(self):
        for rule in self:
            for product in (rule.main_product_id, rule.global_product_id):
                if product and (not product.sale_ok or (
                        product.company_id and product.company_id != rule.company_id)):
                    raise ValidationError(_(
                        'Los productos de una regla deben ser vendibles y pertenecer a la compañía de la regla. '
                        'En reglas compartidas usa referencias internas o crea una regla por compañía.'))

    @api.constrains('keywords', 'code')
    def _check_keywords(self):
        for rule in self:
            if not rule.code or len(rule.code) > 64 or not re.fullmatch(r'[a-z0-9_\-]+', rule.code):
                raise ValidationError(_('El código debe contener letras minúsculas, números, _ o - (máx. 64).'))
            if len(rule.keywords or '') > 1500:
                raise ValidationError(_('La lista de expresiones es demasiado larga.'))

    @api.model
    def _select_for_text(self, text, company):
        """Select only with a specific lexical match; prefer company overrides.

        Conservative matching: short generic words do not trigger a rule.
        Do not load historical orders to choose a profile blindly.
        """
        plain = _plain(text)[:6000]
        if not plain:
            return self.browse()
        profiles = self.search([
            ('active', '=', True), ('company_id', 'in', [False, company.id]),
        ], order='priority desc, id asc', limit=40)
        scores = []
        for rule in profiles:
            terms = [_plain(term.strip()) for term in (rule.keywords or '').splitlines()]
            matched = [t for t in terms if len(t) >= 7 and t in plain]
            if not matched:
                continue
            # Prefer more specific phrases, then priority; a company override wins ties.
            score = (max(map(len, matched)), len(matched), rule.priority,
                     1 if rule.company_id else 0)
            scores.append((score, rule))
        if not scores:
            return self.browse()
        return sorted(scores, key=lambda item: item[0], reverse=True)[0][1]

    def _resolve_product(self, slot, company):
        self.ensure_one()
        if slot not in ('main', 'global'):
            raise UserError(_('Tipo de producto de regla no válido.'))
        configured = self[slot + '_product_id']
        code = (self[slot + '_product_code'] or '').strip()
        domain = [('sale_ok', '=', True), ('company_id', 'in', [False, company.id])]
        if configured:
            product = self.env['product.product'].with_company(company).search(
                [('id', '=', configured.id)] + domain, limit=1)
            if not product:
                raise UserError(_('El producto %s de la regla no está disponible en esta compañía.') % configured.display_name)
            return product
        if not code:
            raise UserError(_('Configura el producto %s de la regla %s.') % (slot, self.name))
        matches = self.env['product.product'].with_company(company).search(
            [('default_code', '=', code)] + domain, limit=3)
        if len(matches) != 1:
            raise UserError(_(
                'La referencia interna exacta %s debe identificar un único producto vendible en esta compañía. '
                'Encontrados: %s. Configura el producto en la regla comercial.') % (code, len(matches)))
        return matches

    def action_company_copy(self):
        self.ensure_one()
        if self.company_id == self.env.company:
            return True
        if self.company_id:
            raise UserError(_('Solo se puede personalizar una regla compartida para la compañía actual.'))
        existing = self.search([
            ('code', '=', self.code), ('company_id', '=', self.env.company.id),
        ], limit=1)
        target = existing or self.copy({'company_id': self.env.company.id})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': target.id,
                'view_mode': 'form', 'target': 'current'}


class SaleAIQuotationProfileDraft(models.Model):
    _inherit = 'sale.ai.draft'

    quotation_profile_id = fields.Many2one('sale.ai.quotation.profile',
        string='Regla comercial aplicada', copy=False, readonly=True)


class SaleAIQuotationProfileLine(models.Model):
    _inherit = 'sale.ai.draft.line'

    commercial_role = fields.Selection([
        ('other', 'Sin rol'), ('main', 'Producto principal'),
        ('technical', 'Nota técnica'), ('global', 'Partida global'),
    ], default='other', required=True, copy=False, string='Papel en composición comercial')


class SaleAIQuotationProfileSession(models.Model):
    _inherit = 'sale.ai.session'

    def _ai_compose_profile(self, profile, explicit=False, target_total=None):
        """Idempotent composition of THREE commercial lines.

        No sale.order write; all input calculations retained as internal notes.
        Requires a specific matching profile and exact catalog products. On an
        unsuccessful composition the ORM caller should wrap this in a savepoint.
        """
        self.ensure_one()
        self._ensure_can_edit_draft()
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise AccessError(_('Solo administradores de Ventas pueden aplicar reglas.'))
        profile.ensure_one()
        if not profile.active or (profile.company_id and profile.company_id != self.company_id):
            raise UserError(_('Regla comercial no disponible en la compañía activa.'))
        if self.company_id != self.env.company:
            raise AccessError(_('La regla debe aplicarse en la compañía activa.'))
        draft = self.draft_id
        if not draft:
            raise UserError(_('Esta conversación no tiene borrador provisional.'))
        main_product = profile._resolve_product('main', self.company_id)
        global_product = profile._resolve_product('global', self.company_id)
        if main_product == global_product:
            raise UserError(_('El producto principal y el producto de importe global deben ser distintos.'))
        lines = draft.line_ids.sorted(key=lambda l: (l.sequence, l.id))
        existing_roles = {role: lines.filtered(lambda l: l.commercial_role == role)
                          for role in ('main', 'technical', 'global')}
        if any(len(item) > 1 for item in existing_roles.values()):
            raise UserError(_('Existen líneas comerciales duplicadas por rol: revisa el borrador.'))
        unassigned = lines.filtered(lambda l: l.commercial_role == 'other')
        text_notes = [line.name for line in unassigned if line.line_kind == 'line_note']
        existing_note = existing_roles['technical'][:1]
        # Reapplication with no new technical note must preserve the existing one.
        # Never replace a previously accepted technical note merely because
        # the model added a new technical paragraph as a separate note.
        note_parts = ([existing_note.name] if existing_note else []) + text_notes
        note_text = '\n\n'.join(dict.fromkeys(part for part in note_parts if part))
        if not note_text:
            # Do not invent a technical specification that was never provided.
            if explicit:
                raise UserError(_('Primero prepara una nota técnica con los trabajos y materiales incluidos.'))
            return {'applied': False, 'reason': 'Falta nota técnica.'}
        if len(note_text) > 3500:
            raise UserError(_('La nota técnica supera los 3.500 caracteres. Resúmela antes de componer.'))

        before = {
            'description': draft.description or '', 'partner_id': draft.partner_id.id or False,
            'pricelist_id': draft.pricelist_id.id or False, 'currency_id': draft.currency_id.id,
            'assumptions': draft.assumptions or '', 'estimate_details': draft.estimate_details or '',
            'quotation_profile_id': draft.quotation_profile_id.id or False,
            'lines': [dict(id=l.id, kind=l.line_kind, name=l.name,
                           product_id=l.product_id.id or False, uom_id=l.product_uom_id.id or False,
                           quantity=l.product_uom_qty, price_unit=l.price_unit,
                           discount=l.discount, price_source=l.price_source,
                           price_evidence=l.price_evidence or '', sequence=l.sequence,
                           commercial_role=l.commercial_role) for l in lines],
        }
        # If there are already three profile lines, use the global total only.
        # Never add a previous global amount on top of itself.
        previous_global = existing_roles['global'][:1]
        other_product_lines = unassigned.filtered(lambda l: l.line_kind == 'product')
        current_base = (sum(other_product_lines.mapped('amount_estimate')) +
                        (previous_global.amount_estimate if previous_global else 0.0))
        if target_total is not None:
            if not isinstance(target_total, (int, float)) or not 0 <= target_total <= 100000000:
                raise UserError(_('El total global solicitado no es válido.'))
            current_base = target_total
        if current_base < 0:
            raise UserError(_('No se puede componer una propuesta económica negativa.'))
        user_fixed = bool(other_product_lines and len(other_product_lines) == 1 and
                          other_product_lines.price_source == 'user') or bool(
                              not other_product_lines and previous_global and previous_global.price_source == 'user')
        origin = 'user' if (user_fixed or target_total is not None) else 'estimate'

        # Preserve monetary detail privately; compact enough for existing field limits.
        if other_product_lines:
            breakdown = ['Desglose adicional que originó la partida global (orientativo):']
            for line in other_product_lines[:20]:
                breakdown.append('%s: %g × %.2f, descuento %g%% = %.2f %s [%s]' % (
                    line.name.replace('\n', ' ')[:95], line.product_uom_qty,
                    line.price_unit, line.discount, line.amount_estimate,
                    draft.currency_id.name, line.price_source))
            existing_calculation = draft.estimate_details or ''
            new_details = '\n'.join(breakdown)
            if new_details not in existing_calculation:
                combined = (existing_calculation + '\n\n' + new_details).strip()
                draft.write({'estimate_details': combined[-2900:]})

        # Construct/reuse roles. Odoo's sale.order line order is preserved.
        def upsert(role, vals):
            old = existing_roles[role][:1]
            if old:
                normalized = lambda key: old[key].id if key in ('product_id', 'product_uom_id') else old[key]
                if any(normalized(key) != value for key, value in vals.items()):
                    old.write(vals)
                return old
            return self.env['sale.ai.draft.line'].create(dict(vals, draft_id=draft.id,
                                                               commercial_role=role))

        upsert('main', {
            'sequence': 10, 'line_kind': 'product', 'product_id': main_product.id,
            'product_uom_id': main_product.uom_id.id,
            'name': (existing_roles['main'].name if existing_roles['main'] else (
                profile.main_line_label or draft.description or main_product.display_name)),
            'product_uom_qty': 1, 'price_unit': 0, 'discount': 0,
            'price_source': 'user', 'price_evidence': 'Cabecera técnica según regla comercial; importe en la partida global.',
        })
        upsert('technical', {
            'sequence': 20, 'line_kind': 'line_note', 'product_id': False,
            'product_uom_id': False, 'name': note_text, 'product_uom_qty': 0,
            'price_unit': 0, 'discount': 0, 'price_source': 'estimate',
            'price_evidence': '',
        })
        upsert('global', {
            'sequence': 30, 'line_kind': 'product', 'product_id': global_product.id,
            'product_uom_id': global_product.uom_id.id,
            'name': previous_global.name if previous_global else (profile.global_line_label or 'TOTAL'),
            'product_uom_qty': 1, 'price_unit': current_base,
            'discount': 0, 'price_source': origin,
            'price_evidence': 'Importe global de la valoración interna; revisión comercial obligatoria.',
        })
        if unassigned:
            unassigned.unlink()
        draft.write({'quotation_profile_id': profile.id})
        # A repeated application with identical lines must not create a new
        # undo event or modify data again.
        from .sale_ai_draft_tools import SaleAIDraftTools
        tools = SaleAIDraftTools(self)
        if tools._snapshot(draft) == before:
            return {'applied': False, 'reason': 'La estructura comercial ya era correcta.'}
        tools._record_undo(draft, before)
        return {'applied': True, 'profile': profile.name,
                'product_main_id': main_product.id, 'product_global_id': global_product.id,
                'line_count': len(draft.line_ids),
                'amount_untaxed_estimate': draft.amount_untaxed_estimate,
                'note': 'Desglose económico conservado en cálculo interno; venta pendiente de revisión.'}
