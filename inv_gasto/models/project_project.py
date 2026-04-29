from odoo import models, api

class Project(models.Model):
    _inherit = 'project.project'

    @api.model
    def _get_profitability_labels(self):
        labels = super()._get_profitability_labels()
        # Cambiamos la etiqueta de 'vendor_bills' para que los costes de inv.gasto 
        # aparezcan bajo 'Operaciones varias' en el tablero
        if 'vendor_bills' in labels:
            labels['vendor_bills'] = 'Operaciones varias'
        return labels

    def action_view_project_vendor_bills(self):
        self.ensure_one()
        # Al hacer clic en el tablero, abrimos los asientos de diario vinculados
        return {
            'name': 'Operaciones varias',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('move_type', '=', 'entry'), 
                ('line_ids.analytic_distribution', 'has_key', str(self.account_id.id))
            ],
            'context': {'default_move_type': 'entry'},
        }