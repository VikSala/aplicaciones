from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # False = la dirección de facturación coincide con los datos personales.
    # Se expresa al revés para que los contactos existentes queden, por defecto,
    # con el checkbox "Mismos datos de facturación" activado tras actualizar.
    portal_separate_billing = fields.Boolean(
        string="Usar una dirección de facturación distinta en el portal",
        default=False,
        copy=False,
    )
