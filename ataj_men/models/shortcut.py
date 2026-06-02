from odoo import models, fields, api
from odoo.exceptions import AccessError


class AtajShortcut(models.Model):
    _name = 'ataj.shortcut'
    _description = 'Atajos de Menú'

    name = fields.Char(string='Nombre', required=True)
    url = fields.Char(string='URL de Redirección', required=True)
    image = fields.Binary(string='Foto/Icono')
    sequence = fields.Integer(default=10)

    visibility = fields.Selection([
        ('global',   'Global (todos los usuarios)'),
        ('job',      'Por puesto de trabajo'),
        ('admin',    'Solo administradores'),
    ], string='Visibilidad', default='job', required=True)

    job_ids = fields.Many2many(
        'hr.job',
        string='Puestos de trabajo',
        help='Puestos que verán este atajo. Solo aplica si la visibilidad es "Por puesto de trabajo".',
    )

    # Campo auxiliar UI
    current_user_is_admin = fields.Boolean(
        compute='_compute_current_user_is_admin',
    )

    menu_id = fields.Many2one(
        'ir.ui.menu', string='Menú Creado', readonly=True, ondelete='cascade')
    action_id = fields.Many2one(
        'ir.actions.act_url', string='Acción Creada', readonly=True, ondelete='cascade')

    # ── Computed ───────────────────────────────────────────────────────────────

    @api.depends_context('uid')
    def _compute_current_user_is_admin(self):
        is_admin = self.env.user.has_group('base.group_system')
        for rec in self:
            rec.current_user_is_admin = is_admin

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _is_admin(self):
        return self.env.user.has_group('base.group_system')

    def _get_menu_groups(self, rec):
        """
        Devuelve los grupos (res.groups) que deben ver el menú según la visibilidad.
        - global: ninguno → todos lo ven (sin restricción de grupo en ir.ui.menu)
        - admin:  base.group_system
        - job:    grupos vinculados a los puestos de trabajo seleccionados
                  (hr.job tiene campo groups_id en versiones con portal, pero en
                   Odoo base no. Usamos base.group_user como fallback y controlamos
                   la visibilidad real desde el dominio del modelo.)
        """
        if rec.visibility == 'global':
            return []
        if rec.visibility == 'admin':
            return [self.env.ref('base.group_system')]
        # job: el menú se crea sin restricción de grupo; la visibilidad real
        # se gestiona en get_shortcuts_for_user() y en las ir.rules de lectura.
        return []

    def _create_menu_and_action(self, rec):
        action = self.env['ir.actions.act_url'].sudo().create({
            'name': rec.name,
            'url': rec.url,
            'target': 'new',
        })
        menu_vals = {
            'name': rec.name,
            'web_icon_data': rec.image,
            'action': f'ir.actions.act_url,{action.id}',
            'parent_id': False,
            'sequence': rec.sequence,
        }
        groups = self._get_menu_groups(rec)
        if groups:
            menu_vals['groups_id'] = [(6, 0, [g.id for g in groups])]
        menu = self.env['ir.ui.menu'].sudo().create(menu_vals)
        return action, menu

    # ── ORM ────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_admin():
            raise AccessError('Solo los administradores pueden crear atajos.')

        records = super().create(vals_list)
        for rec in records:
            action, menu = self._create_menu_and_action(rec)
            rec.sudo().write({'menu_id': menu.id, 'action_id': action.id})
        return records

    def write(self, vals):
        if not self._is_admin():
            raise AccessError('Solo los administradores pueden editar atajos.')

        res = super().write(vals)

        for rec in self:
            # Actualizar menú existente
            if rec.menu_id:
                menu_vals = {}
                if 'name' in vals:
                    menu_vals['name'] = vals['name']
                if 'image' in vals:
                    menu_vals['web_icon_data'] = vals['image']
                if 'sequence' in vals:
                    menu_vals['sequence'] = vals['sequence']
                # Recalcular grupos si cambia visibilidad o puestos
                if 'visibility' in vals or 'job_ids' in vals:
                    groups = self._get_menu_groups(rec)
                    menu_vals['groups_id'] = [(6, 0, [g.id for g in groups])]
                if menu_vals:
                    rec.menu_id.sudo().write(menu_vals)

            if rec.action_id and 'url' in vals:
                rec.action_id.sudo().write({'url': vals['url']})

        return res

    def unlink(self):
        if not self._is_admin():
            raise AccessError('Solo los administradores pueden eliminar atajos.')
        return super().unlink()

    # ── Consulta para el controlador ──────────────────────────────────────────

    @api.model
    def get_shortcuts_for_user(self):
        """
        Devuelve los atajos visibles para el usuario actual:
          - global: todos
          - admin: solo si el usuario es administrador
          - job: solo si el usuario tiene algún empleado con ese puesto de trabajo
        """
        uid = self.env.uid
        is_admin = self.env.user.has_group('base.group_system')

        # Puestos del usuario actual (puede tener varios contratos/empleados)
        employee_jobs = self.env['hr.employee'].sudo().search(
            [('user_id', '=', uid)]
        ).mapped('job_id')

        domain = ['|', ('visibility', '=', 'global'), '|']

        if is_admin:
            domain += [('visibility', '=', 'admin')]
        else:
            domain += [('visibility', '=', 'admin'), ('id', '=', -1)]  # nunca

        if employee_jobs:
            domain += [('visibility', '=', 'job'),
                       ('job_ids', 'in', employee_jobs.ids)]
        else:
            domain += [('id', '=', -1)]  # sin puesto → no ve ningún atajo de tipo job

        return self.sudo().search(domain, order='sequence asc')
