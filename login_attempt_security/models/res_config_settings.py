from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    login_max_attempts = fields.Integer(
        string="Maximum Login Attempts",
        config_parameter="login_attempt_security.max_attempts",
        default=3,
    )

    login_block_minutes = fields.Integer(
        string="Block Duration (Minutes)",
        config_parameter="login_attempt_security.block_minutes",
        default=10,
    )