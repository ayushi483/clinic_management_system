from odoo import http, fields
from odoo.http import request, Response
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
import json
import logging
import anthropic
from datetime import datetime
import pytz

_logger = logging.getLogger(__name__)


class ClinicChatbotController(http.Controller):

    @http.route(
        '/api/v19/chatbot/message',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def handle_message(self, **kwargs):
        try:
            raw = request.httprequest.get_data(as_text=True)
            data = json.loads(raw)
            user_message = data.get('message', '').strip()
            conversation_history = data.get('history', [])
            tz_name = data.get('tz_name', 'UTC')

            if not user_message:
                return self._json_response({'error': 'Empty message'}, 400)

            # ── Use Odoo's fields.Datetime.now() (always UTC) ─────────────
            utc_now = fields.Datetime.now()  # returns a naive datetime in UTC

            # ── Convert UTC now → user's local time using pytz ────────────
            try:
                user_tz = pytz.timezone(tz_name)
            except pytz.UnknownTimeZoneError:
                user_tz = pytz.utc

            utc_aware = pytz.utc.localize(utc_now)
            local_now = utc_aware.astimezone(user_tz)
            local_today_str = local_now.strftime('%A, %B %d, %Y')
            local_now_str = local_now.strftime('%Y-%m-%d %H:%M:%S')

            # ── UTC offset in minutes (for prompt info only) ───────────────
            utc_offset_seconds = local_now.utcoffset().total_seconds()
            utc_offset_minutes = int(utc_offset_seconds / 60)

            # ── Fetch doctors ──────────────────────────────────────────────
            doctors = request.env['clinic.doctor'].sudo().search([('active', '=', True)])
            doctor_list = []
            for d in doctors:
                availability = []
                for line in d.availability_ids:
                    def fmt(f):
                        h = int(f)
                        m = int(round((f - h) * 60))
                        period = "AM" if h < 12 else "PM"
                        return f"{h % 12 or 12}:{m:02d} {period}"
                    availability.append({
                        'day': line.day,
                        'start': fmt(line.start_time),
                        'end': fmt(line.end_time),
                    })
                doctor_list.append({
                    'id': d.id,
                    'name': d.name,
                    'speciality': d.speciality_id.name if d.speciality_id else 'General',
                    'is_available': d.is_available,
                    'fees': d.fees,
                    'availability': availability,
                })

            # ── System prompt ──────────────────────────────────────────────
            system_prompt = f"""You are a friendly clinic appointment assistant built into a clinic management system (Odoo).

User's local date & time: {local_today_str} ({local_now_str})
User's timezone: {tz_name} (UTC offset: {utc_offset_minutes:+d} minutes)

IMPORTANT DATETIME RULE:
- All times the user mentions (e.g. "tomorrow at 10 AM") are in THEIR LOCAL TIME ({tz_name}).
- When you output appointment_datetime in BOOKING_READY, convert the user's local time to UTC.
- UTC offset for this user is {utc_offset_minutes:+d} minutes (i.e. UTC = Local time MINUS {utc_offset_minutes} minutes).
- Example: if user says "10:00 AM" in IST (UTC+330 min), output "04:30:00" UTC.
- Format: YYYY-MM-DD HH:MM:SS (UTC, 24-hour).

You handle THREE tasks only:
1. BOOK an appointment
2. VIEW appointment records (by patient ID or doctor)
3. CHECK doctor availability / available hours

AVAILABLE DOCTORS:
{json.dumps(doctor_list, indent=2)}

=== TASK 1: BOOKING ===
Required fields: patient_id (integer), doctor_id (integer), appointment_datetime (YYYY-MM-DD HH:MM:SS in UTC), notes (optional)
- Ask ONE question at a time if info is missing.
- Resolve relative dates ("tomorrow", "next Monday") using the user's local date above.
- Convert the final datetime to UTC before output.
- When ALL fields collected, output EXACTLY (nothing after):

BOOKING_READY:
{{
  "patient_id": <integer>,
  "doctor_id": <integer>,
  "appointment_datetime": "<YYYY-MM-DD HH:MM:SS in UTC>",
  "notes": "<string or empty>"
}}

=== TASK 2: VIEW RECORDS ===
When asked to show records/appointments for a patient or doctor, output EXACTLY:

FETCH_RECORDS:
{{
  "type": "patient" or "doctor",
  "id": <integer>
}}

=== TASK 3: CHECK AVAILABILITY ===
When asked if a doctor is available or what their hours are, output EXACTLY:

CHECK_AVAILABILITY:
{{
  "doctor_id": <integer>,
  "date": "<YYYY-MM-DD in local date, or empty if just asking general hours>"
}}

RULES:
- Be friendly and concise — staff are busy.
- Confirm details before executing any task.
- If you cannot understand, apologize and ask to rephrase.
- Never invent patient names; always ask for patient ID.
- For availability queries you can answer directly from the doctor list above."""

            messages = list(conversation_history) + [
                {"role": "user", "content": user_message}
            ]

            # ── Call Anthropic ─────────────────────────────────────────────
            api_key = request.env['ir.config_parameter'].sudo().get_param(
                'chatbot.anthropic_api_key'
            )
            if not api_key:
                return self._json_response(
                    {'data': {'reply': '⚠️ AI service is not configured. Please contact your system administrator.'}},
                    200
                )

            client = anthropic.Anthropic(api_key=api_key)
            ai_response = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )

            assistant_text = ai_response.content[0].text
            final_reply = assistant_text

            # ── BOOKING ────────────────────────────────────────────────────
            if "BOOKING_READY:" in assistant_text:
                try:
                    json_part = assistant_text.split("BOOKING_READY:")[1].strip()
                    booking_data = json.loads(json_part)

                    patient = request.env['clinic.patient'].sudo().browse(int(booking_data['patient_id']))
                    if not patient.exists():
                        final_reply = f"❌ Patient with ID {booking_data['patient_id']} not found. Please check the ID."
                        return self._json_response({'data': {'reply': final_reply}}, 200)

                    doctor = request.env['clinic.doctor'].sudo().browse(int(booking_data['doctor_id']))
                    if not doctor.exists():
                        final_reply = "❌ Doctor not found. Please choose from the available doctors."
                        return self._json_response({'data': {'reply': final_reply}}, 200)

                    if not doctor.is_available:
                        final_reply = f"❌ Dr. {doctor.name} is currently not available for booking."
                        return self._json_response({'data': {'reply': final_reply}}, 200)

                    # ── Parse & validate datetime using fields.Datetime ────
                    appt_dt_str = booking_data['appointment_datetime']
                    try:
                        # fields.Datetime.from_string validates the format and returns naive UTC datetime
                        appt_dt_utc = fields.Datetime.from_string(appt_dt_str)
                    except Exception:
                        final_reply = "❌ Invalid datetime format received. Please try booking again."
                        return self._json_response({'data': {'reply': final_reply}}, 200)

                    # ── Reject past appointments ───────────────────────────
                    if appt_dt_utc <= fields.Datetime.now():
                        final_reply = "❌ The appointment time is in the past. Please choose a future date and time."
                        return self._json_response({'data': {'reply': final_reply}}, 200)

                    existing = request.env['clinic.appointment'].sudo().search([
                        ('doctor_id', '=', doctor.id),
                        ('appointment_datetime', '=', appt_dt_utc),
                        ('status', 'not in', ['cancel']),
                    ], limit=1)

                    if existing:
                        final_reply = (
                            f"⚠️ Dr. {doctor.name} already has an appointment at that time. "
                            "Please choose a different time slot."
                        )
                        return self._json_response({'data': {'reply': final_reply}}, 200)

                    # ── Create appointment (pass tz via context, datetime is UTC) ──
                    appointment = request.env['clinic.appointment'].sudo().with_context(
                        tz=tz_name
                    ).create({
                        'patient_id': patient.id,
                        'doctor_id': doctor.id,
                        'appointment_datetime': appt_dt_utc,  # naive UTC — Odoo stores as UTC
                        'notes': booking_data.get('notes', ''),
                        'status': 'draft',
                    })
                    appointment.action_confirm()
                    appointment.invalidate_recordset()

                    # ── Display time back in user's local timezone ─────────
                    appt_aware_utc = pytz.utc.localize(appt_dt_utc)
                    appt_local = appt_aware_utc.astimezone(user_tz)
                    display_dt = appt_local.strftime('%A, %B %d, %Y at %I:%M %p')

                    final_reply = (
                        f"✅ Appointment booked successfully!\n\n"
                        f"📋 Reference: {appointment.appointment_code}\n"
                        f"👤 Patient: {patient.name}\n"
                        f"🩺 Doctor: {doctor.name}\n"
                        f"📅 {display_dt} ({tz_name})\n\n"
                        f"A confirmation email has been sent to the patient."
                    )

                except json.JSONDecodeError as e:
                    _logger.error("Booking JSON parse error: %s", e)
                    final_reply = "I collected all details but had a processing error. Please try again."
                except Exception as e:
                    _logger.exception("Booking creation failed")
                    final_reply = f"❌ Booking failed: {str(e)}"

            # ── FETCH RECORDS ──────────────────────────────────────────────
            elif "FETCH_RECORDS:" in assistant_text:
                try:
                    json_part = assistant_text.split("FETCH_RECORDS:")[1].strip()
                    fetch_data = json.loads(json_part)
                    fetch_type = fetch_data.get('type')
                    fetch_id = int(fetch_data.get('id'))

                    if fetch_type == 'patient':
                        patient = request.env['clinic.patient'].sudo().browse(fetch_id)
                        if not patient.exists():
                            final_reply = f"❌ Patient with ID {fetch_id} not found."
                        else:
                            appointments = request.env['clinic.appointment'].sudo().search([
                                ('patient_id', '=', fetch_id)
                            ], order='appointment_datetime desc', limit=10)

                            if not appointments:
                                final_reply = f"No appointments found for patient {patient.name}."
                            else:
                                lines = [f"📋 Appointments for **{patient.name}**:\n"]
                                for appt in appointments:
                                    status_icon = {
                                        'confirmed': '✅',
                                        'done': '✔️',
                                        'cancel': '❌',
                                        'no_show': '⚠️',
                                        'draft': '📝',
                                    }.get(appt.status, '•')

                                    if appt.appointment_datetime:
                                        # Odoo returns naive UTC datetime — localize properly
                                        dt_utc = appt.appointment_datetime
                                        if isinstance(dt_utc, str):
                                            dt_utc = fields.Datetime.from_string(dt_utc)
                                        dt_aware = pytz.utc.localize(dt_utc)
                                        dt_local = dt_aware.astimezone(user_tz)
                                        dt_str = dt_local.strftime('%d %b %Y, %I:%M %p')
                                    else:
                                        dt_str = 'N/A'

                                    lines.append(
                                        f"{status_icon} {appt.appointment_code} — "
                                        f"Dr. {appt.doctor_id.name} — {dt_str} — {appt.status.title()}"
                                    )
                                final_reply = "\n".join(lines)

                    elif fetch_type == 'doctor':
                        doctor = request.env['clinic.doctor'].sudo().browse(fetch_id)
                        if not doctor.exists():
                            final_reply = f"❌ Doctor with ID {fetch_id} not found."
                        else:
                            # Use fields.Datetime.now() for consistent UTC comparison
                            appointments = request.env['clinic.appointment'].sudo().search([
                                ('doctor_id', '=', fetch_id),
                                ('appointment_datetime', '>=', fields.Datetime.now()),
                                ('status', 'not in', ['cancel']),
                            ], order='appointment_datetime asc', limit=10)

                            if not appointments:
                                final_reply = f"No upcoming appointments found for Dr. {doctor.name}."
                            else:
                                lines = [f"📋 Upcoming appointments for **Dr. {doctor.name}**:\n"]
                                for appt in appointments:
                                    if appt.appointment_datetime:
                                        dt_utc = appt.appointment_datetime
                                        if isinstance(dt_utc, str):
                                            dt_utc = fields.Datetime.from_string(dt_utc)
                                        dt_aware = pytz.utc.localize(dt_utc)
                                        dt_local = dt_aware.astimezone(user_tz)
                                        dt_str = dt_local.strftime('%d %b %Y, %I:%M %p')
                                    else:
                                        dt_str = 'N/A'
                                    lines.append(
                                        f"• {appt.appointment_code} — "
                                        f"{appt.patient_id.name} — {dt_str} — {appt.status.title()}"
                                    )
                                final_reply = "\n".join(lines)
                    else:
                        final_reply = "I couldn't determine what records to fetch. Please specify patient ID or doctor ID."

                except Exception as e:
                    _logger.exception("Fetch records error")
                    final_reply = f"❌ Error fetching records: {str(e)}"

            # ── CHECK AVAILABILITY ─────────────────────────────────────────
            elif "CHECK_AVAILABILITY:" in assistant_text:
                try:
                    json_part = assistant_text.split("CHECK_AVAILABILITY:")[1].strip()
                    avail_data = json.loads(json_part)
                    doctor_id = int(avail_data.get('doctor_id'))
                    check_date = avail_data.get('date', '')

                    doctor = request.env['clinic.doctor'].sudo().browse(doctor_id)
                    if not doctor.exists():
                        final_reply = f"❌ Doctor with ID {doctor_id} not found."
                    else:
                        def fmt(f):
                            h = int(f)
                            m = int(round((f - h) * 60))
                            period = "AM" if h < 12 else "PM"
                            return f"{h % 12 or 12}:{m:02d} {period}"

                        avail_lines = doctor.availability_ids
                        if not avail_lines:
                            final_reply = f"Dr. {doctor.name} has no availability schedule configured."
                        else:
                            status_str = "✅ Available" if doctor.is_available else "❌ Currently Unavailable"
                            lines = [f"🩺 **Dr. {doctor.name}** — {status_str}\n"]
                            lines.append("📅 Working Schedule:")
                            for line in avail_lines:
                                lines.append(f"  • {line.day.capitalize()}: {fmt(line.start_time)} – {fmt(line.end_time)}")

                            if check_date:
                                try:
                                    # check_date is in user's local date (YYYY-MM-DD)
                                    dt_local_naive = datetime.strptime(check_date, '%Y-%m-%d')
                                    weekday = dt_local_naive.strftime('%A').lower()
                                    day_slots = avail_lines.filtered(lambda l: l.day == weekday)

                                    # Build UTC boundaries from local date boundaries using pytz
                                    day_start_local = user_tz.localize(
                                        dt_local_naive.replace(hour=0, minute=0, second=0)
                                    )
                                    day_end_local = user_tz.localize(
                                        dt_local_naive.replace(hour=23, minute=59, second=59)
                                    )
                                    day_start_utc = day_start_local.astimezone(pytz.utc).replace(tzinfo=None)
                                    day_end_utc = day_end_local.astimezone(pytz.utc).replace(tzinfo=None)

                                    booked = request.env['clinic.appointment'].sudo().search_count([
                                        ('doctor_id', '=', doctor_id),
                                        ('appointment_datetime', '>=', fields.Datetime.to_string(day_start_utc)),
                                        ('appointment_datetime', '<=', fields.Datetime.to_string(day_end_utc)),
                                        ('status', 'not in', ['cancel']),
                                    ])

                                    lines.append(f"\n📊 For {dt_local_naive.strftime('%A, %B %d, %Y')}:")
                                    if day_slots:
                                        lines.append(f"  ✅ Doctor is scheduled this day")
                                        lines.append(f"  📌 Appointments booked: {booked}")
                                        if doctor.total_appointment:
                                            remaining = doctor.total_appointment - booked
                                            lines.append(f"  🪑 Slots remaining: {remaining} of {doctor.total_appointment}")
                                    else:
                                        lines.append(f"  ❌ Doctor is NOT available on {dt_local_naive.strftime('%A')}s")
                                except ValueError:
                                    pass

                            final_reply = "\n".join(lines)

                except Exception as e:
                    _logger.exception("Check availability error")
                    final_reply = f"❌ Error checking availability: {str(e)}"

            return self._json_response({'data': {'reply': final_reply}}, 200)

        except Exception as e:
            _logger.exception("Chatbot controller error")
            return self._json_response(
                {'data': {'reply': "Something went wrong. Please try again."}},
                200
            )

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data),
            status=status,
            content_type='application/json',
        )