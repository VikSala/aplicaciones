from datetime import timedelta
import logging

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


# Namespace estable para pg_advisory_xact_lock(namespace, employee_id).
# El bloqueo solo coordina reservas creadas por este módulo y dura hasta el
# final de la transacción HTTP/WhatsApp actual.
BOOKING_LOCK_NAMESPACE = 20260814


class OdooAIAppointmentBooking(models.AbstractModel):
    _name = "odoo.ai.appointment.booking"
    _description = "Reserva atómica de citas del chatbot"

    @api.model
    def book_session(self, session):
        """Revalida y crea la hr.attendance de una sesión lista para reservar.

        Devuelve un resultado estructurado y no genera texto conversacional:
        esa responsabilidad permanece en `odoo.ai.appointment.conversation`.

        Estados posibles:
          - booked: asistencia creada (o ya creada previamente para la sesión),
          - conflict: el hueco propuesto ya no está disponible,
          - test: sesión del asistente de QA; nunca crea asistencias,
          - invalid: faltan datos estructurales para reservar.
        """
        session = self._coerce_session(session)

        if session.is_test:
            return {"status": "test"}

        if session.attendance_id:
            if session.state != "booked":
                session.write({
                    "state": "booked",
                    "booked_at": session.booked_at or fields.Datetime.now(),
                })
            return {
                "status": "booked",
                "attendance": session.attendance_id,
                "already_booked": True,
            }

        if not (
            session.service_id
            and session.proposed_employee_id
            and session.proposed_start
            and session.proposed_end
            and session.customer_name
        ):
            return {
                "status": "invalid",
                "reason": "missing_booking_data",
            }

        employee = session.proposed_employee_id

        # Dos confirmaciones simultáneas del chatbot para un mismo profesional
        # no pueden atravesar a la vez la revalidación + create().
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (BOOKING_LOCK_NAMESPACE, employee.id),
        )

        # Otra petición podría haber terminado mientras esperábamos el lock.
        session.invalidate_recordset([
            "attendance_id",
            "state",
            "booked_at",
            "proposed_employee_id",
            "proposed_start",
            "proposed_end",
        ])
        if session.attendance_id:
            if session.state != "booked":
                session.write({
                    "state": "booked",
                    "booked_at": session.booked_at or fields.Datetime.now(),
                })
            return {
                "status": "booked",
                "attendance": session.attendance_id,
                "already_booked": True,
            }

        if not self._is_proposed_slot_still_available(session):
            return {
                "status": "conflict",
                "reason": "slot_no_longer_available",
            }

        vals = {
            "employee_id": employee.id,
            "check_in": session.proposed_start,
            "check_out": session.proposed_end,
            "is_chatbot_appointment": True,
            "cliente": session.customer_name,
            "appointment_service_id": session.service_id.id,
            "appointment_session_id": session.id,
        }

        try:
            # Si una validación nativa de hr.attendance detecta un solape en el
            # último instante, el savepoint permite responder con alternativa
            # sin romper toda la petición.
            with self.env.cr.savepoint():
                attendance = self.env["hr.attendance"].sudo().create(vals)
        except ValidationError:
            return {
                "status": "conflict",
                "reason": "attendance_overlap",
            }
        except Exception:
            # Cualquier error inesperado queda contenido por el savepoint. No
            # marcamos la sesión como reservada ni delegamos la decisión a IA.
            _logger.exception(
                "Error creando cita chatbot session=%s employee=%s",
                session.id,
                employee.id,
            )
            return {
                "status": "error",
                "reason": "attendance_create_error",
            }

        session.write({
            "attendance_id": attendance.id,
            "state": "booked",
            "booked_at": fields.Datetime.now(),
            "last_activity": fields.Datetime.now(),
        })
        return {
            "status": "booked",
            "attendance": attendance,
            "already_booked": False,
        }

    @api.model
    def _is_proposed_slot_still_available(self, session):
        service = session.service_id
        employee = session.proposed_employee_id
        if employee not in service.get_eligible_employees():
            return False

        start = fields.Datetime.to_datetime(session.proposed_start)
        end = fields.Datetime.to_datetime(session.proposed_end)
        if not start or not end or end <= start:
            return False

        expected_duration = timedelta(minutes=service.duration_minutes)
        if abs((end - start - expected_duration).total_seconds()) > 1:
            return False

        start_utc = start if start.tzinfo else pytz.UTC.localize(start)
        end_utc = end if end.tzinfo else pytz.UTC.localize(end)
        tz = pytz.timezone(employee._get_tz())
        local_start = start_utc.astimezone(tz)
        local_end = end_utc.astimezone(tz)

        # El motor actual trabaja con ventanas horarias locales de un mismo
        # día. Las citas de este proyecto se generan siempre así.
        if local_start.date() != local_end.date():
            return False

        time_from = local_start.hour + local_start.minute / 60.0 + local_start.second / 3600.0
        time_to = local_end.hour + local_end.minute / 60.0 + local_end.second / 3600.0

        slots = service.get_available_slots(
            employee=employee,
            date_from=local_start.date(),
            date_to=local_start.date(),
            time_from=time_from,
            time_to=time_to,
            limit=20,
            now=fields.Datetime.now(),
        )
        start_naive = start_utc.astimezone(pytz.UTC).replace(tzinfo=None)
        end_naive = end_utc.astimezone(pytz.UTC).replace(tzinfo=None)
        return any(
            fields.Datetime.to_datetime(slot["start"]) == start_naive
            and fields.Datetime.to_datetime(slot["end"]) == end_naive
            and slot["employee_id"] == employee.id
            for slot in slots
        )

    @api.model
    def _coerce_session(self, session):
        if isinstance(session, int):
            session = self.env["odoo.ai.appointment.session"].browse(session)
        session = session.exists()
        session.ensure_one()
        return session
