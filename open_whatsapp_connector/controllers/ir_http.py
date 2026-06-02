"""Resolve the target database for inbound webhook requests.

Stock ``Request._get_session_and_dbname`` only resolves the database from the
session cookie or, if there is exactly one database listable, from the monodb
fallback. The sidecar process posts to
``/open_whatsapp_connector/webhook/incoming?db=<name>`` with no cookie and on a
multi-database server, so the request hits ``_serve_nodb`` and returns 404
before the controller is ever dispatched.

Monkey-patch ``_get_session_and_dbname`` to fall back to the ``db`` query
string (matches the ``callback_url`` produced by ``owa.account``) and to the
``X-Odoo-Database`` header (matches what ``sidecar/src/services/session-manager.ts``
sends). The addon is then self-contained and does not depend on ``driver_login``
or any other module providing the same shim.
"""
import logging

from odoo.http import db_list

_logger = logging.getLogger(__name__)

_original_get_session_and_dbname = None


def _patched_get_session_and_dbname(self):
    session, dbname = _original_get_session_and_dbname(self)
    if dbname:
        return session, dbname

    candidate = (
        self.httprequest.args.get('db')
        or self.httprequest.headers.get('X-Odoo-Database')
    )
    if not candidate:
        return session, dbname

    try:
        host = self.httprequest.environ.get('HTTP_HOST', '')
        if candidate in db_list(force=True, host=host):
            session.db = candidate
            return session, candidate
    except Exception:
        _logger.debug("open_whatsapp_connector: db_list failed while resolving %r",
                      candidate, exc_info=True)
    return session, dbname


def _apply_patch():
    global _original_get_session_and_dbname
    from odoo.http import Request
    if _original_get_session_and_dbname is not None:
        return
    _original_get_session_and_dbname = Request._get_session_and_dbname
    Request._get_session_and_dbname = _patched_get_session_and_dbname
    _logger.info(
        "open_whatsapp_connector: patched Request._get_session_and_dbname "
        "to honor ?db= query string and X-Odoo-Database header"
    )


_apply_patch()
