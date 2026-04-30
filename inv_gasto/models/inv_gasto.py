from odoo import models, fields, api, _
from odoo.exceptions import UserError

class InvGasto(models.Model):
    _name = 'inv.gasto'
    _description = 'Gastos de Inventario'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'analytic.mixin']

    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True, default='/')
    
    # NUEVO: Campo de compañía añadido para evitar el KeyError
    company_id = fields.Many2one(
        'res.company', 
        string='Compañía', 
        required=True, 
        default=lambda self: self.env.company
    )
    
    project_id = fields.Many2one('project.project', string='Proyecto', required=True)
    analytic_account_id = fields.Many2one(
        'account.analytic.account', 
        related='project_id.account_id', 
        store=True, 
        readonly=True
    )
    date = fields.Date(string='Fecha', default=fields.Date.context_today)
    
    journal_id = fields.Many2one(
        'account.journal', 
        string='Diario Contable', 
        required=True, 
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self.env['account.journal'].search([
            ('type', '=', 'general'), 
            ('company_id', '=', self.env.company.id)
        ], limit=1)
    )
    
    line_ids = fields.One2many('inv.gasto.line', 'gasto_id', string='Líneas')
    state = fields.Selection([
        ('draft', 'Borrador'), 
        ('confirmed', 'Confirmado')
    ], default='draft', tracking=True)

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
            
            # 1. Movimiento de Stock
            record._create_stock_moves()
            
            # 2. Asiento en Facturación (Sin analítica para evitar duplicados en tablero)
            record._create_account_move()
            
            # 3. Reflejo Manual en Rentabilidad
            record._create_manual_analytic_lines()
            
            record.state = 'confirmed'

    def _create_stock_moves(self):
        """
        Resta el stock real inmediatamente usando el método oficial de Odoo.
        Evita el error de 'creación de cuanto restringida'.
        """
        # Ubicación de salida (Ajuste de Inventario / Gasto)
        location_dest = self.env['stock.location'].search([
            ('usage', '=', 'inventory'),
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        
        # Ubicación de origen (Física)
        warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        location_src = warehouse.lot_stock_id

        if not location_dest:
            raise UserError("No se encontró ubicación de Inventario.")

        for line in self.line_ids:
            # MÉTODO SEGURO: Actualizar cantidad disponible directamente
            # Ponemos la cantidad en negativo para que reste del stock real
            self.env['stock.quant'].sudo()._update_available_quantity(
                line.product_id, 
                location_src, 
                -line.quantity
            )

            # Creamos el registro del movimiento en estado 'Hecho' solo para historial[cite: 1]
            # Al poner state='done' y picked=True, Odoo sabe que ya se ejecutó[cite: 1]
            move = self.env['stock.move'].sudo().create({
                'name': f"Gasto Directo: {self.name}",
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.product_id.uom_id.id,
                'location_id': location_src.id,
                'location_dest_id': location_dest.id,
                'company_id': self.company_id.id,
                'state': 'done',
                'is_inventory': True,
                'picked': True,
            })
            
            # Vinculamos para trazabilidad[cite: 1]
            line.stock_move_id = move.id

    def _create_account_move(self):
        for record in self:
            lineas = []
            total = sum(record.line_ids.mapped('subtotal'))
            for line in record.line_ids:
                cuenta = line.product_id.property_account_expense_id or \
                         line.product_id.categ_id.property_account_expense_categ_id
                
                lineas.append((0, 0, {
                    'name': f"Gasto: {line.product_id.name}",
                    'account_id': cuenta.id,
                    'debit': line.subtotal,
                    'credit': 0.0,
                }))
            
            account_existencias = self.env['account.account'].search([
                ('code', '=', '300001'),
            ], limit=1)

            if not account_existencias:
                raise UserError("No se encontró la cuenta 300001 (Existencias)")

            lineas.append((0, 0, {
                'name': f"Contrapartida: {record.name}",
                'account_id': account_existencias.id,
                'debit': 0.0,
                'credit': total,
            }))

            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': record.journal_id.id,
                'date': record.date,
                'ref': record.name,
                'company_id': record.company_id.id,
                'line_ids': lineas,
            })
            move.action_post()

    def _create_manual_analytic_lines(self):
        for record in self:
            dist = record.analytic_distribution or {str(record.analytic_account_id.id): 100.0}
            for line in record.line_ids:
                coste = line.subtotal
                for account_id, percentage in dist.items():
                    self.env['account.analytic.line'].create({
                        'name': f"Gasto: {line.product_id.name}",
                        'account_id': int(account_id),
                        'date': record.date,
                        'amount': -(coste * (percentage / 100.0)),
                        'unit_amount': line.quantity,
                        'product_id': line.product_id.id,
                        'product_uom_id': line.product_id.uom_id.id,
                        'company_id': record.company_id.id,
                        'category': 'other',
                    })

class InvGastoLine(models.Model):
    _name = 'inv.gasto.line'
    _description = 'Línea de Gasto'

    gasto_id = fields.Many2one('inv.gasto', ondelete='cascade')
    product_id = fields.Many2one('product.product', string="Producto", required=True)
    quantity = fields.Float(string="Cantidad", default=1.0)
    price_unit = fields.Float(string="Precio", related='product_id.standard_price', readonly=False)
    subtotal = fields.Float(string="Subtotal", compute='_compute_subtotal')
    stock_move_id = fields.Many2one('stock.move', string="Movimiento")

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit