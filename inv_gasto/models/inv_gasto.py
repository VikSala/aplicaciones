from odoo import models, fields, api, _
from odoo.exceptions import UserError

class InvGasto(models.Model):
    _name = 'inv.gasto'
    _description = 'Gastos de Inventario'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'analytic.mixin']

    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True, default='/')
    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    project_id = fields.Many2one('project.project', string='Proyecto', required=True)
    analytic_account_id = fields.Many2one('account.analytic.account', related='project_id.account_id', store=True, readonly=True)
    date = fields.Date(string='Fecha', default=fields.Date.context_today)
    journal_id = fields.Many2one('account.journal', string='Diario Contable', required=True, 
                                 domain="[('type', '=', 'general'), ('company_id', '=', company_id)]")
    
    line_ids = fields.One2many('inv.gasto.line', 'gasto_id', string='Líneas')
    account_move_id = fields.Many2one('account.move', string="Asiento Contable", readonly=True, copy=False)
    state = fields.Selection([('draft', 'Borrador'), ('confirmed', 'Confirmado')], default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('inv.gasto') or '/'
        return super().create(vals_list)

    def action_confirm(self):
        for record in self:
            if not record.line_ids:
                raise UserError(_("No hay líneas de producto."))
            record._create_stock_moves()
            record._create_account_move()
            record._create_manual_analytic_lines()
            record.state = 'confirmed'

    def action_cancel(self):
        """ Método a prueba de fallos para cancelar gastos nuevos y antiguos """
        for record in self:
            # --- 1. REVERTIR STOCK ---
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', record.company_id.id)], limit=1)
            location_src = warehouse.lot_stock_id
            location_dest = self.env['stock.location'].search([('usage', '=', 'inventory'), ('company_id', '=', record.company_id.id)], limit=1)
            
            for line in record.line_ids:
                # Devolvemos la cantidad real al stock disponible sumando en positivo
                self.env['stock.quant'].sudo()._update_available_quantity(
                    line.product_id, location_src, line.quantity
                )
                # Creamos el registro del movimiento inverso en estado 'Hecho'
                self.env['stock.move'].sudo().create({
                    'name': f"Devolución de Gasto: {record.name}",
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': line.product_id.uom_id.id,
                    'location_id': location_dest.id if location_dest else self.env.ref('stock.stock_location_inventory').id,
                    'location_dest_id': location_src.id,
                    'company_id': record.company_id.id,
                    'state': 'done',
                })

            # --- 2. BORRAR ASIENTO CONTABLE ---
            # Busca por ID (registros nuevos) o por la referencia en el asiento (registros viejos)
            move_to_cancel = record.account_move_id or self.env['account.move'].search([('ref', '=', record.name)], limit=1)
            if move_to_cancel:
                # Rompemos conciliaciones por seguridad antes de borrar
                if move_to_cancel.line_ids:
                    move_to_cancel.line_ids.remove_move_reconcile()
                move_to_cancel.button_draft()
                move_to_cancel.button_cancel()
                move_to_cancel.with_context(force_delete=True).unlink()
                record.account_move_id = False

            # --- 3. ELIMINAR GASTO DEL TABLERO DEL PROYECTO (Líneas analíticas) ---
            # Busca usando la referencia (nuevos) o buscando por el nombre que le daba el código viejo
            analytic_lines = self.env['account.analytic.line'].search([('ref', '=', record.name)])
            if not analytic_lines:
                for line in record.line_ids:
                    analytic_lines |= self.env['account.analytic.line'].search([
                        ('name', '=', f"Gasto: {line.product_id.name}"),
                        ('date', '=', record.date)
                    ])
            
            if analytic_lines:
                analytic_lines.unlink()

            # --- 4. DEVOLVER A BORRADOR ---
            record.state = 'draft'

    def _create_stock_moves(self):
        location_dest = self.env['stock.location'].search([('usage', '=', 'inventory'), ('company_id', '=', self.company_id.id)], limit=1)
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)], limit=1)
        location_src = warehouse.lot_stock_id
        
        for line in self.line_ids:
            self.env['stock.quant'].sudo()._update_available_quantity(line.product_id, location_src, -line.quantity)
            move = self.env['stock.move'].sudo().create({
                'name': f"Gasto: {self.name}",
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.product_id.uom_id.id,
                'location_id': location_src.id,
                'location_dest_id': location_dest.id,
                'company_id': self.company_id.id,
                'state': 'done',
            })
            line.stock_move_id = move.id

    def _create_account_move(self):
        for record in self:
            lineas = []
            total = sum(record.line_ids.mapped('subtotal'))
            for line in record.line_ids:
                cuenta = line.product_id.property_account_expense_id or line.product_id.categ_id.property_account_expense_categ_id
                lineas.append((0, 0, {'name': f"Gasto: {line.product_id.name}", 'account_id': cuenta.id, 'debit': line.subtotal, 'credit': 0.0}))
            
            account_exist = self.env['account.account'].search([('code', '=', '300001')], limit=1)
            lineas.append((0, 0, {'name': f"Contrapartida {record.name}", 'account_id': account_exist.id, 'debit': 0.0, 'credit': total}))
            
            move = self.env['account.move'].create({
                'move_type': 'entry', 'journal_id': record.journal_id.id, 'date': record.date, 'ref': record.name,
                'line_ids': lineas,
            })
            move.action_post()
            record.account_move_id = move.id

    def _create_manual_analytic_lines(self):
        for record in self:
            for line in record.line_ids:
                self.env['account.analytic.line'].create({
                    'name': f"Gasto: {line.product_id.name}",
                    'account_id': record.analytic_account_id.id,
                    'date': record.date,
                    'amount': -line.subtotal,
                    'ref': record.name,
                    'company_id': record.company_id.id,
                })