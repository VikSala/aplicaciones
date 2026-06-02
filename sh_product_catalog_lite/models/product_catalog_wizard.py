from odoo import models, fields, api, _
import io
import csv
import base64

class ProductCatalogWizard(models.TransientModel):
    _name = 'product.catalog.wizard'
    _description = 'Asistente de Catálogo'

    export_type = fields.Selection([
        ('pdf', 'PDF'),
        ('excel', 'Excel (CSV)')
    ], string='Formato de Exportación', default='pdf', required=True)

    def action_export(self):
        active_ids = self._context.get('active_ids', [])
        if not active_ids:
            return {'type': 'ir.actions.act_window_close'}
            
        products = self.env['product.template'].browse(active_ids)
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        if self.export_type == 'pdf':
            return self.env.ref('sh_product_catalog_lite.action_report_catalog_pdf').report_action(products.ids)
        
        else:
            # EXCEL (CSV)
            output = io.StringIO()
            # Usamos punto y coma (;) para que Excel lo abra en columnas automáticamente en España
            writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            
            # Cabecera
            writer.writerow(['Referencia', 'Nombre', 'Precio', 'Cat. eCommerce', 'Stock Real', 'URL Tienda'])
            
            for prod in products:
                eco_categories = ", ".join(prod.public_categ_ids.mapped('name'))
                product_url = "%s/shop/product/%s" % (base_url, prod.id)
                
                writer.writerow([
                    prod.default_code or '',
                    prod.name or '',
                    prod.list_price,
                    eco_categories,
                    prod.qty_available,
                    product_url
                ])
            
            # LA SOLUCIÓN PARA LOS ACENTOS:
            # Añadimos el BOM de UTF-8 (\ufeff) al principio del archivo
            content = output.getvalue()
            bom = u'\ufeff'
            csv_data = (bom + content).encode('utf-8')
            
            attachment = self.env['ir.attachment'].create({
                'name': 'Catalogo_Productos.csv',
                'type': 'binary',
                'datas': base64.b64encode(csv_data),
                'mimetype': 'text/csv',
            })
            
            return {
                'type': 'ir.actions.act_url',
                'url': '/web/content/%s?download=true' % attachment.id,
                'target': 'new',
            }