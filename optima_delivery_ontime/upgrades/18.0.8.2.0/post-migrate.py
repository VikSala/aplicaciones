from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    carriers = env["delivery.carrier"].with_context(active_test=False).search([("delivery_type", "=", "ontime")])
    confirmed_url = "https://preproduccion.mensaglobal.com/api"
    for carrier in carriers:
        vals = {}
        if not carrier.ontime_production_base_url:
            vals["ontime_production_base_url"] = carrier.ontime_preproduction_base_url or confirmed_url
        if carrier.ontime_environment != "production":
            vals["ontime_environment"] = "production"
        if vals:
            carrier.write(vals)
