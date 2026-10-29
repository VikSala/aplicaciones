"""Safely load/update an existing sale.order through a provisional AI draft.

Loading and chatting never modify the real order. Only a Sales Administrator
can explicitly commit a reviewed, signed patch, regardless of order state.
Concurrent edits are detected *under row locks*. An explicit 'keep_mine'
override affects conflicting editable fields only.
"""
import hashlib
import json

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


EDIT_LINE_FIELDS = (
    'sequence', 'kind', 'name', 'product_id', 'uom_id', 'quantity', 'price_unit', 'discount',
)
EDIT_HEADER_FIELDS = ('partner_id', 'pricelist_id', 'comments')
LINE_LABELS = {
    'sequence': 'orden', 'kind': 'tipo', 'name': 'descripción', 'product_id': 'producto',
    'uom_id': 'unidad', 'quantity': 'cantidad', 'price_unit': 'precio', 'discount': 'descuento',
}
HEADER_LABELS = {'partner_id': 'cliente', 'pricelist_id': 'tarifa', 'comments': 'comentarios'}


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()


def _timestamp(value):
    return fields.Datetime.to_string(value) if value else ''


class SaleAIQuotationEditing(models.Model):
    _inherit = 'sale.ai.session'

    def _edit_access(self):
        self.ensure_one()
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise AccessError(_('Solo los administradores de Ventas pueden editar presupuestos con IA.'))
        if self.user_id != self.env.user or self.company_id != self.env.company:
            raise AccessError(_('La conversación debe ser tuya y de la compañía activa.'))
        self._ensure_can_edit_draft()

    def _edit_order(self):
        self.ensure_one()
        self._edit_access()
        order = self.edit_order_id
        if not order or not order.exists() or order.company_id != self.company_id:
            raise UserError(_('No se encuentra el presupuesto de esta compañía.'))
        return order

    def _edit_comments(self, order):
        field = order._fields.get('x_comentarios')
        if not field or field.type not in ('char', 'text'):
            return ''
        return order.x_comentarios or ''

    def _edit_snapshot(self, order):
        """Serialize the managed fields, plus modification stamps for warnings.

        Extra Odoo fields are NOT part of our patch, so they remain untouched.
        """
        rows = []
        for line in order.order_line.sorted(key=lambda l: (l.sequence, l.id)):
            rows.append({
                'id': line.id,
                'sequence': line.sequence,
                'kind': line.display_type or 'product',
                'name': line.name or '',
                'product_id': line.product_id.id or False,
                'uom_id': line.product_uom.id or False,
                'quantity': line.product_uom_qty if not line.display_type else 0,
                'price_unit': line.price_unit if not line.display_type else 0,
                'discount': line.discount if not line.display_type else 0,
                'stamp': _timestamp(line.write_date),
            })
        return {
            'order_id': order.id,
            'state': order.state,
            'stamp': _timestamp(order.write_date),
            'currency_id': order.currency_id.id or False,
            'partner_id': order.partner_id.id or False,
            'pricelist_id': order.pricelist_id.id or False,
            'comments': self._edit_comments(order),
            'lines': rows,
        }

    def _edit_original(self):
        self.ensure_one()
        if not self.edit_baseline_json:
            raise UserError(_('No se encuentra la versión original del presupuesto. Vuelve a cargarlo.'))
        try:
            original = json.loads(self.edit_baseline_json)
        except (ValueError, TypeError):
            raise UserError(_('La instantánea original está dañada. Vuelve a cargar el presupuesto.'))
        if original.get('order_id') != self.edit_order_id.id:
            raise UserError(_('La instantánea no corresponde al presupuesto de esta sesión.'))
        return original

    def _edit_seed_draft(self, order):
        """Only provisional records are created/deleted; sale.order is read-only."""
        self.ensure_one()
        draft = self.draft_id
        # Clear old undo history, otherwise Ctrl+Z could restore a former baseline.
        draft.change_ids.unlink()
        draft.line_ids.unlink()
        draft.write({
            'partner_id': order.partner_id.id,
            'pricelist_id': order.pricelist_id.id or False,
            'currency_id': order.currency_id.id,
            'description': self._edit_comments(order),
            'assumptions': False,
            'estimate_details': False,
            'undo_snapshot': False,
            'undo_after_fingerprint': False,
        })
        vals = []
        for line in order.order_line.sorted(key=lambda l: (l.sequence, l.id)):
            vals.append({
                'draft_id': draft.id,
                'source_sale_line_id': line.id,
                'sequence': line.sequence,
                'line_kind': line.display_type or 'product',
                'name': line.name or '/',
                'product_id': line.product_id.id or False,
                'product_uom_id': line.product_uom.id or False,
                'product_uom_qty': line.product_uom_qty if not line.display_type else 0,
                'price_unit': line.price_unit if not line.display_type else 0,
                'discount': line.discount if not line.display_type else 0,
                'price_source': 'user',
                'price_evidence': _('Precio existente en el presupuesto %s') % order.name,
            })
        if vals:
            self.env['sale.ai.draft.line'].with_context(sale_ai_internal_edit=True).create(vals)

    @api.model
    def assistant_panel_load_quotation(self, order_id, current_session_id=False,
                                       archive_current=False, discard_current=False):
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise AccessError(_('Solo los administradores de Ventas pueden cargar presupuestos.'))
        if type(order_id) is not int or order_id <= 0:
            raise ValidationError(_('Identificador de presupuesto incorrecto.'))
        if type(archive_current) is not bool or type(discard_current) is not bool or (archive_current and discard_current):
            raise ValidationError(_('Selecciona archivar o descartar, pero no ambas opciones.'))
        order = self.env['sale.order'].search([
            ('id', '=', order_id), ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not order:
            raise UserError(_('No se encuentra el presupuesto en la compañía activa.'))
        current = self._panel_find(current_session_id) if current_session_id else self.browse()
        selected_model_id = current.model_id.id if current else self.env.company.sale_ai_model_id.id
        if current:
            if current.state != 'active' or current.sale_order_id:
                raise UserError(_('Solo puedes sustituir tu conversación activa.'))
            current._ai_lock_session()
            has_work = self._panel_session_has_work(current)
            if has_work and not (archive_current or discard_current):
                raise UserError(_('La conversación actual contiene mensajes o cambios. Selecciona Archivar y cargar o Descartar y cargar.'))
            if has_work and archive_current:
                current.action_close()  # Keep the full conversation in History.
            else:
                current.unlink()  # Explicit discard, or a clean loaded baseline.
        session = self.create({
            'name': _('Edición de %s') % order.name,
            'model_id': selected_model_id,
        })
        session.with_context(sale_ai_internal_edit=True).write({
            'edit_order_id': order.id,
            'edit_baseline_json': json.dumps(session._edit_snapshot(order), ensure_ascii=False),
        })
        session._edit_seed_draft(order)
        return self._panel_details(session)

    def _edit_plan(self, original, current):
        """Build a field-level patch and list concurrent conflicts.

        Preserves all columns that the assistant does not explicitly edit and
        externally added lines. A conflicting deletion is allowed only after an
        explicit 'keep_mine' confirmation.
        """
        draft = self.draft_id
        wanted_header = {
            'partner_id': draft.partner_id.id or False,
            'pricelist_id': draft.pricelist_id.id or False,
            'comments': draft.description or '',
        }
        header_patch = {
            k: v for k, v in wanted_header.items()
            if v != original.get(k)
        }
        conflict_labels = []
        conflict_details = []
        external_labels = []

        def conflict(label, old, remote, local):
            conflict_labels.append(label)
            # Keep the dialog bounded: technical descriptions can be very long.
            limit = lambda value: str(value if value is not None else '')[:100]
            conflict_details.append('%s · anterior: %s · ahora Odoo: %s · tu propuesta: %s' % (
                label, limit(old), limit(remote), limit(local),
            ))
        for key, value in header_patch.items():
            if current.get(key) != original.get(key) and current.get(key) != value:
                conflict(_('Cabecera: %s') % HEADER_LABELS[key], original.get(key), current.get(key), value)
        for key in EDIT_HEADER_FIELDS:
            if current.get(key) != original.get(key):
                external_labels.append(_('Cabecera: %s') % HEADER_LABELS[key])

        baseline = {entry['id']: entry for entry in original['lines']}
        now = {entry['id']: entry for entry in current['lines']}
        proposed = {}
        added = []
        for draft_line in draft.line_ids.sorted(key=lambda l: (l.sequence, l.id)):
            source_id = draft_line.source_sale_line_id or False
            item = {
                'sequence': draft_line.sequence,
                'kind': draft_line.line_kind,
                'name': draft_line.name or '',
                'product_id': draft_line.product_id.id or False,
                'uom_id': draft_line.product_uom_id.id or False,
                'quantity': draft_line.product_uom_qty if draft_line.line_kind == 'product' else 0,
                'price_unit': draft_line.price_unit if draft_line.line_kind == 'product' else 0,
                'discount': draft_line.discount if draft_line.line_kind == 'product' else 0,
            }
            if source_id:
                if source_id not in baseline or source_id in proposed:
                    raise UserError(_('Una línea de origen no pertenece al presupuesto o está repetida. Vuelve a cargarlo.'))
                proposed[source_id] = item
            else:
                added.append(item)
        edits = {}
        removed = []
        for source_id, before in baseline.items():
            actual = now.get(source_id)
            if source_id not in proposed:
                if actual:
                    removed.append(source_id)
                    if (any(actual[k] != before[k] for k in EDIT_LINE_FIELDS) or
                            actual.get('stamp') != before.get('stamp')):
                        conflict(_('Eliminar línea %s, modificada en Odoo') % source_id, before['name'], actual['name'], 'ELIMINAR')
                continue
            desired = proposed[source_id]
            patch = {key: desired[key] for key in EDIT_LINE_FIELDS if desired[key] != before[key]}
            if not patch:
                continue
            if not actual:
                conflict(_('Línea %s eliminada en Odoo; recarga necesaria') % source_id, before['name'], 'ELIMINADA', desired['name'])
                continue
            for key, value in patch.items():
                if actual[key] != before[key] and actual[key] != value:
                    conflict(_('Línea %s: %s') % (source_id, LINE_LABELS[key]), before[key], actual[key], value)
            edits[source_id] = patch
        for source_id, before in baseline.items():
            actual = now.get(source_id)
            if not actual:
                external_labels.append(_('Línea %s eliminada') % source_id)
            elif any(actual[key] != before[key] for key in EDIT_LINE_FIELDS):
                external_labels.append(_('Línea %s modificada') % source_id)
            elif actual.get('stamp') != before.get('stamp'):
                external_labels.append(_('Línea %s: otros campos modificados') % source_id)
        for source_id in now.keys() - baseline.keys():
            external_labels.append(_('Línea %s añadida') % source_id)
        # State changes are relevant concurrent changes, never a reason to
        # prevent editing. Older sessions may have a baseline without 'state'.
        if 'state' in original and current.get('state') != original['state']:
            external_labels.append(_('Estado del documento cambiado en Odoo: %s → %s') % (
                original['state'], current.get('state') or '-'))
        if (current.get('stamp') != original.get('stamp') and
                not external_labels and not any(current.get(k) != original.get(k) for k in EDIT_HEADER_FIELDS)):
            external_labels.append(_('Otros datos del presupuesto modificados en Odoo'))
        return {
            'header': header_patch, 'edits': edits, 'removed': removed, 'added': added,
            'conflicts': conflict_labels, 'conflict_details': conflict_details, 'external_changes': external_labels,
            'changes_count': len(header_patch) + len(edits) + len(removed) + len(added),
            'missing_lines': [sid for sid in proposed if sid in baseline and sid not in now and
                              any(proposed[sid][k] != baseline[sid][k] for k in EDIT_LINE_FIELDS)],
        }

    def _edit_preflight(self):
        self._edit_access()
        order = self._edit_order()
        # Reuse the existing commercial validation but never run creation RPC.
        # Creation's `_quote_preflight` deliberately rejects edit sessions.
        # In editing mode we invoke it with the temporary context flag instead.
        original = self._edit_original()
        current = self._edit_snapshot(order)
        if current.get('currency_id') != original.get('currency_id'):
            raise UserError(_('La moneda del presupuesto cambió en Odoo. Recarga el presupuesto antes de actualizarlo.'))
        planned = self._edit_plan(original, current)
        if planned['missing_lines']:
            raise UserError(_('Una línea que quieres modificar ya no existe en Odoo. Recarga el presupuesto antes de continuar.'))
        if not planned['changes_count']:
            raise UserError(_('No has modificado ningún dato comercial respecto al presupuesto cargado.'))
        # Checks existing commercial validation including partner, catalog,
        # prices, currency and line kinds.
        commercial = self.with_context(sale_ai_edit_validation=True)._quote_preflight()
        signature = _digest({
            'edit_order': order.id,
            'origin': original,
            'draft': commercial['signature'],
            'sources': [(l.id, l.source_sale_line_id) for l in commercial['_lines']],
        })
        return {
            'order': order, 'original': original, 'current': current,
            'planned': planned, 'signature': signature,
            'review': commercial,
            'current_signature': _digest(current),
        }

    @api.model
    def assistant_panel_update_preflight(self, session_id):
        session = self._panel_find(session_id)
        check = session._edit_preflight()
        planned = check['planned']
        return {
            'signature': check['signature'],
            'current_signature': check['current_signature'],
            'sale_order_id': check['order'].id,
            'sale_order_name': check['order'].name,
            'sale_order_state': check['order'].state,
            'sale_order_state_label': dict(
                check['order'].fields_get(['state'], ['selection'])['state']['selection']
            ).get(check['order'].state, check['order'].state),
            'partner': check['review']['partner'],
            'line_count': check['review']['line_count'],
            'amount_untaxed_estimate': check['review']['amount_untaxed_estimate'],
            'currency': check['review']['currency'],
            'changes_count': planned['changes_count'],
            'conflicts': planned['conflicts'],
            'conflict_details': planned['conflict_details'],
            'external_changes': planned['external_changes'],
            'warnings': check['review']['warnings'],
        }

    @staticmethod
    def _edit_sale_line_vals(item):
        if item['kind'] in ('line_section', 'line_note'):
            return {'sequence': item['sequence'], 'display_type': item['kind'], 'name': item['name']}
        values = {
            'sequence': item['sequence'], 'name': item['name'],
            'product_id': item['product_id'] or False,
            'product_uom': item['uom_id'] or False,
            'product_uom_qty': item['quantity'], 'price_unit': item['price_unit'],
            'discount': item['discount'],
        }
        return values

    @api.model
    def assistant_panel_update_quotation(self, session_id, signature, current_signature, confirmed=False, keep_mine=False):
        if confirmed is not True or type(signature) is not str or len(signature) != 64:
            raise UserError(_('Debes revisar y confirmar expresamente la actualización.'))
        if type(current_signature) is not str or len(current_signature) != 64:
            raise UserError(_('Falta la firma de los datos consultados en Odoo.'))
        if keep_mine not in (True, False):
            raise ValidationError(_('Resolución de conflictos incorrecta.'))
        session = self._panel_find(session_id)
        session._edit_access()
        session._ai_lock_session()
        order = session._edit_order()
        # Transaction-scoped locks prevent a race between rechecking and writing.
        self.env.cr.execute('SELECT id FROM sale_order WHERE id = %s FOR UPDATE', [order.id])
        self.env.cr.execute('SELECT id FROM sale_order_line WHERE order_id = %s ORDER BY id FOR UPDATE', [order.id])
        order.invalidate_recordset()
        order.order_line.invalidate_recordset()
        check = session._edit_preflight()
        if signature != check['signature'] or current_signature != check['current_signature']:
            raise UserError(_('El borrador o el presupuesto real cambiaron después de la revisión. Vuelve a pulsar Actualizar presupuesto.'))
        plan = check['planned']
        if plan['conflicts'] and keep_mine is not True:
            raise UserError(_('Existen cambios de otra persona que requieren una confirmación expresa.'))
        if plan['missing_lines']:
            raise UserError(_('Una línea que quieres modificar fue eliminada por otra persona. Recarga el presupuesto.'))

        header = {}
        if 'partner_id' in plan['header']:
            header['partner_id'] = plan['header']['partner_id']
        if 'pricelist_id' in plan['header']:
            header['pricelist_id'] = plan['header']['pricelist_id']
        if 'comments' in plan['header']:
            header.update(session._quote_comment_values(check['review']['_draft']))
            if not header.get('x_comentarios'):
                # Clearing an existing custom comment must also be explicit.
                if order._fields.get('x_comentarios'):
                    header['x_comentarios'] = False
        if header:
            order.write(header)
        lines_model = self.env['sale.order.line']
        # Existing lines are modified in place; unrelated columns are retained.
        for source_id, patch in plan['edits'].items():
            real = lines_model.browse(source_id).exists()
            if not real or real.order_id != order:
                raise UserError(_('La línea %s ya no corresponde al presupuesto.') % source_id)
            if 'kind' in patch and (patch['kind'] != (real.display_type or 'product')):
                # Changing a display line into a product and vice versa is not
                # guaranteed to be supported by the Odoo SQL constraints.
                raise UserError(_('No se puede convertir el tipo de una línea existente. Elimínala en la vista previa y añade otra.'))
            allowed_map = {
                'sequence': 'sequence', 'name': 'name', 'product_id': 'product_id',
                'uom_id': 'product_uom', 'quantity': 'product_uom_qty',
                'price_unit': 'price_unit', 'discount': 'discount',
            }
            changes = {allowed_map[k]: v for k, v in patch.items() if k in allowed_map}
            if changes:
                real.write(changes)
        if plan['removed']:
            lines_model.browse(plan['removed']).filtered(lambda l: l.order_id == order).unlink()
        for line in plan['added']:
            vals = session._edit_sale_line_vals(line)
            vals['order_id'] = order.id
            lines_model.create(vals)
        order.invalidate_recordset()
        order.order_line.invalidate_recordset()
        # The saved version becomes the NEW origin. Never apply subsequent
        # changes against an outdated version or keep an obsolete undo stack.
        session._edit_seed_draft(order)
        session.with_context(sale_ai_internal_edit=True).write({
            'edit_baseline_json': json.dumps(session._edit_snapshot(order), ensure_ascii=False),
        })
        return {
            'sale_order_id': order.id,
            'sale_order_name': order.name,
            'amount_total': order.amount_total,
            'session': self._panel_details(session),
        }
