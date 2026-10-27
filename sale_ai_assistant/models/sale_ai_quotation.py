"""Phase 6: explicit, atomic creation of a DRAFT sale.order from a chat draft.

The LLM never calls this. Only an authenticated Sales Administrator can
request preflight and confirm it from OWL, after reviewing the exact snapshot.
"""
import hashlib
import json
import math

from odoo import api, models, _
from odoo.exceptions import AccessError, UserError


class SaleAIQuotationSession(models.Model):
    _inherit = "sale.ai.session"

    def _quote_comment_values(self, draft):
        """Use the installation's custom Sales field, never the customer reference."""
        comments = draft.description or ''
        if not comments:
            return {}
        field = self.env['sale.order']._fields.get('x_comentarios')
        if not field or field.type not in ('char', 'text') or (field.compute and not field.inverse):
            raise UserError(_('No se pueden guardar los comentarios: Ventas necesita el campo x_comentarios de tipo texto editable.'))
        if field.type == 'char' and field.size and len(comments) > field.size:
            raise UserError(_('Los comentarios superan la longitud admitida por x_comentarios.'))
        return {'x_comentarios': comments}

    def _quote_preflight(self):
        self.ensure_one()
        self._ensure_can_edit_draft()
        if not self.env.user.has_group("sales_team.group_sale_manager"):
            raise AccessError(_("Solo los administradores de Ventas pueden crear presupuestos con IA."))
        if self.user_id != self.env.user or self.company_id != self.env.company:
            raise AccessError(_("Solo puedes finalizar tu conversación de la compañía activa."))

        draft = self.draft_id
        if not draft:
            raise UserError(_("No se ha encontrado el borrador de la conversación."))
        if not draft.partner_id:
            raise UserError(_("Asigna un cliente real de Odoo al borrador antes de crear el presupuesto."))
        self._quote_comment_values(draft)
        partner = draft.partner_id
        if not partner.exists() or (partner.company_id and partner.company_id != self.company_id):
            raise UserError(_("El cliente no pertenece a la compañía activa."))
        lines = draft.line_ids.sorted(key=lambda line: (line.sequence, line.id))
        if not lines or not any(line.line_kind == "product" for line in lines):
            raise UserError(_("Añade al menos una partida comercial, además de las notas o secciones."))
        if len(lines) > 40:
            raise UserError(_("El borrador supera el límite de 40 líneas."))

        commercial_pricelist = draft.pricelist_id or partner.property_product_pricelist
        if not commercial_pricelist:
            raise UserError(_("No hay tarifa disponible para el cliente. Revisa su configuración en Odoo."))
        if commercial_pricelist.company_id and commercial_pricelist.company_id != self.company_id:
            raise UserError(_("La tarifa no pertenece a esta compañía."))
        if commercial_pricelist.currency_id != draft.currency_id:
            raise UserError(_(
                "La moneda del borrador (%s) no coincide con la tarifa del cliente (%s). "
                "Ajusta la moneda o tarifa antes de crear el presupuesto; no se convertirán importes automáticamente."
            ) % (draft.currency_id.name, commercial_pricelist.currency_id.name))

        warnings = [_('La fiscalidad, los totales finales y las condiciones comerciales serán calculados por Odoo y deben revisarse.')]
        if draft.assumptions:
            warnings.append(_('Quedan comprobaciones pendientes: %s') % draft.assumptions[:400])
        if any(line.line_kind == "product" and not line.product_id for line in lines):
            warnings.append(_('Hay partidas sin producto del catálogo: comprueba su asociación a un producto antes de facturar o entregar.'))
        if any(line.line_kind == "product" and line.price_source in ("estimate", "external", "history") for line in lines):
            warnings.append(_('Hay precios estimados o basados en referencias, no precios definitivos de venta.'))
        for line in lines:
            if line.product_id:
                if (not line.product_id.exists() or not line.product_id.sale_ok or
                    (line.product_id.company_id and line.product_id.company_id != self.company_id)):
                    raise UserError(_('Producto no disponible para la venta en la compañía activa: %s') % line.name[:100])
            if line.line_kind == 'product':
                if (not math.isfinite(line.product_uom_qty) or line.product_uom_qty <= 0 or
                    not math.isfinite(line.price_unit) or line.price_unit < 0 or
                    not math.isfinite(line.discount) or not 0 <= line.discount <= 100):
                    raise UserError(_('La cantidad, el precio o descuento de una partida no son válidos: %s') % line.name[:100])
                if line.product_uom_id and line.product_id and line.product_uom_id.category_id != line.product_id.uom_id.category_id:
                    raise UserError(_('La unidad de medida no corresponde a la categoría del producto: %s') % line.name[:100])
            elif line.line_kind not in ('line_note', 'line_section'):
                raise UserError(_('Tipo de línea inválido en el borrador.'))

        # Incorporate full data affecting the operation; any edit requires a new preflight.
        snapshot = {
            'session': self.id,
            'company': self.company_id.id,
            'customer': partner.id,
            'pricelist': commercial_pricelist.id,
            'currency': draft.currency_id.id,
            'description': draft.description or '',
            'assumptions': draft.assumptions or '',
            'lines': [
                [line.id, line.sequence, line.line_kind, line.product_id.id or 0,
                 line.product_uom_id.id or 0, line.name, line.product_uom_qty,
                 line.price_unit, line.discount, line.price_source, line.price_evidence or '']
                for line in lines
            ],
        }
        signature = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
        return {
            'signature': signature,
            'partner': partner.display_name,
            'pricelist': commercial_pricelist.display_name,
            'currency': draft.currency_id.name,
            'amount_untaxed_estimate': draft.amount_untaxed_estimate,
            'line_count': len(lines),
            'product_count': len(lines.filtered(lambda line: line.line_kind == 'product')),
            'warnings': warnings,
            '_partner': partner,
            '_pricelist': commercial_pricelist,
            '_lines': lines,
            '_draft': draft,
        }

    @api.model
    def assistant_panel_quotation_preflight(self, session_id):
        session = self._panel_find(session_id)
        preflight = session._quote_preflight()
        result = {key: value for key, value in preflight.items() if not key.startswith('_')}
        # Advisory-only review: a provider error must never make a valid draft
        # impossible to review or create. The creation endpoint does NOT call IA.
        result["warnings"] = list(result["warnings"]) + session._ai_review_draft_before_creation()
        return result

    @api.model
    def assistant_panel_create_quotation(self, session_id, signature, confirmed=False):
        # Never called by any LLM tool; requires an explicit UI confirmation.
        if confirmed is not True or not isinstance(signature, str) or len(signature) != 64:
            raise UserError(_('Debes revisar el resumen y confirmar expresamente la creación.'))
        session = self._panel_find(session_id)
        # Lock across tabs/requests before reading draft or writing sale.order.
        session._ai_lock_session()
        preflight = session._quote_preflight()
        if signature != preflight['signature']:
            raise UserError(_('El borrador o los datos comerciales han cambiado. Revisa la vista previa y vuelve a confirmar.'))
        if session.sale_order_id:
            raise UserError(_('Esta conversación ya tiene un presupuesto asociado.'))

        values = {
            'partner_id': preflight['_partner'].id,
            'company_id': session.company_id.id,
            'user_id': self.env.uid,
            'pricelist_id': preflight['_pricelist'].id,
            'origin': _('Asistente IA · Conversación %s') % session.id,
        }
        values.update(session._quote_comment_values(preflight['_draft']))
        # Preserve line order, names and explicit chosen prices. Odoo computes
        # invoice/shipping partners, taxes and amounts from customer/fiscal position.
        commands = []
        for line in preflight['_lines']:
            if line.line_kind in ('line_note', 'line_section'):
                line_values = {
                    'sequence': line.sequence,
                    'display_type': line.line_kind,
                    'name': line.name,
                }
            else:
                line_values = {
                    'sequence': line.sequence,
                    'name': line.name,
                    'product_uom_qty': line.product_uom_qty,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                }
                if line.product_id:
                    line_values['product_id'] = line.product_id.id
                    line_values['product_uom'] = (line.product_uom_id or line.product_id.uom_id).id
                elif line.product_uom_id:
                    line_values['product_uom'] = line.product_uom_id.id
            commands.append((0, 0, line_values))
        values['order_line'] = commands
        order = self.env['sale.order'].with_company(session.company_id).create(values)
        if order.state != 'draft' or order.company_id != session.company_id:
            raise UserError(_('El pedido generado no está en estado presupuesto. Se cancela la operación.'))
        if len(order.order_line) != len(preflight['_lines']):
            raise UserError(_('La creación de líneas no coincide con el borrador. Se cancela la operación.'))
        session._complete_with_order(order)
        return {
            'sale_order_id': order.id,
            'sale_order_name': order.name,
            'state': session.state,
            'amount_untaxed': order.amount_untaxed,
            'amount_tax': order.amount_tax,
            'amount_total': order.amount_total,
        }
