from odoo import models, fields, api
from odoo.exceptions import UserError

class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_inst_usuario = fields.Char(string='Usuario Web (Email)')
    x_inst_password = fields.Char(string='Contraseña Web')

    def action_force_sync_access(self):
        for partner in self:
            if not partner.x_inst_usuario or not partner.x_inst_password:
                raise UserError("Debes rellenar el Usuario y la Contraseña antes de sincronizar.")
            
            # Buscamos si este contacto tiene un usuario de sistema
            user = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)], limit=1)
            
            if user:
                # Si existe, le forzamos los datos
                user.write({
                    'login': partner.x_inst_usuario,
                    'password': partner.x_inst_password,
                    'email': partner.x_inst_usuario
                })
            else:
                raise UserError("Este contacto no tiene un usuario creado. Ve a 'Acción > Gestionar acceso al portal' primero.")
        
        return {
            'effect': {
                'fadeout': 'slow',
                'message': '¡Acceso sincronizado correctamente!',
                'type': 'rainbow_man',
            }
        }