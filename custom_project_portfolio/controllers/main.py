from odoo import http
from odoo.http import request


class PortfolioController(http.Controller):

    @http.route('/portfolio', type='http', auth='public', website=True)
    def portfolio(self, category_id=None, **kw):

        domain = [('is_published_portfolio', '=', True)]

        categories = request.env['project.portfolio.category'].sudo().search([])

        if category_id:
            domain.append(('portfolio_category_id', '=', int(category_id)))

        projects = request.env['project.project'].sudo().search(domain)

        return request.render(
            'custom_project_portfolio.portfolio_template_grid',
            {
                'projects': projects,
                'categories': categories,
                'active_category_id': int(category_id) if category_id else None,
            }
        )
