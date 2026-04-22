from odoo import http, fields
from odoo.http import request, Response
from odoo.exceptions import ValidationError
import json
import logging
import anthropic
from datetime import datetime
import pytz

_logger = logging.getLogger(__name__)


def extract_json(text):
    """Safely extract JSON block from LLM output."""
    if not text:
        raise ValueError("Empty JSON text")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON found in response")
    json_str = text[start:end + 1].strip()
    return json.loads(json_str)


class ClinicChatbotMobileController(http.Controller):

    @http.route(
        '/api/v19/chatbot/mobile/message',
        type='http',
        auth='bearer',
        methods=['POST'],
        csrf=False,
        cors='*',
    )
    def handle_mobile_message(self, **kwargs):
        try:
            raw = request.httprequest.get_data(as_text=True)
            data = json.loads(raw)
            user_message = data.get('message', '').strip()
            conversation_history = data.get('history', [])
            tz_name = data.get('tz_name', 'UTC')
            mobile_patient_id = data.get('patient_id')

            if not user_message:
                return self._json_response({'error': 'Empty message'}, 400)

            # ── Timezone setup ──────────────────────────────────────
            utc_now = fields.Datetime.now()
            try:
                user_tz = pytz.timezone(tz_name)
            except pytz.UnknownTimeZoneError:
                user_tz = pytz.utc
                tz_name = 'UTC'

            utc_aware = pytz.utc.localize(utc_now)
            local_now = utc_aware.astimezone(user_tz)
            local_today_str = local_now.strftime('%A, %B %d, %Y')
            local_now_str = local_now.strftime('%Y-%m-%d %H:%M:%S')

            # ── Build doctor list ───────────────────────────────────
            doctors = request.env['clinic.doctor'].sudo().search(
                [('active', '=', True)]
            )
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

            # ── Patient context ────────────────────────────────────
            patient_context = ""
            patient_name = "the patient"
            if mobile_patient_id:
                patient = request.env['clinic.patient'].sudo().browse(
                    int(mobile_patient_id)
                )
                if patient.exists():
                    patient_name = patient.name or "the patient"
                    patient_context = f"""
LOGGED-IN PATIENT:
- Name: {patient.name}
- Patient ID: {patient.id}
- Email: {patient.email or 'N/A'}
- Phone: {patient.phone or 'N/A'}

Always address the patient by their first name when appropriate.
When they ask about "my appointments" or "my records", fetch records for patient_id {patient.id}.
"""

            # ── System prompt ──────────────────────────────────────
            system_prompt = f"""You are a friendly clinic assistant chatbot.

IMPORTANT RULES:
1. NEVER use markdown formatting: no **, no ##, no *, no backticks, no --- lines.
2. Write plain conversational text only. Use emojis for visual cues instead.
3. Keep responses concise and friendly.
4. Today is {local_today_str}. Current time: {local_now_str}.
5. Always respond as if speaking to {patient_name} personally.
6. When booking, ALWAYS check the doctor's availability schedule and only suggest times within their working hours.

{patient_context}

AVAILABLE DOCTORS:
{json.dumps(doctor_list, indent=2)}

ACTIONS — when you need to perform an action, output ONLY the action tag + JSON on the last line, nothing after it:

To book an appointment:
BOOKING_READY:{{"patient_id": <id>, "doctor_id": <id>, "appointment_datetime": "YYYY-MM-DD HH:MM:SS"}}

To fetch patient records:
FETCH_RECORDS:{{"type": "patient", "id": <patient_id>}}

To check doctor availability:
CHECK_AVAILABILITY:{{"doctor_id": <id>}}

For casual questions, dark mode requests, greetings — just reply conversationally without any action tag.
"""

            messages = list(conversation_history) + [
                {"role": "user", "content": user_message}
            ]

            # ── Get API key ────────────────────────────────────────
            api_key = request.env['ir.config_parameter'].sudo().get_param(
                'chatbot.anthropic_api_key'
            )
            if not api_key:
                return self._json_response(
                    {'data': {'reply': '⚠️ AI service not configured. Please contact support.'}},
                    200
                )

            # ── Call Claude API ────────────────────────────────────
            client = anthropic.Anthropic(api_key=api_key)
            ai_response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )

            assistant_text = ai_response.content[0].text.strip()
            final_reply = assistant_text

            # ── BOOKING ────────────────────────────────────────────
            if "BOOKING_READY:" in assistant_text:
                try:
                    visible_part = assistant_text.split("BOOKING_READY:")[0].strip()
                    json_part = assistant_text.split("BOOKING_READY:")[1].strip()
                    booking_data = extract_json(json_part)

                    patient = request.env['clinic.patient'].sudo().browse(
                        int(booking_data['patient_id'])
                    )
                    doctor = request.env['clinic.doctor'].sudo().browse(
                        int(booking_data['doctor_id'])
                    )

                    if not patient.exists():
                        return self._json_response(
                            {'data': {'reply': '❌ Patient not found. Please try again.'}}, 200)

                    if not doctor.exists():
                        return self._json_response(
                            {'data': {'reply': '❌ Doctor not found. Please try again.'}}, 200)

                    appt_dt_str = booking_data['appointment_datetime']

                    try:
                        local_dt = datetime.strptime(appt_dt_str, '%Y-%m-%d %H:%M:%S')
                        user_tz_obj = pytz.timezone(tz_name) if tz_name else pytz.utc
                        local_dt_aware = user_tz_obj.localize(local_dt)
                        utc_dt_aware = local_dt_aware.astimezone(pytz.utc)
                        appt_dt_utc = utc_dt_aware.replace(tzinfo=None)  # naive UTC for Odoo
                    except Exception:
                        return self._json_response(
                            {'data': {'reply': '❌ Invalid datetime format. Please try again.'}}, 200)

                    if appt_dt_utc <= datetime.utcnow():
                        return self._json_response(
                            {'data': {'reply': '❌ Appointment must be a future date and time.'}}, 200)

                    # Check conflicts
                    existing = request.env['clinic.appointment'].sudo().search([
                        ('doctor_id', '=', doctor.id),
                        ('appointment_datetime', '=', appt_dt_utc),
                        ('status', 'not in', ['cancel']),
                    ], limit=1)
                    if existing:
                        return self._json_response(
                            {'data': {'reply': f'❌ Dr. {doctor.name} already has a booking at that time. Please choose a different slot.'}}, 200)

                    # ── Create appointment ─────────────────────────
                    # Catch ValidationError separately to show doctor's
                    # availability message directly to the user
                    try:
                        appt = request.env['clinic.appointment'].sudo().create({
                            'patient_id': patient.id,
                            'doctor_id': doctor.id,
                            'appointment_datetime': appt_dt_utc,
                            'status': 'draft',
                        })
                        appt.action_confirm()

                    except ValidationError as ve:
                        # Strip Odoo's internal emoji/formatting and return clean message
                        err_msg = ve.args[0] if ve.args else str(ve)
                        return self._json_response(
                            {'data': {'reply': f'❌ {err_msg}'}}, 200)

                    formatted_dt = local_dt.strftime('%A, %B %d at %I:%M %p')
                    final_reply = ""
                    if visible_part:
                        final_reply = visible_part + "\n\n"

                    final_reply += (
                        f"✅ Appointment booked!\n\n"
                        f"👨‍⚕️ Doctor: Dr. {doctor.name}\n"
                        f"📅 Date: {formatted_dt}\n"
                        f"🔖 Code: {appt.appointment_code or 'Pending'}\n\n"
                        f"You'll receive a confirmation shortly."
                    )

                except ValidationError as ve:
                    err_msg = ve.args[0] if ve.args else str(ve)
                    final_reply = f'❌ {err_msg}'
                except Exception:
                    _logger.exception("Booking error")
                    final_reply = "❌ I couldn't complete the booking. Please try again or call the clinic directly."

            # ── FETCH RECORDS ──────────────────────────────────────
            elif "FETCH_RECORDS:" in assistant_text:
                try:
                    visible_part = assistant_text.split("FETCH_RECORDS:")[0].strip()
                    json_part = assistant_text.split("FETCH_RECORDS:")[1].strip()
                    fetch_data = extract_json(json_part)

                    fetch_type = fetch_data.get('type')
                    fetch_id = int(fetch_data.get('id', 0))

                    if fetch_type == 'patient' and fetch_id:
                        appointments = request.env['clinic.appointment'].sudo().search(
                            [('patient_id', '=', fetch_id)],
                            order='appointment_datetime desc',
                            limit=10,
                        )

                        if not appointments:
                            final_reply = (
                                "📋 No appointments found for your account.\n\n"
                                "Would you like to book one now?"
                            )
                        else:
                            lines = ["📋 Here are your recent appointments:\n"]
                            for appt in appointments:
                                dt_str = ''
                                if appt.appointment_datetime:
                                    dt_utc = appt.appointment_datetime
                                    dt_local = pytz.utc.localize(dt_utc).astimezone(user_tz)
                                    dt_str = dt_local.strftime('%b %d, %Y at %I:%M %p')
                                status_map = {
                                    'draft':     '🟡 Pending',
                                    'confirmed': '🟢 Confirmed',
                                    'done':      '✅ Completed',
                                    'cancel':    '❌ Cancelled',
                                    'no_show':   '⚠️ No Show',
                                }
                                status_label = status_map.get(appt.status, appt.status.title())
                                lines.append(
                                    f"• {dt_str}\n"
                                    f"  Dr. {appt.doctor_id.name}\n"
                                    f"  Status: {status_label}"
                                )
                            final_reply = "\n\n".join(lines)
                    else:
                        final_reply = "❌ Could not retrieve records. Please try again."

                except Exception:
                    _logger.exception("Fetch records error")
                    final_reply = "❌ Error retrieving records. Please try again."

            # ── CHECK AVAILABILITY ─────────────────────────────────
            elif "CHECK_AVAILABILITY:" in assistant_text:
                try:
                    visible_part = assistant_text.split("CHECK_AVAILABILITY:")[0].strip()
                    json_part = assistant_text.split("CHECK_AVAILABILITY:")[1].strip()
                    avail_data = extract_json(json_part)

                    doctor_id = int(avail_data.get('doctor_id', 0))
                    doctor = request.env['clinic.doctor'].sudo().browse(doctor_id)

                    if not doctor.exists():
                        final_reply = "❌ Doctor not found. Please check the name and try again."
                    else:
                        def fmt(f):
                            h = int(f)
                            m = int(round((f - h) * 60))
                            period = "AM" if h < 12 else "PM"
                            return f"{h % 12 or 12}:{m:02d} {period}"

                        status_str = "✅ Available" if doctor.is_available else "❌ Currently Unavailable"
                        lines = [f"🗓 Dr. {doctor.name} — {status_str}\n"]
                        if doctor.availability_ids:
                            for line in doctor.availability_ids:
                                lines.append(
                                    f"• {line.day.capitalize()}: {fmt(line.start_time)} - {fmt(line.end_time)}"
                                )
                        else:
                            lines.append("No schedule listed. Please call the clinic.")

                        if visible_part:
                            final_reply = visible_part + "\n\n" + "\n".join(lines)
                        else:
                            final_reply = "\n".join(lines)

                except Exception:
                    _logger.exception("Availability error")
                    final_reply = "❌ Error checking availability. Please try again."

            return self._json_response({'data': {'reply': final_reply}}, 200)

        except Exception:
            _logger.exception("Mobile chatbot error")
            return self._json_response(
                {'data': {'reply': "⚠️ Something went wrong. Please try again."}},
                200,
            )

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data),
            status=status,
            content_type='application/json',
        )