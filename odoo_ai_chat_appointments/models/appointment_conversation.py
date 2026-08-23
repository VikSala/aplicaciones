import re
import unicodedata
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models, _


WEEKDAYS_ES = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

YES_WORDS = {
    "si", "vale", "ok", "okay", "perfecto", "perfecta", "confirmo", "confirmar",
    "de acuerdo", "me va bien", "esta bien", "genial", "adelante",
}
NO_WORDS = {
    "no", "otra", "otra hora", "otro horario", "no me va bien", "cambiar", "cambialo",
}
CANCEL_WORDS = {
    "cancelar", "cancela", "cancelalo", "cancelala", "olvidalo", "dejalo", "salir",
}
RESTART_WORDS = {
    "reiniciar", "empezar de nuevo", "volver a empezar", "nueva reserva", "otra reserva",
}
GREETING_WORDS = {
    "hola", "buenas", "buenos dias", "buenas dias", "buenas tardes", "buenas noches",
    "hey", "ey", "holi", "hello",
}
BOOKING_INTENT_WORDS = {
    "cita", "una cita", "quiero cita", "quiero una cita", "pedir cita", "reservar cita",
    "reservar una cita", "agendar cita", "agendar una cita", "reserva", "reservar",
}
HELP_WORDS = {
    "ayuda", "ayudame", "que opciones tengo", "que puedo decir", "opciones", "menu",
}
THANKS_WORDS = {
    "gracias", "muchas gracias", "genial gracias", "perfecto gracias",
}

TODAY_APPOINTMENTS_WORDS = {
    "mis citas",
    "mis citas de hoy",
    "citas de hoy",
    "que citas tengo",
    "que citas tengo hoy",
    "cuales son mis citas",
    "cuales son mis citas de hoy",
    "cuales son las citas que tengo",
    "cuales son las citas que tengo hoy",
    "mi agenda",
    "mi agenda de hoy",
    "agenda de hoy",
    "mis citas hoy",
}

APPOINTMENT_DATE_WORDS = {
    "hoy",
    "mañana",
    "manana",
    "pasado mañana",
    "pasado manana",
    "lunes",
    "martes",
    "miercoles",
    "miércoles",
    "jueves",
    "viernes",
    "sabado",
    "sábado",
    "domingo",
}

MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


class OdooAIAppointmentConversation(models.AbstractModel):
    _name = "odoo.ai.appointment.conversation"
    _description = "Máquina de estados y parser Python del chatbot de citas"

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @api.model
    def process_message(self, session, message):
        """Procesa un mensaje sin IA y devuelve una respuesta estructurada.

        `handled=True` significa que Python ha entendido la entrada y ha aplicado
        una transición determinista. `fallback=True` marca exactamente el único
        punto en que puede intervenir n8n/IA, sin otorgarle autoridad sobre
        disponibilidad, estado ni reservas.
        """
        session = self._coerce_session(session)
        text = (message or "").strip()
        normalized = self._normalize(text)

        if not text:
            return self._fallback(session, _("El mensaje está vacío."))

        session.write({"last_activity": fields.Datetime.now()})

        # Reiniciar abre un proceso nuevo y conserva el anterior como histórico.
        # Se permite incluso si por una llamada interna todavía recibimos una
        # sesión ya reservada; los canales normales ya crearían una nueva.
        if self._matches_any(normalized, RESTART_WORDS):
            new_session = session.start_new_process(reason="user_restart")
            return self._handled(
                new_session,
                self._service_question(),
                action="new_process_started",
                previous_session_ref=session.name,
            )

        # Una cita confirmada nunca se cancela ni modifica implícitamente desde
        # este parser. Para otra cita se abre un proceso nuevo.
        if session.state == "booked":
            return self._handled(
                session,
                _("Esta cita ya está confirmada. Si quieres reservar otra, escribe “nueva reserva”."),
                action="already_booked",
            )

        if self._matches_any(normalized, CANCEL_WORDS):
            session.cancel_process(reason="user_cancelled")
            return self._handled(
                session,
                _("He cancelado este proceso de reserva. Cuando quieras empezar otro, escribe “nueva reserva”."),
                action="cancelled",
            )

        if session.state in ("cancelled", "expired"):
            return self._handled(
                session,
                _("Esta sesión ya está cerrada. Inicia una nueva reserva para continuar."),
                action="closed_session",
            )

        if session.state == "ready_to_book":
            if normalized in {"confirmar", "reintentar", "intentar de nuevo"} or self._parse_yes_no(normalized) is True:
                return self._attempt_booking(session)
            return self._handled(
                session,
                self.get_resume_message(session),
                action="ready_to_book_waiting_confirmation",
            )

        # Intenciones simples que podemos resolver siempre por código. Esto
        # evita gastar IA en saludos o en un genérico "quiero cita" y, sobre
        # todo, permite reanudar el punto exacto de la reserva después de un
        # fallback conversacional.
        if self._is_simple_greeting(normalized):
            return self._handled(
                session,
                self._greeting_reply(session),
                action="greeting",
            )
        if self._is_booking_intent(normalized):
            return self._handled(
                session,
                self.get_resume_message(session),
                action="booking_intent_resume",
            )
        if self._matches_any(normalized, HELP_WORDS):
            return self._handled(
                session,
                self._help_reply(session),
                action="help",
            )
        # Consulta de agenda del empleado conectado. Se procesa antes de la
        # máquina de estados de reserva para que "mis citas" funcione aunque
        # el usuario tenga una conversación de reserva abierta.
        if self._is_today_appointments_intent(normalized):
            return self._handle_today_appointments(session, normalized)

        if self._matches_any(normalized, THANKS_WORDS):
            return self._handled(
                session,
                _("De nada. %s") % self.get_resume_message(session),
                action="thanks",
            )

        state = session.state or "new"
        if state in ("new", "waiting_service"):
            result = self._handle_service(session, text, normalized)
        elif state == "waiting_booking_mode":
            result = self._handle_booking_mode(session, text, normalized)
        elif state == "waiting_employee":
            result = self._handle_employee(session, text, normalized)
        elif state == "waiting_time_preference":
            result = self._handle_time_preference(session, text, normalized)
        elif state == "slot_proposed":
            result = self._handle_slot_confirmation(session, text, normalized)
        elif state == "waiting_customer_name":
            result = self._handle_customer_name(session, text, normalized)
        else:
            return self._handled(
                session,
                _("El estado actual de la conversación no está contemplado por el flujo de reservas."),
                action="unsupported_state",
            )

        # Si la respuesta específica del estado no entiende el mensaje, damos
        # una última oportunidad a intenciones globales conocidas antes de
        # enviar nada a n8n. Un servicio explícito es válido en cualquier punto
        # de una reserva: puede reafirmar el actual o cambiarlo.
        if result.get("fallback"):
            global_result = self._try_global_recovery(session, text, normalized)
            if global_result:
                return global_result
        return result


    @api.model
    def _is_today_appointments_intent(self, normalized):
        """Detecta consultas de agenda del empleado autenticado.

        El usuario no tiene que utilizar una frase exacta. Se aceptan formas
        naturales como:
        - "mis citas de hoy"
        - "dime mis citas de mañana"
        - "citas del lunes"
        - "dime las citas de mañana"
        - "qué citas tengo el miércoles"
        - "mi agenda del viernes"
        - "mis citas del 28 de agosto"

        Es importante no confundir estas consultas con una petición de reserva
        como "quiero una cita mañana". Las expresiones de reserva se excluyen
        explícitamente para que el flujo de contratación siga funcionando.
        """
        normalized = (normalized or "").strip()
        if not normalized:
            return False

        if normalized in TODAY_APPOINTMENTS_WORDS:
            return True

        # Palabras que indican que el usuario quiere CREAR/RESERVAR una cita,
        # no consultar las que ya tiene. Esta comprobación evita que una frase
        # como "quiero una cita mañana" se interprete como consulta de agenda.
        booking_query = re.search(
            r"\b(?:quiero|quisiera|necesito|busco|solicito|reservar|reserva|"
            r"pedir|pido|agendar|crear|concertar|coger|"
            r"sacar)\b",
            normalized,
        )
        if booking_query and not re.search(
            r"\b(?:mis|mi)\s+(?:citas?|agenda)\b", normalized
        ):
            return False

        has_appointment_word = bool(re.search(r"\b(?:citas?|agenda)\b", normalized))
        if not has_appointment_word:
            return False

        # Una consulta de agenda con fecha debe contener una referencia
        # temporal reconocible. Esto permite "citas del lunes" sin exigir la
        # expresión literal "mis citas".
        return self._parse_appointment_query_date(normalized) is not None

    @api.model
    def _parse_appointment_query_date(self, normalized):
        """Devuelve el día local solicitado para una consulta de agenda."""
        normalized = self._normalize(normalized or "")
        user = self.env.user
        tz_name = user.tz or "UTC"
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.UTC

        now_utc = fields.Datetime.to_datetime(fields.Datetime.now())
        if not now_utc.tzinfo:
            now_utc = pytz.UTC.localize(now_utc)
        today = now_utc.astimezone(tz).date()

        if re.search(r"\bpasado manana\b", normalized):
            return today + timedelta(days=2)
        if re.search(r"\bmanana\b", normalized):
            return today + timedelta(days=1)
        if re.search(r"\bhoy\b", normalized):
            return today

        # "el lunes", "mis citas del lunes", etc. -> próxima aparición
        # de ese día de la semana (si hoy coincide, se interpreta como hoy).
        for weekday_name, weekday in WEEKDAYS_ES.items():
            if (
                re.search(r"\b(?:el|del|de|para)\s+%s\b" % re.escape(weekday_name), normalized)
                or re.search(r"\b(?:mis|las|mis próximas|mis proximas)\s+(?:citas?|agenda)\s+(?:del?\s+)?%s\b" % re.escape(weekday_name), normalized)
                or re.search(r"\b(?:citas?|agenda)\s+%s\b" % re.escape(weekday_name), normalized)
            ):
                days_ahead = (weekday - today.weekday()) % 7
                return today + timedelta(days=days_ahead)

        # Fechas numéricas: 28/08, 28-08-2026, 28.08.2026, etc.
        match = re.search(r"\b(\d{1,2})[\/\-\.](\d{1,2})(?:[\/\-\.](\d{4}))?\b", normalized)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3) or today.year)
            try:
                result = datetime(year, month, day).date()
            except ValueError:
                return None
            # Si no se indicó año y la fecha ya pasó, normalmente se refiere
            # a la siguiente aparición de esa fecha.
            if not match.group(3) and result < today:
                try:
                    result = datetime(today.year + 1, month, day).date()
                except ValueError:
                    return None
            return result

        # "28 de agosto" / "28 agosto".
        match = re.search(r"\b(\d{1,2})\s+(?:de\s+)?([a-z]+)(?:\s+(?:de\s+)?(\d{4}))?\b", normalized)
        if match and match.group(2) in MONTHS_ES:
            day = int(match.group(1))
            month = MONTHS_ES[match.group(2)]
            year = int(match.group(3) or today.year)
            try:
                result = datetime(year, month, day).date()
            except ValueError:
                return None
            if not match.group(3) and result < today:
                try:
                    result = datetime(today.year + 1, month, day).date()
                except ValueError:
                    return None
            return result

        return None

    @api.model
    def _handle_today_appointments(self, session, normalized=None):
        """Devuelve las citas del día solicitado del empleado autenticado.

        La identidad se toma del usuario de Odoo. Para hoy solo se muestran
        citas cuyo inicio todavía no ha pasado; para mañana, un día de la
        semana o una fecha futura/pasada se muestran todas las citas de ese día.
        """
        user = self.env.user
        Employee = self.env["hr.employee"].sudo()
        Attendance = self.env["hr.attendance"].sudo()

        if not user or user._is_public():
            return self._handled(
                session,
                _("Para consultar tus citas necesitas estar conectado con tu usuario de Odoo."),
                action="appointments_requires_login",
            )

        employees = Employee.search([
            ("user_id", "=", user.id),
            ("active", "=", True),
        ])
        if not employees:
            return self._handled(
                session,
                _("No encuentro un empleado asociado a tu usuario de Odoo, así que no puedo consultar tus citas."),
                action="appointments_no_employee",
            )

        target_date = self._parse_appointment_query_date(normalized or "")
        if target_date is None:
            target_date = self._local_today_for_user(user)

        tz_name = user.tz or "UTC"
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.UTC

        now_utc = fields.Datetime.to_datetime(fields.Datetime.now())
        if not now_utc.tzinfo:
            now_utc = pytz.UTC.localize(now_utc)
        local_now = now_utc.astimezone(tz)
        local_today = local_now.date()

        local_day_start = tz.localize(datetime.combine(target_date, datetime.min.time()))
        local_day_end = local_day_start + timedelta(days=1)
        utc_day_start = local_day_start.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_day_end = local_day_end.astimezone(pytz.UTC).replace(tzinfo=None)

        appointments = Attendance.search([
            ("employee_id", "in", employees.ids),
            ("check_in", ">=", fields.Datetime.to_string(utc_day_start)),
            ("check_in", "<", fields.Datetime.to_string(utc_day_end)),
        ], order="check_in asc, id asc")

        if target_date == local_today:
            current_utc_naive = local_now.astimezone(pytz.UTC).replace(tzinfo=None)
            appointments = appointments.filtered(
                lambda appointment: (
                    appointment.check_in
                    and fields.Datetime.to_datetime(appointment.check_in) >= current_utc_naive
                )
            )

        if not appointments:
            if target_date == local_today:
                reply = _("Hoy no tienes más citas pendientes.")
            else:
                reply = _("No tienes citas para el %(date)s.") % {
                    "date": target_date.strftime("%d/%m/%Y"),
                }
            return self._handled(
                session,
                reply,
                action="appointments",
                appointment_count=0,
                appointment_date=target_date.isoformat(),
            )

        lines = []
        for appointment in appointments:
            start = fields.Datetime.to_datetime(appointment.check_in)
            if not start.tzinfo:
                start = pytz.UTC.localize(start)
            start_local = start.astimezone(tz)

            end_local = False
            if appointment.check_out:
                end = fields.Datetime.to_datetime(appointment.check_out)
                if not end.tzinfo:
                    end = pytz.UTC.localize(end)
                end_local = end.astimezone(tz)

            time_text = start_local.strftime("%H:%M")
            if end_local:
                time_text += "–%s" % end_local.strftime("%H:%M")

            client = (appointment.cliente or "").strip()
            service = appointment.appointment_service_id.display_name if appointment.appointment_service_id else ""
            details = []
            if client:
                details.append(client)
            if service:
                details.append(service)
            suffix = " — %s" % " · ".join(details) if details else ""
            lines.append("• %s%s" % (time_text, suffix))

        employee_names = ", ".join(employees.mapped("name"))
        if target_date == local_today:
            title = _("Tus próximas citas de hoy, %(employee)s, son:")
        else:
            title = _("Tus citas del %(date)s, %(employee)s, son:")
        reply = title % {
            "employee": employee_names,
            "date": target_date.strftime("%d/%m/%Y"),
        } + "\n" + "\n".join(lines)
        return self._handled(
            session,
            reply,
            action="appointments",
            appointment_count=len(appointments),
            appointment_date=target_date.isoformat(),
        )

    @api.model
    def _local_today_for_user(self, user):
        tz_name = user.tz or "UTC"
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.UTC
        now_utc = fields.Datetime.to_datetime(fields.Datetime.now())
        if not now_utc.tzinfo:
            now_utc = pytz.UTC.localize(now_utc)
        return now_utc.astimezone(tz).date()

    @api.model
    def _is_simple_greeting(self, normalized):
        normalized = (normalized or "").strip()
        if normalized in GREETING_WORDS:
            return True
        # Variantes muy comunes escritas en chat: "holaa", "holaaa".
        return bool(re.fullmatch(r"hola+", normalized))

    @api.model
    def _is_booking_intent(self, normalized):
        return (normalized or "").strip() in BOOKING_INTENT_WORDS

    @api.model
    def _greeting_reply(self, session):
        resume = self.get_resume_message(session)
        if session.state in ("new", "waiting_service"):
            return _("¡Hola! %s") % resume
        return _("¡Hola! %s") % resume

    @api.model
    def _help_reply(self, session):
        resume = self.get_resume_message(session)
        return _(
            "%(resume)s También puedes escribir “cancelar” para cerrar este proceso o “nueva reserva” para empezar otro.",
            resume=resume,
        )

    @api.model
    def _try_global_recovery(self, session, text, normalized):
        """Recupera cambios inequívocos antes de recurrir a la IA.

        En Fase 8 servicio, profesional y modalidad son intenciones globales:
        el usuario puede cambiar de opinión sin tener que volver manualmente al
        principio. Se conserva la preferencia horaria siempre que siga siendo
        aplicable y se recalcula la propuesta con datos reales.
        """
        explicit_services = self._find_services(normalized)
        explicit_service = explicit_services[0] if len(explicit_services) == 1 else False

        if explicit_service and session.service_id != explicit_service:
            return self._switch_service(session, explicit_service, text, normalized)

        service = explicit_service or session.service_id
        if service:
            employee = self._find_employee(service, normalized)
            if employee and session.state not in ("new", "waiting_service"):
                return self._switch_employee(session, employee, text, normalized)

            if re.search(r"\b(?:otro|otra) (?:profesional|fisio|fisioterapeuta|entrenador)\b", normalized):
                session.write({
                    "booking_mode": "choose_employee",
                    "employee_id": False,
                    "proposed_employee_id": False,
                    "proposed_start": False,
                    "proposed_end": False,
                    "state": "waiting_employee",
                })
                return self._handled(
                    session,
                    self._employee_question(service),
                    action="change_employee_requested",
                )

            mode = self._parse_booking_mode(normalized)
            if mode and session.state not in ("new", "waiting_service"):
                return self._switch_booking_mode(session, mode, text, normalized)

        if explicit_service and session.service_id == explicit_service:
            return self._handled(
                session,
                self.get_resume_message(session),
                action="service_reaffirmed",
            )
        return False

    @api.model
    def _switch_service(self, session, service, text, normalized):
        """Cambia de servicio conservando contexto que siga siendo válido."""
        previous_mode = session.booking_mode
        previous_employee = session.employee_id
        preference_snapshot = {
            "preference_text": session.preference_text,
            "preferred_date_from": session.preferred_date_from,
            "preferred_date_to": session.preferred_date_to,
            "preferred_time_from": session.preferred_time_from,
            "preferred_time_to": session.preferred_time_to,
            "preference_data": dict(session.preference_data or {}),
        }
        session.write({
            "service_id": service.id,
            "booking_mode": False,
            "employee_id": False,
            "proposed_employee_id": False,
            "proposed_start": False,
            "proposed_end": False,
            "state": "waiting_booking_mode",
            **preference_snapshot,
        })

        explicit_employee = self._find_employee(service, normalized)
        if explicit_employee:
            return self._switch_employee(session, explicit_employee, text, normalized, service_changed=True)

        explicit_mode = self._parse_booking_mode(normalized)
        if explicit_mode:
            return self._switch_booking_mode(session, explicit_mode, text, normalized, service_changed=True)

        # Una modalidad previa inequívoca puede mantenerse. Si el profesional
        # anterior también ofrece el nuevo servicio, mantenemos igualmente esa
        # elección; si no, volvemos a preguntar modalidad/profesional.
        if previous_mode == "first_available":
            session.write({"booking_mode": "first_available", "state": "waiting_time_preference"})
            if self._has_saved_preference(session):
                return self._propose_from_saved_preference(
                    session,
                    action="service_changed_first_available",
                    intro=_("He cambiado el servicio a %s y mantengo tu preferencia horaria.") % service.display_name,
                )
            return self._handled(
                session,
                _("He cambiado el servicio a %(service)s. ¿Qué día u horario prefieres?", service=service.display_name),
                action="service_changed",
            )

        if previous_mode == "choose_employee" and previous_employee and previous_employee in service.get_eligible_employees():
            session.write({
                "booking_mode": "choose_employee",
                "employee_id": previous_employee.id,
                "state": "waiting_time_preference",
            })
            if self._has_saved_preference(session):
                return self._propose_from_saved_preference(
                    session,
                    action="service_changed_employee_preserved",
                    intro=_("He cambiado el servicio a %(service)s y mantengo a %(employee)s.", service=service.display_name, employee=previous_employee.display_name),
                )
            return self._handled(
                session,
                _("He cambiado el servicio a %(service)s y mantengo a %(employee)s. ¿Qué día u horario prefieres?", service=service.display_name, employee=previous_employee.display_name),
                action="service_changed_employee_preserved",
            )

        return self._handled(
            session,
            _(
                "He cambiado el servicio a %(service)s. %(question)s",
                service=service.display_name,
                question=_("¿Quieres 1) elegir profesional o 2) reservar con quien tenga la primera disponibilidad?"),
            ),
            action="service_changed",
        )

    @api.model
    def _switch_employee(self, session, employee, text, normalized, service_changed=False):
        if session.employee_id == employee and session.booking_mode == "choose_employee" and not service_changed:
            return self._handled(session, self.get_resume_message(session), action="employee_reaffirmed")
        session.write({
            "booking_mode": "choose_employee",
            "employee_id": employee.id,
            "proposed_employee_id": False,
            "proposed_start": False,
            "proposed_end": False,
            "state": "waiting_time_preference",
        })
        parsed = self._parse_time_preference(session, text, normalized)
        if parsed.get("recognized"):
            return self._handle_time_preference(session, text, normalized)
        if self._has_saved_preference(session):
            return self._propose_from_saved_preference(
                session,
                action="employee_changed",
                intro=_("De acuerdo, buscaré ahora con %s.") % employee.display_name,
            )
        return self._handled(
            session,
            _("De acuerdo, buscaré con %(employee)s. ¿Qué día u horario prefieres?", employee=employee.display_name),
            action="employee_changed",
        )

    @api.model
    def _switch_booking_mode(self, session, mode, text, normalized, service_changed=False):
        if mode == "choose_employee":
            session.write({
                "booking_mode": "choose_employee",
                "employee_id": False,
                "proposed_employee_id": False,
                "proposed_start": False,
                "proposed_end": False,
                "state": "waiting_employee",
            })
            return self._handled(session, self._employee_question(session.service_id), action="booking_mode_changed")

        session.write({
            "booking_mode": "first_available",
            "employee_id": False,
            "proposed_employee_id": False,
            "proposed_start": False,
            "proposed_end": False,
            "state": "waiting_time_preference",
        })
        parsed = self._parse_time_preference(session, text, normalized)
        if parsed.get("recognized"):
            return self._handle_time_preference(session, text, normalized)
        if self._has_saved_preference(session):
            return self._propose_from_saved_preference(
                session,
                action="booking_mode_changed",
                intro=_("De acuerdo, buscaré la primera disponibilidad manteniendo tu preferencia horaria."),
            )
        return self._handled(
            session,
            _("De acuerdo, buscaré la primera disponibilidad. ¿Qué día u horario prefieres?"),
            action="booking_mode_changed",
        )

    @api.model
    def _has_saved_preference(self, session):
        # Los Float vacíos de Odoo pueden leerse como 0.0; `preference_text` y
        # `preference_data` distinguen de forma fiable una preferencia que ya
        # fue realmente procesada por el parser.
        return bool(
            session.preference_text
            or session.preference_data
            or session.preferred_date_from
            or session.preferred_date_to
        )

    @api.model
    def _propose_from_saved_preference(self, session, action="context_changed", intro=None):
        preference = self._get_session_preference(session)
        if not session.service_id:
            return self._handled(session, self._service_question(), action=action)

        employee = session.employee_id if session.booking_mode == "choose_employee" else None
        slot = session.service_id.get_first_available_slot(
            employee=employee,
            date_from=preference.get("date_from"),
            date_to=preference.get("date_to"),
            time_from=preference.get("time_from"),
            time_to=preference.get("time_to"),
        )
        if not slot:
            session.write({
                "proposed_employee_id": False,
                "proposed_start": False,
                "proposed_end": False,
                "state": "waiting_time_preference",
            })
            prefix = (intro + " ") if intro else ""
            return self._handled(
                session,
                prefix + _("No encuentro ningún hueco con esa preferencia. Indícame otro día u horario."),
                action="context_changed_no_slot",
            )

        session.write({
            "proposed_employee_id": slot["employee_id"],
            "proposed_start": slot["start"],
            "proposed_end": slot["end"],
            "state": "slot_proposed",
        })
        prefix = (intro + " ") if intro else ""
        return self._handled(
            session,
            prefix + _(
                "Tengo disponible con %(employee)s el %(start)s. ¿Te viene bien? Responde sí o no.",
                employee=slot["employee_name"],
                start=slot["start_local"],
            ),
            action=action,
            slot=slot,
        )

    # ------------------------------------------------------------------
    # Estados
    # ------------------------------------------------------------------

    @api.model
    def _handle_service(self, session, text, normalized):
        matches = self._find_services(normalized)
        if len(matches) != 1:
            session.write({"state": "waiting_service"})
            if len(matches) > 1:
                names = ", ".join(matches.mapped("name"))
                return self._fallback(session, _("He encontrado más de un servicio posible: %s") % names)
            return self._fallback(session, self._service_question())

        service = matches[0]
        session.write({
            "service_id": service.id,
            "state": "waiting_booking_mode",
            "booking_mode": False,
            "employee_id": False,
        })

        # Si el primer mensaje ya contiene profesional o modalidad, no
        # obligamos al usuario a repetir información que Python ya entiende.
        employee = self._find_employee(service, normalized)
        if not employee:
            mentioned_employee = self._find_any_employee(normalized)
            if mentioned_employee and mentioned_employee not in service.get_eligible_employees():
                return self._handled(
                    session,
                    _(
                        "%(employee)s no está habilitado para %(service)s. %(question)s",
                        employee=mentioned_employee.display_name,
                        service=service.display_name,
                        question=self._employee_question(service),
                    ),
                    action="employee_not_eligible",
                )
        if employee:
            session.write({
                "booking_mode": "choose_employee",
                "employee_id": employee.id,
                "state": "waiting_time_preference",
            })
            if self._parse_time_preference(session, text, normalized).get("recognized"):
                return self._handle_time_preference(session, text, normalized)
            return self._handled(
                session,
                _("Perfecto, %(service)s con %(employee)s. ¿Qué preferencia de día u horario tienes?",
                  service=service.display_name, employee=employee.display_name),
                action="service_and_employee_selected",
            )

        mode = self._parse_booking_mode(normalized)
        if mode:
            if mode == "choose_employee":
                session.write({"booking_mode": mode, "state": "waiting_employee"})
                return self._handled(session, self._employee_question(service), action="service_and_booking_mode_selected")
            session.write({"booking_mode": mode, "state": "waiting_time_preference"})
            if self._parse_time_preference(session, text, normalized).get("recognized"):
                return self._handle_time_preference(session, text, normalized)
            return self._handled(
                session,
                _("Perfecto, buscaré la primera disponibilidad para %(service)s. ¿Qué preferencia de día u horario tienes?",
                  service=service.display_name),
                action="service_and_booking_mode_selected",
            )

        employees = service.get_eligible_employees()
        employee_names = ", ".join(employees.mapped("name")) or _("ningún profesional configurado")
        reply = _(
            "Perfecto, has elegido %(service)s. Profesionales disponibles para este servicio: %(employees)s. "
            "¿Quieres 1) elegir profesional o 2) reservar con quien tenga la primera disponibilidad?",
            service=service.display_name,
            employees=employee_names,
        )
        return self._handled(session, reply, action="service_selected")

    @api.model
    def _handle_booking_mode(self, session, text, normalized):
        employee = self._find_employee(session.service_id, normalized)
        if employee:
            session.write({
                "booking_mode": "choose_employee",
                "employee_id": employee.id,
                "state": "waiting_time_preference",
            })
            if self._parse_time_preference(session, text, normalized).get("recognized"):
                return self._handle_time_preference(session, text, normalized)
            return self._handled(
                session,
                _("Perfecto, buscaré con %(employee)s. ¿Qué preferencia de día u horario tienes?", employee=employee.display_name),
                action="employee_selected",
            )

        mode = self._parse_booking_mode(normalized)
        if mode == "choose_employee":
            session.write({"booking_mode": mode, "state": "waiting_employee"})
            return self._handled(session, self._employee_question(session.service_id), action="booking_mode_selected")
        if mode == "first_available":
            session.write({"booking_mode": mode, "employee_id": False, "state": "waiting_time_preference"})
            if self._parse_time_preference(session, text, normalized).get("recognized"):
                return self._handle_time_preference(session, text, normalized)
            return self._handled(
                session,
                _("Perfecto, buscaré la primera disponibilidad entre todos los profesionales compatibles. ¿Qué preferencia de día u horario tienes?"),
                action="booking_mode_selected",
            )

        return self._fallback(
            session,
            _("No he podido saber qué modalidad prefieres. Responde 1 para elegir profesional o 2 para la primera disponibilidad."),
        )

    @api.model
    def _handle_employee(self, session, text, normalized):
        employee = self._find_employee(session.service_id, normalized)
        if not employee:
            mentioned_employee = self._find_any_employee(normalized)
            if mentioned_employee:
                return self._handled(
                    session,
                    _(
                        "%(employee)s no está habilitado para %(service)s. %(question)s",
                        employee=mentioned_employee.display_name,
                        service=session.service_id.display_name,
                        question=self._employee_question(session.service_id),
                    ),
                    action="employee_not_eligible",
                )
            return self._fallback(session, self._employee_question(session.service_id))

        session.write({
            "employee_id": employee.id,
            "booking_mode": "choose_employee",
            "state": "waiting_time_preference",
        })
        if self._parse_time_preference(session, text, normalized).get("recognized"):
            return self._handle_time_preference(session, text, normalized)
        return self._handled(
            session,
            _("Perfecto, buscaré con %(employee)s. ¿Qué preferencia de día u horario tienes?", employee=employee.display_name),
            action="employee_selected",
        )

    @api.model
    def _handle_time_preference(self, session, text, normalized):
        parsed = self._parse_time_preference(session, text, normalized)
        if not parsed.get("recognized"):
            return self._fallback(
                session,
                _("No he podido interpretar esa preferencia horaria. Prueba, por ejemplo: “por la tarde”, “mañana a partir de las 17”, “el martes” o “lo antes posible”."),
            )

        preference_json = dict(parsed)
        for key in ("date_from", "date_to"):
            if preference_json.get(key):
                preference_json[key] = fields.Date.to_string(preference_json[key])

        session.write({
            "preference_text": text,
            "preferred_date_from": parsed.get("date_from") or False,
            "preferred_date_to": parsed.get("date_to") or False,
            "preferred_time_from": parsed.get("time_from") if parsed.get("time_from") is not None else False,
            "preferred_time_to": parsed.get("time_to") if parsed.get("time_to") is not None else False,
            "preference_data": preference_json,
        })

        employee = session.employee_id if session.booking_mode == "choose_employee" else None
        slot = session.service_id.get_first_available_slot(
            employee=employee,
            date_from=parsed.get("date_from"),
            date_to=parsed.get("date_to"),
            time_from=parsed.get("time_from"),
            time_to=parsed.get("time_to"),
        )
        if not slot:
            session.write({
                "proposed_employee_id": False,
                "proposed_start": False,
                "proposed_end": False,
                "state": "waiting_time_preference",
            })
            return self._handled(
                session,
                _("No encuentro ningún hueco con esa preferencia dentro del horizonte configurado. Indícame otro día u horario."),
                action="no_slot",
            )

        session.write({
            "proposed_employee_id": slot["employee_id"],
            "proposed_start": slot["start"],
            "proposed_end": slot["end"],
            "state": "slot_proposed",
        })
        reply = _(
            "Tengo disponible con %(employee)s el %(start)s. ¿Te viene bien? Responde sí o no.",
            employee=slot["employee_name"],
            start=slot["start_local"],
        )
        return self._handled(session, reply, action="slot_proposed", slot=slot)

    @api.model
    def _handle_slot_confirmation(self, session, text, normalized):
        answer = self._parse_yes_no(normalized)
        if answer is True:
            # Si ya conocemos el nombre (por ejemplo porque el hueco anterior
            # se ocupó justo al confirmar), no obligamos al usuario a repetirlo.
            if session.customer_name:
                session.write({"state": "ready_to_book"})
                return self._attempt_booking(session)

            session.write({"state": "waiting_customer_name"})
            return self._handled(
                session,
                _("Perfecto. Indícame tu nombre y apellidos para confirmar la reserva."),
                action="slot_accepted",
            )

        # "No, mejor a las 16" / "No, el martes" tiene prioridad sobre el
        # rechazo simple. El parser mezcla únicamente los datos nuevos con la
        # preferencia ya guardada, por lo que conserva profesional, día o
        # franja cuando el usuario no los vuelve a repetir.
        parsed = self._parse_time_preference(session, text, normalized)
        if answer is False and parsed.get("recognized"):
            session.write({
                "state": "waiting_time_preference",
                "proposed_employee_id": False,
                "proposed_start": False,
                "proposed_end": False,
            })
            return self._handle_time_preference(session, text, normalized)

        if answer is False:
            # Un "no" sin más no borra el contexto. Primero intentamos el
            # siguiente hueco posterior, priorizando el mismo día y respetando
            # servicio, profesional/modalidad y franja ya elegidos.
            next_slot = self._find_next_slot_after_rejection(session)
            if next_slot:
                session.write({
                    "proposed_employee_id": next_slot["employee_id"],
                    "proposed_start": next_slot["start"],
                    "proposed_end": next_slot["end"],
                    "state": "slot_proposed",
                })
                return self._handled(
                    session,
                    _(
                        "De acuerdo. Tengo otro hueco con %(employee)s el %(start)s. "
                        "¿Te viene bien? Responde sí o no.",
                        employee=next_slot["employee_name"],
                        start=next_slot["start_local"],
                    ),
                    action="alternative_slot_proposed",
                    slot=next_slot,
                )

            session.write({
                "state": "waiting_time_preference",
                "proposed_employee_id": False,
                "proposed_start": False,
                "proposed_end": False,
            })
            return self._handled(
                session,
                _(
                    "De acuerdo. No encuentro otro hueco posterior con esa misma preferencia. "
                    "Indícame otro día u horario y conservaré el resto de datos de la reserva."
                ),
                action="slot_rejected_no_alternative",
            )

        # Si el usuario responde directamente con otra preferencia, intentamos
        # reutilizar el parser sin exigir un "no" previo.
        if parsed.get("recognized"):
            session.write({
                "state": "waiting_time_preference",
                "proposed_employee_id": False,
                "proposed_start": False,
                "proposed_end": False,
            })
            return self._handle_time_preference(session, text, normalized)

        return self._fallback(session, _("Necesito saber si aceptas el hueco propuesto. Responde sí o no, o indica directamente otro horario."))

    @api.model
    def _handle_customer_name(self, session, text, normalized):
        # En el paso del nombre evitamos confundir frases como “mejor con
        # Fran” con un nombre de cliente. Solo intentamos cambios globales si
        # hay una señal lingüística clara de cambio/preferencia.
        change_cue = bool(re.search(
            r"\b(?:mejor|prefiero|cambiar|cambia|con|me da igual|cualquiera|primera disponibilidad)\b",
            normalized,
        ))
        if change_cue:
            global_result = self._try_global_recovery(session, text, normalized)
            if global_result:
                return global_result
            parsed = self._parse_time_preference(session, text, normalized)
            if parsed.get("recognized"):
                session.write({
                    "state": "waiting_time_preference",
                    "proposed_employee_id": False,
                    "proposed_start": False,
                    "proposed_end": False,
                })
                return self._handle_time_preference(session, text, normalized)

        customer_name = self._parse_customer_name(text, normalized)
        if not customer_name:
            return self._fallback(session, _("Necesito nombre y apellidos, por ejemplo: “Vik Sala”."))

        session.write({
            "customer_name": customer_name,
            "state": "ready_to_book",
        })
        return self._attempt_booking(session)

    @api.model
    def _attempt_booking(self, session):
        """Revalida el hueco y crea la cita real cuando procede."""
        booking = self.env["odoo.ai.appointment.booking"].sudo().book_session(session)
        status = booking.get("status")

        if status == "test":
            return self._handled(
                session,
                _(
                    "Datos preparados: %(customer)s, %(service)s con %(employee)s el %(start)s. "
                    "Esta es una sesión de prueba, por lo que no se crea ninguna asistencia.",
                    customer=session.customer_name,
                    service=session.service_id.display_name,
                    employee=session.proposed_employee_id.display_name,
                    start=self._format_session_slot(session),
                ),
                action="ready_to_book",
            )

        if status == "booked":
            return self._handled(
                session,
                _(
                    "Cita confirmada para %(customer)s: %(service)s con %(employee)s el %(start)s. "
                    "La reserva ya está registrada.",
                    customer=session.customer_name,
                    service=session.service_id.display_name,
                    employee=session.proposed_employee_id.display_name,
                    start=self._format_session_slot(session),
                ),
                action="booked",
            )

        if status == "conflict":
            # El hueco se ha ocupado entre la propuesta y la confirmación.
            # Conservamos incluso el nombre del cliente y buscamos la siguiente
            # alternativa con el mismo contexto de servicio/profesional/franja.
            next_slot = self._find_next_slot_after_rejection(session)
            if next_slot:
                session.write({
                    "proposed_employee_id": next_slot["employee_id"],
                    "proposed_start": next_slot["start"],
                    "proposed_end": next_slot["end"],
                    "state": "slot_proposed",
                })
                return self._handled(
                    session,
                    _(
                        "Ese hueco acaba de dejar de estar disponible. Tengo otro con %(employee)s "
                        "el %(start)s. ¿Te viene bien? Responde sí o no.",
                        employee=next_slot["employee_name"],
                        start=next_slot["start_local"],
                    ),
                    action="booking_conflict_alternative",
                    slot=next_slot,
                )

            session.write({
                "state": "waiting_time_preference",
                "proposed_employee_id": False,
                "proposed_start": False,
                "proposed_end": False,
            })
            return self._handled(
                session,
                _(
                    "Ese hueco acaba de dejar de estar disponible y no encuentro otra alternativa "
                    "con la misma preferencia. Indícame otro día u horario; conservaré el resto de datos."
                ),
                action="booking_conflict_no_alternative",
            )

        if status == "error":
            session.write({"state": "ready_to_book", "last_activity": fields.Datetime.now()})
            return self._handled(
                session,
                _(
                    "No he podido registrar la cita por un error interno, pero mantengo todos tus datos. "
                    "Escribe “confirmar” para volver a intentarlo o “cancelar” para cerrar el proceso."
                ),
                action="booking_error",
            )

        return self._fallback(
            session,
            _("No se ha podido confirmar la reserva porque faltan datos del proceso. Reinicia la reserva y vuelve a intentarlo."),
        )

    # ------------------------------------------------------------------
    # Parsers deterministas
    # ------------------------------------------------------------------

    @api.model
    def _find_services(self, normalized):
        Service = self.env["odoo.ai.appointment.service"]
        services = Service.search([("active", "=", True)])
        matches = Service.browse()
        normalized_padded = " %s " % normalized
        for service in services:
            candidates = [service.name or ""] + service.get_alias_list()
            for candidate in candidates:
                needle = self._normalize(candidate)
                if needle and (normalized == needle or " %s " % needle in normalized_padded):
                    matches |= service
                    break
        return matches

    @api.model
    def _parse_booking_mode(self, normalized):
        if normalized in {"1", "opcion 1", "primera opcion"}:
            return "choose_employee"
        if normalized in {"2", "opcion 2", "segunda opcion"}:
            return "first_available"

        choose_patterns = (
            "elegir", "elegir fisio", "elegir fisioterapeuta", "elegir profesional",
            "quiero elegir", "prefiero elegir", "con alguien concreto",
        )
        first_patterns = (
            "me da igual", "cualquiera", "lo antes posible", "primera disponibilidad",
            "primer hueco", "primero disponible", "quien este libre", "el que pueda antes",
            "el primero", "la primera",
        )
        if any(pattern in normalized for pattern in choose_patterns):
            return "choose_employee"
        if any(pattern in normalized for pattern in first_patterns):
            return "first_available"
        return False

    @api.model
    def _find_employee(self, service, normalized):
        if not service:
            return False
        employees = service.get_eligible_employees()
        if not employees:
            return False

        exact = []
        first_name = []
        padded = " %s " % normalized
        for employee in employees:
            emp_name = self._normalize(employee.name or "")
            if emp_name and (normalized == emp_name or " %s " % emp_name in padded):
                exact.append(employee)
                continue
            first = emp_name.split(" ", 1)[0] if emp_name else ""
            if first and re.search(r"(?:^|\s)%s(?:$|\s)" % re.escape(first), normalized):
                first_name.append(employee)

        if len(exact) == 1:
            return exact[0]
        if not exact and len(first_name) == 1:
            return first_name[0]
        return False

    @api.model
    def _find_any_employee(self, normalized):
        employees = self.env["hr.employee"].search([("active", "=", True)])
        exact = []
        first_name = []
        padded = " %s " % normalized
        for employee in employees:
            emp_name = self._normalize(employee.name or "")
            if emp_name and (normalized == emp_name or " %s " % emp_name in padded):
                exact.append(employee)
                continue
            first = emp_name.split(" ", 1)[0] if emp_name else ""
            if first and re.search(r"(?:^|\s)%s(?:$|\s)" % re.escape(first), normalized):
                first_name.append(employee)
        if len(exact) == 1:
            return exact[0]
        if not exact and len(first_name) == 1:
            return first_name[0]
        return False

    @api.model
    def _parse_time_preference(self, session, text, normalized):
        """Interpreta solo lo que aporta el mensaje y conserva el contexto previo.

        Ejemplos importantes:
          - preferencia previa: lunes por la tarde; mensaje: "a las 16"
            => mantiene lunes y cambia únicamente la hora.
          - preferencia previa: lunes por la tarde; mensaje: "martes"
            => cambia el día y mantiene la franja de tarde.
          - mensaje: "lo antes posible"
            => reinicia fecha/hora a una búsqueda abierta desde hoy.
        """
        today = self._today_for_session(session)
        horizon_to = today + timedelta(days=max(session.service_id.max_search_days, 1) - 1)
        previous = self._get_session_preference(session)

        result = {
            "recognized": False,
            "date_from": previous.get("date_from") or today,
            "date_to": previous.get("date_to") or horizon_to,
            "time_from": previous.get("time_from"),
            "time_to": previous.get("time_to"),
            "explicit_date": False,
            "explicit_time": False,
            "reset_scope": False,
            "parser": "python_phase3_contextual",
        }

        if any(token in normalized for token in ("lo antes posible", "cuanto antes", "primera disponible", "primer hueco")):
            result.update(
                recognized=True,
                date_from=today,
                date_to=horizon_to,
                time_from=None,
                time_to=None,
                reset_scope=True,
            )

        # Fechas explícitas dd/mm[/aaaa] o dd-mm[-aaaa].
        explicit = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", normalized)
        if explicit:
            day, month, year = int(explicit.group(1)), int(explicit.group(2)), explicit.group(3)
            year = int(year) if year else today.year
            if year < 100:
                year += 2000
            try:
                parsed_date = fields.Date.to_date("%04d-%02d-%02d" % (year, month, day))
                result.update(
                    date_from=parsed_date,
                    date_to=parsed_date,
                    recognized=True,
                    explicit_date=True,
                )
            except Exception:
                pass
        elif "pasado manana" in normalized:
            target = today + timedelta(days=2)
            result.update(date_from=target, date_to=target, recognized=True, explicit_date=True)
        elif self._contains_date_tomorrow(normalized):
            target = today + timedelta(days=1)
            result.update(date_from=target, date_to=target, recognized=True, explicit_date=True)
        elif re.search(r"\bhoy\b", normalized):
            result.update(date_from=today, date_to=today, recognized=True, explicit_date=True)
        else:
            weekday_dates = []
            for word, weekday in WEEKDAYS_ES.items():
                if re.search(r"\b%s\b" % word, normalized):
                    days_ahead = (weekday - today.weekday()) % 7
                    target = today + timedelta(days=days_ahead)
                    weekday_dates.append(target)
            if weekday_dates:
                result.update(
                    date_from=min(weekday_dates),
                    date_to=max(weekday_dates),
                    recognized=True,
                    explicit_date=True,
                )

        morning_from, morning_to, afternoon_from, afternoon_to = self._daypart_hours()
        if re.search(r"\bpor la manana\b|\bpor las mananas\b|\bde manana\b|\bmananas\b", normalized):
            result.update(
                time_from=morning_from,
                time_to=morning_to,
                recognized=True,
                explicit_time=True,
            )
        if re.search(r"\bpor la tarde\b|\bpor las tardes\b|\bde tarde\b|\btardes\b", normalized):
            result.update(
                time_from=afternoon_from,
                time_to=afternoon_to,
                recognized=True,
                explicit_time=True,
            )

        # "entre 17 y 19" / "entre las 17:30 y las 19:00"
        between = re.search(
            r"\bentre(?: las)?\s+(\d{1,2}(?::\d{2})?)\s+(?:y|a)\s+(?:las\s+)?(\d{1,2}(?::\d{2})?)\b",
            normalized,
        )
        if between:
            start = self._parse_clock(between.group(1))
            end = self._parse_clock(between.group(2))
            if start is not None and end is not None and end > start:
                result.update(
                    time_from=start,
                    time_to=end,
                    recognized=True,
                    explicit_time=True,
                )

        # "a partir de las 17", "desde las 17", "después de las 17".
        # Si había un límite superior previo compatible (p. ej. "por la tarde"),
        # se mantiene para que una respuesta parcial no destruya contexto útil.
        start_match = re.search(
            r"(?:a partir de|desde|despues de)(?: las)?\s+(\d{1,2}(?::\d{2})?)",
            normalized,
        )
        if start_match:
            parsed = self._parse_clock(start_match.group(1))
            if parsed is not None:
                result.update(time_from=parsed, recognized=True, explicit_time=True)
                if result.get("time_to") is not None and result["time_to"] <= parsed:
                    result["time_to"] = None

        # "antes de las 12" / "hasta las 12". Conserva un límite inferior
        # anterior cuando sigue siendo compatible.
        end_match = re.search(r"(?:antes de|hasta)(?: las)?\s+(\d{1,2}(?::\d{2})?)", normalized)
        if end_match:
            parsed = self._parse_clock(end_match.group(1))
            if parsed is not None:
                result.update(time_to=parsed, recognized=True, explicit_time=True)
                if result.get("time_from") is not None and parsed <= result["time_from"]:
                    result["time_from"] = None

        # "a las 17" = inicio exacto. Limitamos el final al tamaño del servicio.
        exact_time = re.search(r"(?:^|\s)a las\s+(\d{1,2}(?::\d{2})?)\b", normalized)
        if exact_time and not between and not start_match:
            parsed = self._parse_clock(exact_time.group(1))
            if parsed is not None:
                duration_hours = session.service_id.duration_minutes / 60.0
                result.update(
                    time_from=parsed,
                    time_to=min(parsed + duration_hours, 24.0),
                    recognized=True,
                    explicit_time=True,
                )

        return result

    @api.model
    def _parse_yes_no(self, normalized):
        if normalized == "si" or normalized.startswith("si ") or self._matches_any(normalized, YES_WORDS):
            return True
        if normalized == "no" or normalized.startswith("no ") or self._matches_any(normalized, NO_WORDS):
            return False
        return None

    @api.model
    def _parse_customer_name(self, text, normalized):
        if not text or len(text) > 120:
            return False
        if self._parse_yes_no(normalized) is not None or self._matches_any(normalized, CANCEL_WORDS):
            return False

        cleaned = re.sub(r"^(?:me llamo|soy)\s+", "", text.strip(), flags=re.IGNORECASE)
        if any(char.isdigit() for char in cleaned):
            return False
        words = [word for word in re.split(r"\s+", cleaned) if word]
        if len(words) < 2:
            return False
        if not all(re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", word) for word in words):
            return False
        return " ".join(words)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    @api.model
    def _get_session_preference(self, session):
        """Recupera la preferencia normalizada ya guardada en la sesión."""
        data = dict(session.preference_data or {})

        raw_date_from = data.get("date_from") or session.preferred_date_from
        raw_date_to = data.get("date_to") or session.preferred_date_to
        date_from = fields.Date.to_date(raw_date_from) if raw_date_from else False
        date_to = fields.Date.to_date(raw_date_to) if raw_date_to else False

        if "time_from" in data:
            time_from = data.get("time_from")
        else:
            time_from = session.preferred_time_from if session.preferred_time_from is not False else None

        if "time_to" in data:
            time_to = data.get("time_to")
        else:
            time_to = session.preferred_time_to if session.preferred_time_to is not False else None

        return {
            "date_from": date_from,
            "date_to": date_to,
            "time_from": time_from,
            "time_to": time_to,
        }

    @api.model
    def _find_next_slot_after_rejection(self, session):
        """Busca una alternativa sin perder la preferencia que originó el hueco.

        Se prioriza otro inicio posterior en el mismo día. Si ese día ya no
        ofrece más opciones y la preferencia original abarcaba más fechas, se
        continúa desde el día siguiente. Un rechazo simple, por tanto, no
        convierte de nuevo la búsqueda en "desde hoy".
        """
        if not session.proposed_start or not session.proposed_employee_id or not session.service_id:
            return False

        rejected_start = fields.Datetime.to_datetime(session.proposed_start)
        rejected_utc = rejected_start if rejected_start.tzinfo else pytz.UTC.localize(rejected_start)
        tz = pytz.timezone(session.proposed_employee_id._get_tz())
        rejected_local_date = rejected_utc.astimezone(tz).date()

        preference = self._get_session_preference(session)
        employee = session.employee_id if session.booking_mode == "choose_employee" else None
        search_kwargs = {
            "time_from": preference.get("time_from"),
            "time_to": preference.get("time_to"),
            "limit": 200,
        }

        # 1) Mismo día y una hora estrictamente posterior. En modo
        # first_available también evitamos devolver el mismo instante con otro
        # profesional, porque el usuario acaba de rechazar esa hora.
        same_day_slots = session.service_id.get_available_slots(
            employee=employee,
            date_from=rejected_local_date,
            date_to=rejected_local_date,
            **search_kwargs,
        )
        for slot in same_day_slots:
            if fields.Datetime.to_datetime(slot["start"]) > rejected_start:
                return slot

        # 2) Si la preferencia permitía más días, mantenemos la misma franja y
        # continuamos cronológicamente desde el día siguiente.
        date_to = preference.get("date_to")
        next_day = rejected_local_date + timedelta(days=1)
        if date_to and next_day <= date_to:
            later_slots = session.service_id.get_available_slots(
                employee=employee,
                date_from=next_day,
                date_to=date_to,
                **search_kwargs,
            )
            if later_slots:
                return later_slots[0]

        return False

    @api.model
    def _today_for_session(self, session):
        employee = session.employee_id or session.proposed_employee_id
        if not employee and session.service_id:
            employee = session.service_id.get_eligible_employees()[:1]
        tz_name = employee._get_tz() if employee else (self.env.user.tz or "UTC")
        now = fields.Datetime.to_datetime(fields.Datetime.now())
        if not now.tzinfo:
            now = pytz.UTC.localize(now)
        return now.astimezone(pytz.timezone(tz_name)).date()

    @api.model
    def _daypart_hours(self):
        config = self.env["ir.config_parameter"].sudo()
        return (
            self._config_float(config, "odoo_ai_chat_appointments.morning_from", 8.0),
            self._config_float(config, "odoo_ai_chat_appointments.morning_to", 14.0),
            self._config_float(config, "odoo_ai_chat_appointments.afternoon_from", 15.0),
            self._config_float(config, "odoo_ai_chat_appointments.afternoon_to", 21.0),
        )

    @api.model
    def _config_float(self, config, key, default):
        try:
            return float(config.get_param(key, default) or default)
        except (TypeError, ValueError):
            return default

    @api.model
    def _contains_date_tomorrow(self, normalized):
        if "manana" not in normalized:
            return False
        # "por la mañana" es franja horaria, no fecha; "mañana por la mañana"
        # sí contiene una ocurrencia independiente de fecha.
        stripped = normalized.replace("por la manana", "").replace("de manana", "")
        return bool(re.search(r"\bmanana\b", stripped))

    @api.model
    def _parse_clock(self, value):
        try:
            if ":" in value:
                hour, minute = value.split(":", 1)
                hour, minute = int(hour), int(minute)
            else:
                hour, minute = int(value), 0
        except (TypeError, ValueError):
            return None
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return hour + minute / 60.0

    @api.model
    def _normalize(self, value):
        value = (value or "").strip().lower()
        value = unicodedata.normalize("NFKD", value)
        value = "".join(char for char in value if not unicodedata.combining(char))
        value = re.sub(r"[^a-z0-9:/\-\s]", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    @api.model
    def _matches_any(self, normalized, candidates):
        if normalized in candidates:
            return True
        padded = " %s " % normalized
        return any(" %s " % candidate in padded for candidate in candidates if len(candidate) > 2)

    @api.model
    def get_resume_message(self, session):
        """Mensaje corto para reanudar una conversación Web tras recargar.

        No reconstruye histórico: únicamente expresa el estado persistente que
        ya es la fuente de verdad del flujo.
        """
        session = self._coerce_session(session)
        if session.state in ("new", "waiting_service"):
            return self._service_question()
        if session.state == "waiting_booking_mode":
            service = session.service_id.display_name if session.service_id else _("el servicio")
            return _(
                "Continuamos con %(service)s. ¿Quieres 1) elegir profesional o 2) reservar con quien tenga la primera disponibilidad?",
                service=service,
            )
        if session.state == "waiting_employee":
            return self._employee_question(session.service_id)
        if session.state == "waiting_time_preference":
            service = session.service_id.display_name if session.service_id else _("el servicio")
            if session.employee_id:
                return _(
                    "Continuamos con %(service)s y %(employee)s. ¿Qué día u horario prefieres?",
                    service=service,
                    employee=session.employee_id.display_name,
                )
            return _(
                "Continuamos con %(service)s buscando la primera disponibilidad. ¿Qué día u horario prefieres?",
                service=service,
            )
        if session.state == "slot_proposed" and session.proposed_employee_id and session.proposed_start:
            return _(
                "Seguimos con la propuesta de %(employee)s el %(start)s. ¿Te viene bien? Responde sí o no.",
                employee=session.proposed_employee_id.display_name,
                start=self._format_session_slot(session),
            )
        if session.state == "waiting_customer_name":
            return _("El hueco está aceptado. Indícame tu nombre y apellidos para confirmar la reserva.")
        if session.state == "ready_to_book":
            return _(
                "Tus datos están preparados para %(service)s con %(employee)s el %(start)s. "
                "Escribe confirmar para reintentar la confirmación de la cita.",
                service=session.service_id.display_name if session.service_id else _("el servicio"),
                employee=session.proposed_employee_id.display_name if session.proposed_employee_id else _("el profesional"),
                start=self._format_session_slot(session),
            )
        if session.state == "booked":
            return _("Esta cita ya está confirmada. Si quieres otra, escribe “nueva reserva”.")
        if session.state == "cancelled":
            return _("Este proceso está cancelado. Escribe “nueva reserva” para empezar otro.")
        if session.state == "expired":
            return _("La reserva anterior caducó por inactividad. Escribe “nueva reserva” para empezar otro proceso.")
        return self._service_question()

    @api.model
    def _service_question(self):
        services = self.env["odoo.ai.appointment.service"].search([("active", "=", True)], order="sequence, name")
        names = ", ".join(services.mapped("name"))
        return _("¿Qué servicio necesitas? Servicios disponibles: %s") % (names or _("ninguno configurado"))

    @api.model
    def _employee_question(self, service):
        employees = service.get_eligible_employees() if service else self.env["hr.employee"]
        names = ", ".join(employees.mapped("name"))
        return _("¿Con qué profesional quieres reservar? Opciones: %s") % (names or _("ninguno configurado"))

    @api.model
    def _reset_session(self, session):
        session.write({
            "state": "waiting_service",
            "service_id": False,
            "booking_mode": False,
            "employee_id": False,
            "preference_text": False,
            "preferred_date_from": False,
            "preferred_date_to": False,
            "preferred_time_from": False,
            "preferred_time_to": False,
            "preference_data": False,
            "proposed_employee_id": False,
            "proposed_start": False,
            "proposed_end": False,
            "customer_name": False,
            "attendance_id": False,
            "booked_at": False,
            "last_activity": fields.Datetime.now(),
        })

    @api.model
    def _format_session_slot(self, session):
        if not session.proposed_start:
            return ""
        value = fields.Datetime.to_datetime(session.proposed_start)
        if not value.tzinfo:
            value = pytz.UTC.localize(value)
        tz_name = session.proposed_employee_id._get_tz() if session.proposed_employee_id else "UTC"
        return value.astimezone(pytz.timezone(tz_name)).strftime("%d/%m/%Y %H:%M")

    @api.model
    def _handled(self, session, reply, action=None, **extra):
        result = {
            "handled": True,
            "fallback": False,
            "reply": reply,
            "state": session.state,
            "session_id": session.id,
            "action": action or False,
        }
        result.update(extra)
        return result

    @api.model
    def _fallback(self, session, reply):
        return {
            "handled": False,
            "fallback": True,
            "reply": reply,
            "state": session.state,
            "session_id": session.id,
            "action": False,
        }

    @api.model
    def _coerce_session(self, session):
        if isinstance(session, int):
            session = self.env["odoo.ai.appointment.session"].browse(session)
        session = session.exists()
        session.ensure_one()
        return session
