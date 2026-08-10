from odoo import models, fields
from odoo.exceptions import AccessDenied
from datetime import timedelta


class ResUsers(models.Model):
    _inherit = "res.users"

    login_attempt_count = fields.Integer(default=0)
    is_login_blocked = fields.Boolean(default=False)
    login_blocked_until = fields.Datetime()

    def reset_login_attempts(self):
        self.sudo().write({
            "login_attempt_count": 0,
            "is_login_blocked": False,
            "login_blocked_until": False,
        })

    def _check_credentials(self, password, user_agent_env):
        self.ensure_one()
        max_attempts = int(self.env["ir.config_parameter"].sudo().get_param("login_attempt_security.max_attempts", 3))
        block_minutes = int(
            self.env["ir.config_parameter"].sudo().get_param("login_attempt_security.block_minutes", 10))

        if self.is_login_blocked:
            if (self.login_blocked_until
                    and self.login_blocked_until > fields.Datetime.now()
            ):
                raise AccessDenied(f"Account temporarily locked for {block_minutes} min")
            else:
                self.reset_login_attempts()

        try:
            result = super()._check_credentials(password, user_agent_env)

            self.reset_login_attempts()
            return result

        except AccessDenied:

            self.sudo().write({
                "login_attempt_count": self.login_attempt_count + 1
            })

            if self.login_attempt_count + 1 >= max_attempts:
                self.sudo().write({
                    "is_login_blocked": True,
                    "login_blocked_until": fields.Datetime.now()
                                           + timedelta(minutes=block_minutes),
                })

            self.env.cr.commit()

            raise
