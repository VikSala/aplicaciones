from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

TECHNICAL_PREFIX = '__custom_override__'


class CustomReportModifier(models.Model):
    _name = 'custom.report.modifier'
    _description = 'Motor de Herencias Dinámicas'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre', required=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    parent_view_id = fields.Many2one(
        'ir.ui.view',
        string='Vista padre',
        required=True,
        domain=[('type', '=', 'qweb')],
        ondelete='restrict',
    )
    xpath_code = fields.Text(
        string='Código XPath',
        required=True,
        help='Bloque <xpath expr="..." position="...">...</xpath> completo.',
    )
    active = fields.Boolean(string='Activo', default=True)
    notes = fields.Text(string='Notas')
    technical_view_id = fields.Many2one(
        'ir.ui.view',
        string='Vista técnica generada',
        readonly=True,
        copy=False,
        ondelete='set null',
    )
    state = fields.Selection(
        [('draft', 'Borrador'), ('active', 'Activo'), ('error', 'Error')],
        string='Estado',
        default='draft',
        readonly=True,
    )
    last_error = fields.Text(string='Último error', readonly=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _technical_view_key(self):
        self.ensure_one()
        safe = self.name[:40].replace(' ', '_').replace('.', '_')
        return f'custom_report_modifier.{TECHNICAL_PREFIX}{self.id}_{safe}'

    def _technical_view_name(self):
        self.ensure_one()
        safe = self.name[:40].replace(' ', '_').replace('.', '_')
        return f'{TECHNICAL_PREFIX}{self.id}_{safe}'

    # ------------------------------------------------------------------
    # ORM Hooks
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.active:
                rec._sync_technical_view()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('xpath_code', 'active', 'parent_view_id', 'name')):
            for rec in self:
                rec._sync_technical_view()
        return res

    def unlink(self):
        for rec in self:
            rec._delete_technical_view()
        return super().unlink()

    # ------------------------------------------------------------------
    # Sincronización con ir.ui.view
    # ------------------------------------------------------------------

    def _sync_technical_view(self):
        self.ensure_one()

        if not self.active:
            self._deactivate_technical_view()
            return

        IrView = self.env['ir.ui.view'].sudo()
        arch = self.xpath_code.strip()

        view_vals = {
            'name': self._technical_view_name(),
            'key': self._technical_view_key(),
            'type': 'qweb',
            'inherit_id': self.parent_view_id.id,
            'arch_db': arch,
            'active': True,
            'priority': 99,
        }

        try:
            if self.technical_view_id:
                self.technical_view_id.sudo().write(view_vals)
                self._write_state('active', None)
            else:
                new_view = IrView.create(view_vals)
                # SQL directo para evitar re-disparar el hook write()
                self.env.cr.execute(
                    "UPDATE custom_report_modifier "
                    "SET technical_view_id = %s, state = 'active', last_error = NULL "
                    "WHERE id = %s",
                    (new_view.id, self.id)
                )
                self.invalidate_recordset()
        except Exception as e:
            _logger.error('CustomReportModifier [%s]: %s', self.id, e)
            self._write_state('error', str(e))
            raise UserError(
                _('XPath inválido o error en la herencia.\n\nDetalle:\n%s') % str(e)
            )

    def _write_state(self, state, error):
        self.env.cr.execute(
            "UPDATE custom_report_modifier "
            "SET state = %s, last_error = %s "
            "WHERE id = %s",
            (state, error, self.id)
        )
        self.invalidate_recordset()

    def _deactivate_technical_view(self):
        self.ensure_one()
        if self.technical_view_id:
            try:
                self.technical_view_id.sudo().write({'active': False})
            except Exception as e:
                _logger.warning('No se pudo desactivar vista técnica %s: %s',
                                self.technical_view_id.id, e)
        self._write_state('draft', None)

    def _delete_technical_view(self):
        self.ensure_one()
        if self.technical_view_id:
            try:
                self.technical_view_id.sudo().unlink()
            except Exception as e:
                _logger.warning('No se pudo eliminar vista técnica %s: %s',
                                self.technical_view_id.id, e)

    # ------------------------------------------------------------------
    # Botones del formulario
    # ------------------------------------------------------------------

    def action_activate(self):
        for rec in self:
            self.env.cr.execute(
                "UPDATE custom_report_modifier SET active = true WHERE id = %s",
                (rec.id,)
            )
            rec.invalidate_recordset()
            rec._sync_technical_view()

    def action_deactivate(self):
        for rec in self:
            rec._deactivate_technical_view()
            self.env.cr.execute(
                "UPDATE custom_report_modifier SET active = false WHERE id = %s",
                (rec.id,)
            )
            rec.invalidate_recordset()

    def action_test_xpath(self):
        """Valida el XPath con dry-run: crea en savepoint y siempre hace rollback."""
        self.ensure_one()
        arch = self.xpath_code.strip()
        error_msg = None

        try:
            with self.env.cr.savepoint():
                self.env['ir.ui.view'].sudo().create({
                    'name': '__dry_run_test__',
                    'key': 'custom_report_modifier.__dry_run_test__',
                    'type': 'qweb',
                    'inherit_id': self.parent_view_id.id,
                    'arch_db': arch,
                    'active': False,
                    'priority': 99,
                })
                # Forzar rollback lanzando excepción controlada
                raise Exception('__rollback__')
        except Exception as e:
            if '__rollback__' not in str(e):
                error_msg = str(e)

        if error_msg:
            raise UserError(_('XPath inválido:\n\n%s') % error_msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('XPath válido'),
                'message': _('Odoo acepta la herencia correctamente.'),
                'type': 'success',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # Botón de pánico
    # ------------------------------------------------------------------

    @api.model
    def action_panic_deactivate_all(self):
        records = self.search([('active', '=', True)])
        count = len(records)
        for rec in records:
            rec._deactivate_technical_view()
        if records:
            self.env.cr.execute(
                "UPDATE custom_report_modifier "
                "SET active = false, state = 'draft' "
                "WHERE id = ANY(%s)",
                (records.ids,)
            )
            records.invalidate_recordset()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pánico activado'),
                'message': _('%d herencias desactivadas.') % count,
                'type': 'warning',
                'sticky': True,
            },
        }
