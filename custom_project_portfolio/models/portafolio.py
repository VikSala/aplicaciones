from odoo import models, fields


class ProjectPortfolioCategory(models.Model):
    _name = 'project.portfolio.category'
    _description = 'Categoría de Portfolio'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Nombre', required=True)
    color = fields.Char(string='Color (hex)', default='#6c757d')


class ProjectPortfolioImage(models.Model):
    _name = 'project.portfolio.image'
    _description = 'Portfolio Image'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    project_id = fields.Many2one(
        'project.project',
        string='Proyecto',
        required=True,
        ondelete='cascade'
    )
    name = fields.Char(string='Nombre')
    image = fields.Binary(string='Imagen')


class ProjectProject(models.Model):
    _inherit = 'project.project'

    is_published_portfolio = fields.Boolean(string='Publicado')
    portfolio_title = fields.Char(string='Título')
    portfolio_description = fields.Html(string='Descripción')
    portfolio_category_id = fields.Many2one(
        'project.portfolio.category',
        string='Categoría',
        ondelete='set null'
    )
    portfolio_image_ids = fields.One2many(
        'project.portfolio.image',
        'project_id',
        string='Imágenes'
    )
