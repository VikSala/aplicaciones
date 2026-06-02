from odoo import http
from odoo.http import request


class AtajController(http.Controller):

    @http.route('/get_custom_apps', type='json', auth='user')
    def get_custom_apps(self):
        shortcuts = request.env['ataj.shortcut'].get_shortcuts_for_user()
        return [
            {
                'id': s.id,
                'name': s.name,
                'url': s.url,
                'visibility': s.visibility,
                'img': s.image.decode('utf-8') if s.image else False,
            }
            for s in shortcuts
        ]
