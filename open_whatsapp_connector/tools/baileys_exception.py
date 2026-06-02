from odoo.exceptions import UserError


class BaileysError(UserError):
    """Exception for WhatsApp sidecar communication errors."""

    def __init__(self, failure_type='unknown', message=''):
        self.failure_type = failure_type
        self.error_message = message
        super().__init__(message)
