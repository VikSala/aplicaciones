from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OdooAIAppointmentAvailability(models.AbstractModel):
    _name = "odoo.ai.appointment.availability"
    _description = "Motor de disponibilidad del chatbot de citas"

    @api.model
    def get_available_slots(
        self,
        service,
        employee=None,
        date_from=None,
        date_to=None,
        time_from=None,
        time_to=None,
        limit=50,
        now=None,
    ):
        """Devuelve huecos reales ordenados cronológicamente.

        El motor trabaja con tres fuentes de verdad:
          1. jornada efectiva del empleado (calendario Odoo + ausencias),
          2. asistencias existentes del empleado, que se consideran ocupadas,
          3. fecha/hora actual, para no devolver huecos en el pasado.

        ``date_from`` y ``date_to`` son fechas locales del empleado. Los
        ``time_from`` / ``time_to`` son horas decimales locales (0..24).

        El resultado contiene datetimes UTC *naive*, que es el formato que
        espera fields.Datetime al escribir en Odoo, junto con textos locales
        pensados únicamente para diagnóstico/UI.
        """
        service = self._coerce_record(service, "odoo.ai.appointment.service", "servicio")
        service.ensure_one()

        if employee:
            employee = self._coerce_record(employee, "hr.employee", "empleado")
            employee.ensure_one()
            eligible = service.get_eligible_employees()
            if employee not in eligible:
                raise ValidationError(_(
                    "El empleado %(employee)s no está habilitado para el servicio %(service)s.",
                    employee=employee.display_name,
                    service=service.display_name,
                ))
            employees = employee
        else:
            employees = service.get_eligible_employees()

        if not employees:
            return []

        date_from = fields.Date.to_date(date_from) if date_from else fields.Date.context_today(self)
        if date_to:
            date_to = fields.Date.to_date(date_to)
        else:
            date_to = date_from + timedelta(days=max(service.max_search_days, 1) - 1)

        if date_to < date_from:
            raise ValidationError(_("La fecha hasta no puede ser anterior a la fecha desde."))

        max_allowed_to = date_from + timedelta(days=max(service.max_search_days, 1) - 1)
        if date_to > max_allowed_to:
            date_to = max_allowed_to

        time_from = self._validate_hour(time_from, "Hora desde")
        time_to = self._validate_hour(time_to, "Hora hasta")
        if time_from is not None and time_to is not None and time_to <= time_from:
            raise ValidationError(_("La hora hasta debe ser posterior a la hora desde."))

        limit = max(int(limit or 0), 0)
        if not limit:
            return []

        now_utc = self._as_utc_aware(now or fields.Datetime.now())
        all_slots = []
        for emp in employees.sorted(lambda e: (e.name or "", e.id)):
            all_slots.extend(self._get_employee_slots(
                service=service,
                employee=emp,
                date_from=date_from,
                date_to=date_to,
                time_from=time_from,
                time_to=time_to,
                now_utc=now_utc,
                limit=limit,
            ))

        all_slots.sort(key=lambda slot: (slot["start"], slot["employee_name"], slot["employee_id"]))
        return all_slots[:limit]

    @api.model
    def get_first_available_slot(self, service, employee=None, **kwargs):
        kwargs["limit"] = 1
        slots = self.get_available_slots(service=service, employee=employee, **kwargs)
        return slots[0] if slots else False

    @api.model
    def _get_employee_slots(
        self,
        service,
        employee,
        date_from,
        date_to,
        time_from,
        time_to,
        now_utc,
        limit,
    ):
        tz = pytz.timezone(employee._get_tz())
        local_range_start = tz.localize(datetime.combine(date_from, time.min))
        local_range_end = tz.localize(datetime.combine(date_to + timedelta(days=1), time.min))
        range_start_utc = local_range_start.astimezone(pytz.UTC)
        range_end_utc = local_range_end.astimezone(pytz.UTC)

        not_before_utc = now_utc + timedelta(minutes=service.min_notice_minutes)
        effective_start_utc = max(range_start_utc, not_before_utc)
        if effective_start_utc >= range_end_utc:
            return []

        # Odoo devuelve la jornada efectiva y ya resta las ausencias del
        # calendario (compute_leaves=True dentro de _get_expected_attendances).
        work_intervals = employee._get_expected_attendances(effective_start_utc, range_end_utc)
        occupied_intervals = self._get_occupied_intervals(
            employee=employee,
            start_utc=effective_start_utc,
            end_utc=range_end_utc,
            tz=tz,
        )

        duration = timedelta(minutes=service.duration_minutes)
        step_minutes = service.slot_step_minutes
        slots = []

        for raw_start, raw_end, _meta in work_intervals:
            work_start = self._ensure_aware(raw_start).astimezone(tz)
            work_end = self._ensure_aware(raw_end).astimezone(tz)
            if work_end <= work_start:
                continue

            free_intervals = self._subtract_occupied(
                [(work_start, work_end)],
                occupied_intervals,
            )

            for free_start, free_end in free_intervals:
                candidate = self._ceil_local_datetime(free_start, step_minutes, tz)
                while candidate + duration <= free_end:
                    candidate_end = tz.normalize(candidate + duration)
                    candidate_utc = candidate.astimezone(pytz.UTC)

                    if candidate_utc < not_before_utc:
                        candidate = self._ceil_local_datetime(
                            max(candidate + timedelta(minutes=step_minutes), not_before_utc.astimezone(tz)),
                            step_minutes,
                            tz,
                        )
                        continue

                    if self._matches_time_window(candidate, candidate_end, time_from, time_to):
                        start_naive_utc = candidate_utc.replace(tzinfo=None)
                        end_naive_utc = candidate_end.astimezone(pytz.UTC).replace(tzinfo=None)
                        slots.append({
                            "employee_id": employee.id,
                            "employee_name": employee.display_name,
                            "service_id": service.id,
                            "service_name": service.display_name,
                            "start": start_naive_utc,
                            "end": end_naive_utc,
                            "timezone": employee._get_tz(),
                            "start_local": candidate.strftime("%d/%m/%Y %H:%M"),
                            "end_local": candidate_end.strftime("%d/%m/%Y %H:%M"),
                        })
                        if len(slots) >= limit:
                            return slots

                    candidate = tz.normalize(candidate + timedelta(minutes=step_minutes))

        return slots

    @api.model
    def _get_occupied_intervals(self, employee, start_utc, end_utc, tz):
        """Obtiene cualquier asistencia que bloquee el rango.

        Se consideran ocupadas todas las hr.attendance del empleado, no solo
        las marcadas como cita chatbot. Es coherente con la restricción nativa
        de Odoo: dos asistencias del mismo empleado no pueden solaparse.
        Una asistencia abierta bloquea desde su check_in hasta el final del
        rango consultado.
        """
        start_naive = start_utc.astimezone(pytz.UTC).replace(tzinfo=None)
        end_naive = end_utc.astimezone(pytz.UTC).replace(tzinfo=None)
        attendances = self.env["hr.attendance"].search([
            ("employee_id", "=", employee.id),
            ("check_in", "<", end_naive),
            "|",
            ("check_out", "=", False),
            ("check_out", ">", start_naive),
        ], order="check_in asc, id asc")

        intervals = []
        for attendance in attendances:
            if not attendance.check_in:
                continue
            occupied_start = max(self._as_utc_aware(attendance.check_in), start_utc)
            occupied_end = min(
                self._as_utc_aware(attendance.check_out) if attendance.check_out else end_utc,
                end_utc,
            )
            if occupied_end > occupied_start:
                intervals.append((occupied_start.astimezone(tz), occupied_end.astimezone(tz)))
        return self._merge_intervals(intervals)

    @api.model
    def _subtract_occupied(self, free_intervals, occupied_intervals):
        result = list(free_intervals)
        for occupied_start, occupied_end in occupied_intervals:
            next_result = []
            for free_start, free_end in result:
                if occupied_end <= free_start or occupied_start >= free_end:
                    next_result.append((free_start, free_end))
                    continue
                if occupied_start > free_start:
                    next_result.append((free_start, min(occupied_start, free_end)))
                if occupied_end < free_end:
                    next_result.append((max(occupied_end, free_start), free_end))
            result = next_result
            if not result:
                break
        return result

    @api.model
    def _merge_intervals(self, intervals):
        if not intervals:
            return []
        ordered = sorted(intervals, key=lambda item: item[0])
        merged = [ordered[0]]
        for current_start, current_end in ordered[1:]:
            previous_start, previous_end = merged[-1]
            if current_start <= previous_end:
                merged[-1] = (previous_start, max(previous_end, current_end))
            else:
                merged.append((current_start, current_end))
        return merged

    @api.model
    def _matches_time_window(self, start_dt, end_dt, time_from, time_to):
        start_minutes = start_dt.hour * 60 + start_dt.minute + start_dt.second / 60.0
        end_minutes = end_dt.hour * 60 + end_dt.minute + end_dt.second / 60.0
        # Si la cita cruza de día, el final se expresa por encima de 24h.
        if end_dt.date() > start_dt.date():
            end_minutes += 24 * 60

        if time_from is not None and start_minutes < time_from * 60:
            return False
        if time_to is not None and end_minutes > time_to * 60:
            return False
        return True

    @api.model
    def _ceil_local_datetime(self, value, step_minutes, tz):
        value = value.astimezone(tz)
        minutes = value.hour * 60 + value.minute
        if value.second or value.microsecond:
            minutes += 1
        rounded_minutes = ((minutes + step_minutes - 1) // step_minutes) * step_minutes
        day_offset, minute_of_day = divmod(rounded_minutes, 24 * 60)
        target_date = value.date() + timedelta(days=day_offset)
        naive = datetime.combine(target_date, time.min) + timedelta(minutes=minute_of_day)
        try:
            return tz.localize(naive, is_dst=None)
        except (pytz.NonExistentTimeError, pytz.AmbiguousTimeError):
            # Las transiciones DST suelen caer de madrugada; normalizar desde
            # el instante conocido evita que una excepción invalide la búsqueda.
            delta = naive - value.replace(tzinfo=None)
            return tz.normalize(value + delta)

    @api.model
    def _validate_hour(self, value, label):
        if value is None or value is False:
            return None
        value = float(value)
        if value < 0 or value > 24:
            raise ValidationError(_("%(label)s debe estar entre 00:00 y 24:00.", label=label))
        return value

    @api.model
    def _as_utc_aware(self, value):
        value = fields.Datetime.to_datetime(value)
        if value.tzinfo:
            return value.astimezone(pytz.UTC)
        return pytz.UTC.localize(value)

    @api.model
    def _ensure_aware(self, value):
        if value.tzinfo:
            return value
        return pytz.UTC.localize(value)

    @api.model
    def _coerce_record(self, value, model_name, label):
        if isinstance(value, int):
            value = self.env[model_name].browse(value)
        if not value or value._name != model_name or not value.exists():
            raise ValidationError(_("No se ha indicado un %(label)s válido.", label=label))
        return value
