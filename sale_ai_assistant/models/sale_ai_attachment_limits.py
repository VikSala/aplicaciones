"""Company-scoped, operator-controlled attachment limits.

Zero disables that *application* check. It cannot override upstream request,
proxy, image-decoder or AI provider limits. Defaults preserve 11.16 behavior.
"""

# field name -> (stored parameter, default, unit, description)
ATTACHMENT_LIMITS = {
    'max_files': ('max_files', 5, 'files'),
    'total_mb': ('total_mb', 30, 'MiB'),
    'image_mb': ('image_mb', 10, 'MiB'),
    'pdf_mb': ('pdf_mb', 5, 'MiB'),
    'txt_mb': ('txt_mb', 5, 'MiB'),
    'mp3_mb': ('mp3_mb', 25, 'MiB'),
    'pdf_pages': ('pdf_pages', 10, 'pages'),
    'image_megapixels': ('image_megapixels', 25, 'MP'),
    'image_edge_px': ('image_edge_px', 1800, 'px'),
    'pdf_edge_px': ('pdf_edge_px', 1600, 'px'),
    'text_chars': ('text_chars', 50000, 'chars'),
    'transcription_response_kb': ('transcription_response_kb', 1024, 'KiB'),
}
PARAM_PREFIX = 'sale_ai_assistant.attachment.'


def get_attachment_limits(env, company_id):
    """Only a saved nonnegative integer is accepted; 0 means unlimited."""
    params = env['ir.config_parameter'].sudo()
    result = {}
    for name, (slug, default, _unit) in ATTACHMENT_LIMITS.items():
        value = params.get_param('%s%s.%d' % (PARAM_PREFIX, slug, company_id))
        try:
            parsed = default if value in (None, '', False) else int(value)
            result[name] = parsed if parsed >= 0 else default
        except (TypeError, ValueError, OverflowError):
            result[name] = default
    return result


def bytes_for_mb(mb):
    return mb * 1024 * 1024


def over_limit(value, limit):
    return limit > 0 and value > limit
