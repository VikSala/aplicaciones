from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import AccessDenied


class ResUsers(models.Model):
    _inherit = "res.users"

    login_attempt_count = fields.Integer(default=0)
    is_login_blocked = fields.Boolean(default=False)
    login_blocked_until = fields.Datetime()

    def reset_login_attempts(self):
        """Reset the lock state for the user(s)."""
        self.sudo().write({
            "login_attempt_count": 0,
            "is_login_blocked": False,
            "login_blocked_until": False,
        })

    def _check_credentials(self, credential, user_agent_env):
        """Extend Odoo 18 credential checking with temporary lockout.

        Important Odoo 18 detail:
        - During an interactive login, ``self`` is the user record.
        - During RPC/session credential checks (``res.users.check``), Odoo calls
          ``_check_credentials`` on an empty ``res.users`` recordset and the
          actual user is available as ``self.env.user``.

        Therefore this override must NOT call ``self.ensure_one()``.
        """
        user = self if len(self) == 1 else self.env.user

        max_attempts = int(
            self.env["ir.config_parameter"].sudo().get_param(
                "login_attempt_security.max_attempts", 3
            )
        )
        block_minutes = int(
            self.env["ir.config_parameter"].sudo().get_param(
                "login_attempt_security.block_minutes", 10
            )
        )

        # Avoid invalid configuration values disabling the login unexpectedly.
        max_attempts = max(max_attempts, 1)
        block_minutes = max(block_minutes, 1)

        if user.is_login_blocked:
            if (
                user.login_blocked_until
                and user.login_blocked_until > fields.Datetime.now()
            ):
                raise AccessDenied(
                    f"Account temporarily locked for {block_minutes} min"
                )
            user.reset_login_attempts()

        try:
            result = super()._check_credentials(credential, user_agent_env)
        except AccessDenied:
            # Calculate first, then write. The original module read the field
            # again after write(), which could block one attempt too early.
            new_attempt_count = user.login_attempt_count + 1
            vals = {"login_attempt_count": new_attempt_count}

            if new_attempt_count >= max_attempts:
                vals.update({
                    "is_login_blocked": True,
                    "login_blocked_until": (
                        fields.Datetime.now()
                        + timedelta(minutes=block_minutes)
                    ),
                })

            user.sudo().write(vals)

            # AccessDenied normally causes the surrounding transaction to roll
            # back. Keep the original module's intent: persist the failed-attempt
            # counter before re-raising the authentication error.
            self.env.cr.commit()
            raise

        # Odoo calls this method for RPC credential validation too. Avoid an
        # unnecessary write on every successful RPC call when there is nothing
        # to reset.
        if (
            user.login_attempt_count
            or user.is_login_blocked
            or user.login_blocked_until
        ):
            user.reset_login_attempts()

        return result
