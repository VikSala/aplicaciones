import shutil, logging
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)


def post_init_hook(env):
    print(f"Checking for 'dwebp' tool...")
    if not shutil.which('dwebp'):
        _logger.error("The 'dwebp' tool is required to use this app. Install it using 'sudo apt install webp'." )
        raise UserError(
            "The 'dwebp' tool is required to use this app. Install it using 'sudo apt install webp'."
        )
