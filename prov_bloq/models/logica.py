from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    config_purchase_provider_id = fields.Many2one(
        'res.partner', 
        string="Proveedor Predeterminado",
        config_parameter='prov_bloq.purchase_provider_id'
    )

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def write(self, vals):
        # 1. Obtenemos la ID configurada en ajustes
        config_id = self.env['ir.config_parameter'].sudo().get_param('prov_bloq.purchase_provider_id')
        
        if config_id:
            for partner in self:
                # 2. Si el contacto que se intenta editar es el configurado
                # y el usuario NO es administrador (group_system)
                if partner.id == int(config_id) and not self.env.user.has_group('base.group_system'):
                    raise UserError(_("Seguridad: No tienes permisos para modificar los datos de este proveedor específico."))
        
        return super(ResPartner, self).write(vals)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    is_admin_user = fields.Boolean(compute='_compute_is_admin_user')

    @api.depends_context('uid')
    def _compute_is_admin_user(self):
        for order in self:
            order.is_admin_user = self.env.user.has_group('base.group_system')

    @api.model
    def default_get(self, fields_list):
        res = super(PurchaseOrder, self).default_get(fields_list)
        provider_id = self.env['ir.config_parameter'].sudo().get_param('prov_bloq.purchase_provider_id')
        if provider_id and 'partner_id' in fields_list:
            res['partner_id'] = int(provider_id)
        return res