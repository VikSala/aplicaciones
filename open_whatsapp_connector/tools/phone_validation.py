import logging

from odoo.addons.phone_validation.tools import phone_validation

_logger = logging.getLogger(__name__)


def wa_phone_format(env, number, country=None, force_format='E164'):
    """Format a phone number for WhatsApp (E.164 without the + prefix).

    :param env: Odoo environment
    :param number: phone number string
    :param country: res.country record (optional)
    :param force_format: phonenumbers format (default E164)
    :return: formatted number without '+' prefix, or False
    """
    if not number:
        return False
    if not country:
        country = env.company.country_id
    try:
        formatted = phone_validation.phone_format(
            number,
            country.code if country else False,
            country.phone_code if country else False,
            force_format=force_format,
            raise_exception=False,
        )
        if formatted:
            return formatted.lstrip('+')
    except Exception:
        _logger.debug("Failed to format phone number %s", number)
    return False
