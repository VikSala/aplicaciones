# -*- coding: utf-8 -*-

import logging
import math

from odoo import fields, http
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome

_logger = logging.getLogger(__name__)


class LoginPopupAuthSignup(AuthSignupHome):
    """Extiende el alta estándar y añade el login AJAX del popup."""

    PROFESSIONAL_CATEGORY_MAP = {
        "company": "Empresa",
        "self_employed": "Autónomo",
    }

    @http.route(
        "/login_popup/authenticate",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def login_popup_authenticate(self, login=None, password=None, **kw):
        """Autentica sin abandonar la página y devuelve un resultado JSON.

        La autenticación sigue pasando por ``request.session.authenticate`` y,
        por tanto, por ``res.users._check_credentials``. Esto permite que
        módulos como ``login_attempt_security`` sigan contabilizando intentos
        y bloqueando la cuenta normalmente.

        Si ``login_attempt_security`` está instalado, tras un AccessDenied se
        consulta el estado del usuario para informar al popup cuando la cuenta
        ha quedado bloqueada. La integración es opcional: ``login_popup``
        continúa funcionando aunque ese módulo no esté instalado.
        """
        login = (login or "").strip()
        password = password or ""

        if not login or not password:
            return request.make_json_response({
                "success": False,
                "locked": False,
                "message": "Introduce tu correo electrónico y contraseña.",
            })

        credential = {
            "login": login,
            "password": password,
            "type": "password",
        }

        try:
            request.session.authenticate(request.db, credential)
            return request.make_json_response({
                "success": True,
                "locked": False,
            })
        except AccessDenied:
            security_status = self._get_login_security_status(login)
            if security_status["locked"]:
                minutes = security_status["remaining_minutes"]
                minute_label = "minuto" if minutes == 1 else "minutos"
                return request.make_json_response({
                    "success": False,
                    "locked": True,
                    "remaining_minutes": minutes,
                    "message": (
                        "Has superado el número máximo de intentos. "
                        f"Podrás volver a intentarlo en {minutes} {minute_label}."
                    ),
                })

            return request.make_json_response({
                "success": False,
                "locked": False,
                "message": "Correo electrónico o contraseña incorrectos.",
            })
        except Exception:
            _logger.exception("Error inesperado al autenticar desde login_popup")
            return request.make_json_response({
                "success": False,
                "locked": False,
                "message": "No se ha podido iniciar sesión. Inténtalo de nuevo.",
            }, status=500)

    def _get_login_security_status(self, login):
        """Devuelve el bloqueo de ``login_attempt_security`` si está presente.

        No se declara dependencia dura con dicho módulo para conservar la
        compatibilidad del popup como módulo independiente.
        """
        Users = request.env["res.users"].sudo()

        required_fields = {
            "is_login_blocked",
            "login_blocked_until",
        }
        if not required_fields.issubset(Users._fields):
            return {"locked": False, "remaining_minutes": 0}

        user = Users.search(
            Users._get_login_domain(login),
            order=Users._get_login_order(),
            limit=1,
        )
        if not user or not user.is_login_blocked or not user.login_blocked_until:
            return {"locked": False, "remaining_minutes": 0}

        now = fields.Datetime.now()
        if user.login_blocked_until <= now:
            return {"locked": False, "remaining_minutes": 0}

        seconds = (user.login_blocked_until - now).total_seconds()
        remaining_minutes = max(1, math.ceil(seconds / 60.0))
        return {
            "locked": True,
            "remaining_minutes": remaining_minutes,
        }

    @http.route()
    def web_auth_signup(self, *args, **kw):
        # Republicamos la ruta heredada para que Odoo aplique este controlador.
        return super().web_auth_signup(*args, **kw)

    def _signup_with_values(self, token, values):
        """Crea el usuario y, si procede, añade su etiqueta profesional.

        Se replica el pequeño tramo final del flujo estándar de Odoo 18 para
        poder asignar la categoría antes del commit y de la autenticación.
        """
        account_type = (request.params.get("signup_account_type") or "").strip()
        professional_type = (request.params.get("professional_type") or "").strip()

        # Revalidación en servidor: los atributos ``required`` del navegador
        # mejoran la UX, pero no deben ser la única barrera para estos datos.
        if account_type == "particular":
            if not (request.params.get("partner_vat") or "").strip():
                raise UserError("El NIF es obligatorio.")
        elif account_type == "professional":
            if professional_type not in self.PROFESSIONAL_CATEGORY_MAP:
                raise UserError("Selecciona el tipo de profesional.")
            if not (request.params.get("partner_vat") or "").strip():
                vat_name = "CIF" if professional_type == "company" else "NIF"
                raise UserError(f"El {vat_name} es obligatorio.")
            if not (request.params.get("partner_phone") or "").strip():
                raise UserError("El teléfono/móvil es obligatorio.")

        login, password = request.env["res.users"].sudo().signup(values, token)

        if account_type == "particular":
            self._apply_particular_profile(login, self._get_particular_partner_values())
        elif account_type == "professional":
            category_name = self.PROFESSIONAL_CATEGORY_MAP.get(professional_type)
            partner_values = self._get_professional_partner_values()
            self._apply_professional_profile(
                login,
                professional_type,
                category_name,
                partner_values,
            )

        # Mismo orden que el controlador estándar de auth_signup: el usuario
        # debe estar confirmado en BD antes de autenticar una nueva sesión.
        request.env.cr.commit()
        credential = {
            "login": login,
            "password": password,
            "type": "password",
        }
        request.session.authenticate(request.db, credential)

    def _get_particular_partner_values(self):
        """Datos adicionales del contacto creado desde el alta Particular."""
        return {
            "vat": (request.params.get("partner_vat") or "").strip(),
        }

    def _get_professional_partner_values(self):
        """Recoge los datos del formulario profesional para ``res.partner``.

        Los nombres de los inputs están prefijados con ``partner_`` para que
        el flujo estándar de ``auth_signup`` no intente tratarlos como campos
        propios del alta de usuario. Aquí se traducen a campos del contacto.
        """
        values = {
            "street": (request.params.get("partner_street") or "").strip(),
            "zip": (request.params.get("partner_zip") or "").strip(),
            "city": (request.params.get("partner_city") or "").strip(),
            "vat": (request.params.get("partner_vat") or "").strip(),
            "phone": (request.params.get("partner_phone") or "").strip(),
            "website": (request.params.get("partner_website") or "").strip(),
        }
        return {field_name: value for field_name, value in values.items() if value}

    def _apply_particular_profile(self, login, partner_values):
        """Guarda el NIF obligatorio en el contacto de una cuenta Particular."""
        User = request.env["res.users"].sudo()
        user = User.search(
            User._get_login_domain(login),
            order=User._get_login_order(),
            limit=1,
        )
        if user and user.partner_id:
            user.partner_id.sudo().write(partner_values)

    def _apply_professional_profile(
        self,
        login,
        professional_type,
        category_name,
        partner_values=None,
    ):
        """Configura el contacto profesional y asigna su etiqueta.

        - Empresa: el contacto pasa a ser de tipo Compañía.
        - Autónomo: se mantiene como Individuo.
        - La categoría se reutiliza si ya existe (búsqueda case-insensitive).
        - Calle y número, CP, ciudad, NIF/CIF, teléfono y web se guardan en el contacto.
        """
        User = request.env["res.users"].sudo()
        user = User.search(
            User._get_login_domain(login),
            order=User._get_login_order(),
            limit=1,
        )
        if not user or not user.partner_id:
            return

        partner = user.partner_id.sudo()
        values_to_write = {
            "is_company": professional_type == "company",
        }
        values_to_write.update(partner_values or {})
        partner.write(values_to_write)

        Category = request.env["res.partner.category"].sudo().with_context(
            active_test=False
        )

        # =ilike evita crear duplicados por diferencias de mayúsculas/minúsculas.
        category = Category.search(
            [("name", "=ilike", category_name)],
            limit=1,
        )
        if not category:
            category = Category.create({"name": category_name})

        if category not in partner.category_id:
            partner.write({
                "category_id": [(4, category.id)],
            })
