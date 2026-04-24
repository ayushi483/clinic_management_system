from odoo import http, fields
from odoo.http import request, Response
import json
import logging
import re
import requests as http_requests
from datetime import datetime, timedelta
import pytz
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

OLLAMA_URL     = "http://localhost:11434/api/chat"
OLLAMA_MODEL   = "mistral"
OLLAMA_TIMEOUT = 120

# ══════════════════════════════════════════════════════════════════════════
# BOOKING STATE MACHINE
# ══════════════════════════════════════════════════════════════════════════

BOOKING_PHRASES = [
    'book appointment', 'book an appointment', 'i want to book',
    'want to book', 'make appointment', 'schedule appointment',
    'new appointment', 'book a appointment',
]

def _is_booking_intent(msg):
    m = msg.lower().strip()
    return any(ph in m for ph in BOOKING_PHRASES)

def _parse_booking_state(history):
    for m in reversed(history):
        c = m.get('content', '')
        if c.startswith('__BOOKING_STATE__:'):
            try:
                return json.loads(c[len('__BOOKING_STATE__:'):])
            except Exception:
                return None
    return None

def _make_state_msg(state_dict):
    return '__BOOKING_STATE__:' + json.dumps(state_dict)

# ── Utilities ──────────────────────────────────────────────────────────────

def _normalize_code(code):
    return re.sub(r'[\s\-/]', '', code).upper()

def _find_patient(env, raw_code):
    P   = env['clinic.patient'].sudo()
    raw = str(raw_code).strip()
    nrm = _normalize_code(raw)
    for attempt_val, op in [(raw, '='), (nrm, '='), (nrm, 'ilike')]:
        r = P.search([('patient_code', op, attempt_val)], limit=1)
        if r: return r
    digits = re.sub(r'\D', '', raw)
    if digits:
        padded = digits.zfill(4)
        for attempt in [f'PAT{padded}', f'PAT{digits}', padded, digits]:
            r = P.search([('patient_code', '=', attempt)], limit=1)
            if r: return r
        r = P.search([('patient_code', 'ilike', padded)], limit=1)
        if r: return r
    r = P.search([('name', 'ilike', raw)], limit=1)
    if r: return r
    for p in P.search([]):
        if _normalize_code(p.patient_code) == nrm:
            return p
    return P.browse([])

def _find_doctor(env, name):
    return env['clinic.doctor'].sudo().search(
        [('name', 'ilike', str(name).strip()), ('active', '=', True)], limit=1)

def _find_appointment(env, code):
    A = env['clinic.appointment'].sudo()
    r = A.search([('appointment_code', '=', code)], limit=1)
    if not r:
        r = A.search([('appointment_code', '=', _normalize_code(code))], limit=1)
    return r

def _fmt_time(f):
    h = int(f); m = int(round((f - h) * 60))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"

def _parse_datetime_flexible(dt_str):
    for fmt in [
        '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
        '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M',
        '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M',
        '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M',
        '%B %d, %Y %I:%M %p', '%b %d, %Y %I:%M %p',
        '%d %B %Y %H:%M',    '%d %b %Y %H:%M',
    ]:
        try:
            return datetime.strptime(dt_str.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse: {dt_str!r}")

def _parse_json_block(text, keyword):
    try:
        raw = text.split(keyword)[1].strip()
        s   = raw.index('{')
        e   = raw.rindex('}') + 1
        return json.loads(raw[s:e])
    except Exception:
        return None

# ── Doctor / patient helpers ───────────────────────────────────────────────

def _doctor_list(env):
    result = []
    for d in env['clinic.doctor'].sudo().search([('active', '=', True)]):
        avail = [
            {'day': l.day, 'start': _fmt_time(l.start_time), 'end': _fmt_time(l.end_time)}
            for l in d.availability_ids
        ]
        result.append({
            'id':           d.id,
            'name':         d.name,
            'speciality':   d.speciality_id.name if d.speciality_id else 'General',
            'is_available': d.is_available,
            'fees':         int(d.fees) if d.fees else 0,
            'availability': avail,
            'total_slots':  d.total_appointment or 0,
        })
    return result

def _format_doctor_list(env):
    doctors = env['clinic.doctor'].sudo().search([('active', '=', True)])
    if not doctors:
        return "No doctors are currently available."
    lines = ["Here are our available doctors:\n"]
    for d in doctors:
        spec      = d.speciality_id.name if d.speciality_id else 'General'
        status    = "✅ Available" if d.is_available else "❌ Unavailable"
        fees      = f"₹{int(d.fees)}" if d.fees else ""
        avail_str = ", ".join(
            f"{l.day.capitalize()} {_fmt_time(l.start_time)}–{_fmt_time(l.end_time)}"
            for l in d.availability_ids
        ) or "Schedule not set"
        line = f"• **Dr. {d.name}** — {spec} | {status}"
        if fees: line += f" | Fees: {fees}"
        line += f"\n  🕐 {avail_str}"
        lines.append(line)
    lines.append("\n\nWhich doctor would you like to book with?")
    return "\n".join(lines)

def _get_booked_slots(env, doctor_id, date_str, user_tz):
    try:
        dln = datetime.strptime(date_str, '%Y-%m-%d')
        ds  = user_tz.localize(dln.replace(hour=0,  minute=0,  second=0)).astimezone(pytz.utc).replace(tzinfo=None)
        de  = user_tz.localize(dln.replace(hour=23, minute=59, second=59)).astimezone(pytz.utc).replace(tzinfo=None)
        appts = env['clinic.appointment'].sudo().search([
            ('doctor_id', '=', doctor_id),
            ('appointment_datetime', '>=', ds),
            ('appointment_datetime', '<=', de),
            ('status', 'not in', ['cancel']),
        ])
        return [
            pytz.utc.localize(a.appointment_datetime).astimezone(user_tz).strftime('%H:%M')
            for a in appts if a.appointment_datetime
        ]
    except Exception:
        return []

# ── Code extraction ────────────────────────────────────────────────────────

_CODE_RE   = re.compile(r'\b([A-Za-z]{2,5}[\s\-/]*\d{1,6})\b')
_DIGITS_RE = re.compile(r'\b(\d{3,6})\b')

def _extract_code_candidates(text):
    stripped = text.strip()
    codes = _CODE_RE.findall(text)
    if codes: return codes
    if re.match(r'^[A-Za-z0-9\-/]{2,12}$', stripped): return [stripped]
    digits = _DIGITS_RE.findall(text)
    if digits: return digits
    return []

# ── Date / time parsing ────────────────────────────────────────────────────

def _parse_date(text):
    text = text.strip()
    m = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', text)
    if m:
        try:
            datetime.strptime(m.group(1), '%Y-%m-%d')
            return m.group(1)
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b', text)
    if m:
        try:
            d = datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", '%d/%m/%Y')
            return d.strftime('%Y-%m-%d')
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b', text, re.I)
    if not m:
        m = re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\b', text, re.I)
    if m:
        try:
            year = datetime.now().year
            raw  = text.strip()
            for fmt in ['%d %B', '%d %b', '%B %d', '%b %d']:
                try:
                    d = datetime.strptime(raw[:20], fmt)
                    return d.replace(year=year).strftime('%Y-%m-%d')
                except ValueError:
                    pass
        except Exception:
            pass
    return None


def _parse_time(text):
    text = text.strip()
    m = re.search(r'\b(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)?\b', text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        ampm  = (m.group(3) or '').lower()
        if ampm == 'pm' and h != 12: h += 12
        elif ampm == 'am' and h == 12: h = 0
        elif not ampm and 1 <= h <= 7: h += 12
        if 0 <= h < 24 and 0 <= mn < 60:
            return f"{h:02d}:{mn:02d}"
    m = re.search(r'\b(\d{1,2})\s*(am|pm|AM|PM)\b', text)
    if m:
        h    = int(m.group(1))
        ampm = m.group(2).lower()
        if ampm == 'pm' and h != 12: h += 12
        elif ampm == 'am' and h == 12: h = 0
        if 0 <= h < 24:
            return f"{h:02d}:00"
    return None


def _has_conflict(env, doctor_id, appt_utc):
    window_start = appt_utc - timedelta(seconds=59)
    window_end   = appt_utc + timedelta(seconds=59)
    return bool(env['clinic.appointment'].sudo().search([
        ('doctor_id',            '=',      doctor_id),
        ('appointment_datetime', '>=',     window_start),
        ('appointment_datetime', '<=',     window_end),
        ('status',               'not in', ['cancel', 'draft']),
    ], limit=1))


def _booking_state_machine(env, user_message, state, user_tz, tz_name):
    """
    Returns: (reply, new_state, action, action_data, save_to_history)

    FIX: The confirm step now directly calls _execute_booking_from_state
    and returns its result WITHOUT doing an additional conflict check here.
    Previously the flow was:
      confirm step → calls _execute_booking → conflict check inside execute → error
      BUT ALSO the outer _handle() was being called again on the same message → double error.

    Now: confirm step → execute → single error path only.
    """
    step = state.get('step', 'ask_patient')

    if step == 'ask_patient':
        candidates = _extract_code_candidates(user_message)
        if not candidates:
            return ("Please enter your patient code (e.g. **PAT0042**).", state, None, {}, False)
        for raw in candidates:
            patient = _find_patient(env, raw)
            if patient:
                new_state = {**state, 'step': 'ask_doctor',
                             'patient_code': patient.patient_code, 'patient_name': patient.name}
                reply = f"✅ Patient verified: **{patient.name}** ({patient.patient_code})\n\n" + _format_doctor_list(env)
                return reply, new_state, None, {}, True
        nrm = _normalize_code(candidates[0])
        return (f"❌ No patient found with code **{nrm}**. Please double-check and try again.",
                state, None, {}, False)

    if step == 'ask_doctor':
        name = re.sub(r'^(dr\.?\s*|doctor\s*)', '', user_message.strip(), flags=re.I).strip()
        doc  = _find_doctor(env, name) if name else None
        if not name or not doc:
            return (f"I didn't find a doctor matching **{user_message.strip()}**. "
                    f"Please choose from the list:\n\n{_format_doctor_list(env)}",
                    state, None, {}, False)
        if not doc.is_available:
            return (f"**Dr. {doc.name}** is currently unavailable. "
                    f"Please choose an available doctor:\n\n{_format_doctor_list(env)}",
                    state, None, {}, False)
        new_state = {**state, 'step': 'ask_date', 'doctor_name': doc.name,
                     'doctor_id': doc.id, 'doctor_fees': int(doc.fees) if doc.fees else 0}
        return (f"Great! Booking with **Dr. {doc.name}**.\n\n"
                f"What date works for you? (e.g. **2026-04-25** or **25 April**)",
                new_state, None, {}, True)

    if step == 'ask_date':
        date = _parse_date(user_message)
        if not date:
            return ("I couldn't read that date. Please use **2026-04-25** or **25 April**.",
                    state, None, {}, False)
        try:
            if datetime.strptime(date, '%Y-%m-%d').date() < datetime.now().date():
                return ("That date is in the past. Please choose a future date.", state, None, {}, False)
        except Exception:
            pass
        new_state = {**state, 'step': 'ask_time', 'date': date}
        return (f"📅 Date set to **{date}**.\n\n"
                f"What time would you prefer? (e.g. **10:00 AM**, **2:30 PM**, **6:30 PM**)",
                new_state, None, {}, True)

    if step == 'ask_time':
        time_str = _parse_time(user_message)
        if not time_str:
            return ("I couldn't read that time. Please use **10:00 AM**, **14:30**, or **6:30 PM**.",
                    state, None, {}, False)
        new_state = {**state, 'step': 'confirm', 'time': time_str}
        date = state.get('date', ''); doc_nm = state.get('doctor_name', '')
        pat_nm = state.get('patient_name', ''); pat_cd = state.get('patient_code', '')
        fees = state.get('doctor_fees', 0)
        try:
            h, mn     = map(int, time_str.split(':'))
            disp_time = f"{h % 12 or 12}:{mn:02d} {'AM' if h < 12 else 'PM'}"
        except Exception:
            disp_time = time_str
        reply = (f"📋 **Confirm Appointment:**\n\n"
                 f"👤 Patient: **{pat_nm}** ({pat_cd})\n"
                 f"🩺 Doctor: **Dr. {doc_nm}**\n"
                 f"📅 Date: **{date}**\n"
                 f"🕐 Time: **{disp_time}**\n"
                 f"💳 Fees: ₹{fees}\n\n"
                 f"Reply **yes** to confirm or **no** to cancel.")
        return reply, new_state, None, {}, True

    if step == 'confirm':
        msg_lower = user_message.lower().strip()
        if any(w in msg_lower for w in ['yes', 'confirm', 'ok', 'okay', 'sure', 'book', 'yep', 'yeah']):
            # FIX: Execute and return directly — single code path, no double-error possible
            return _execute_booking_from_state(env, state, user_tz, tz_name)
        elif any(w in msg_lower for w in ['no', 'cancel', 'stop', 'abort']):
            return "Booking cancelled. Type **book appointment** to start again.", {}, None, {}, True
        return ("Please reply **yes** to confirm or **no** to cancel.", state, None, {}, False)

    return "Something went wrong. Type **book appointment** to start over.", {}, None, {}, True


def _execute_booking_from_state(env, state, user_tz, tz_name):
    """
    Execute the actual booking. Returns (reply, new_state, action, action_data, save).

    FIX: On any error we return ({}, ...) for new_state to clear the booking state
    from history, so the user can start fresh without getting stuck.
    On conflict: clear state AND give a helpful message to try a different time.
    """
    patient = _find_patient(env, state.get('patient_code', ''))
    if not patient:
        return (f"❌ Patient {state.get('patient_code')} not found. "
                f"Type **book appointment** to start again.", {}, None, {}, True)

    doctor_id = state.get('doctor_id')
    doctor    = env['clinic.doctor'].sudo().browse(doctor_id) if doctor_id else None
    if not doctor or not doctor.exists():
        return ("❌ Doctor not found. Type **book appointment** to start again.",
                {}, None, {}, True)

    try:
        h, mn    = map(int, state['time'].split(':'))
        dt_local = datetime.strptime(f"{state['date']} {h:02d}:{mn:02d}:00", '%Y-%m-%d %H:%M:%S')
        appt_utc = user_tz.localize(dt_local).astimezone(pytz.utc).replace(tzinfo=None)
    except Exception as e:
        return (f"❌ Could not parse appointment time: {e}. "
                f"Type **book appointment** to try again.", {}, None, {}, True)

    if appt_utc <= datetime.utcnow():
        return ("❌ That time is in the past. Type **book appointment** to try again.",
                {}, None, {}, True)

    # FIX: Single conflict check — only here, not duplicated upstream
    if _has_conflict(env, doctor.id, appt_utc):
        try:
            h, mn     = map(int, state['time'].split(':'))
            disp_time = f"{h % 12 or 12}:{mn:02d} {'AM' if h < 12 else 'PM'}"
        except Exception:
            disp_time = state.get('time', '')
        # Clear state so user is not stuck; ask them to re-book with different time
        return (f"❌ **Dr. {doctor.name}** already has a confirmed booking at **{disp_time}** "
                f"on **{state.get('date', '')}**.\n\n"
                f"Please type **book appointment** to try a different time or date.",
                {}, None, {}, True)

    appt = None
    try:
        appt = env['clinic.appointment'].sudo().with_context(tz=tz_name).create({
            'patient_id': patient.id, 'doctor_id': doctor.id,
            'appointment_datetime': appt_utc, 'notes': state.get('notes', ''), 'status': 'draft',
        })
        appt.action_confirm()
        appt.invalidate_recordset()
    except ValidationError as ve:
        if appt:
            try: appt.sudo().unlink()
            except Exception: pass
        return (f"❌ {ve.args[0]}\n\nType **book appointment** to try again.",
                {}, None, {}, True)
    except Exception:
        _logger.exception("Booking creation failed")
        if appt:
            try: appt.sudo().unlink()
            except Exception: pass
        return ("❌ Booking failed. Please try again. Type **book appointment** to start over.",
                {}, None, {}, True)

    display = pytz.utc.localize(appt_utc).astimezone(user_tz).strftime('%A, %B %d, %Y at %I:%M %p')
    reply = (f"✅ **Appointment Booked!**\n\n"
             f"📋 **Ref:** {appt.appointment_code}\n"
             f"👤 **Patient:** {patient.name} ({patient.patient_code})\n"
             f"🩺 **Doctor:** Dr. {doctor.name}\n"
             f"📅 **Date:** {display} ({tz_name})\n"
             f"💳 **Fees:** ₹{int(doctor.fees) if doctor.fees else '—'}")
    return reply, {}, "open_appointment", {"appointment_id": appt.id}, True


# ── Record helpers ─────────────────────────────────────────────────────────

def _fetch_patient_records(env, identifier, user_tz):
    pat = _find_patient(env, identifier)
    if not pat:
        return f"❌ No patient found with code **{identifier.upper()}**."
    appts = env['clinic.appointment'].sudo().search(
        [('patient_id', '=', pat.id)], order='appointment_datetime desc', limit=15)
    if not appts:
        return f"📋 No appointments found for **{pat.name}** ({pat.patient_code})."
    icons = {'confirmed': '✅', 'done': '✔️', 'cancel': '❌', 'no_show': '⚠️', 'draft': '📝'}
    lines = [f"📋 **Appointments for {pat.name} ({pat.patient_code}):**\n"]
    for a in appts:
        dt = a.appointment_datetime
        if isinstance(dt, str): dt = fields.Datetime.from_string(dt)
        dstr = pytz.utc.localize(dt).astimezone(user_tz).strftime('%d %b %Y, %I:%M %p') if dt else 'N/A'
        lines.append(f"{icons.get(a.status,'•')} **{a.appointment_code}** — "
                     f"Dr. {a.doctor_id.name} — {dstr} — {a.status.replace('_',' ').title()}")
    return "\n".join(lines)

def _fetch_doctor_records(env, identifier, user_tz):
    doc = _find_doctor(env, identifier)
    if not doc:
        return f"❌ No doctor found: **{identifier}**."
    appts = env['clinic.appointment'].sudo().search([
        ('doctor_id', '=', doc.id),
        ('appointment_datetime', '>=', fields.Datetime.now()),
        ('status', 'not in', ['cancel']),
    ], order='appointment_datetime asc', limit=15)
    if not appts:
        return f"📋 No upcoming appointments for **Dr. {doc.name}**."
    lines = [f"📋 **Upcoming — Dr. {doc.name}:**\n"]
    for a in appts:
        dt = a.appointment_datetime
        if isinstance(dt, str): dt = fields.Datetime.from_string(dt)
        dstr = pytz.utc.localize(dt).astimezone(user_tz).strftime('%d %b %Y, %I:%M %p') if dt else 'N/A'
        lines.append(f"• **{a.appointment_code}** — {a.patient_id.name} — "
                     f"{dstr} — {a.status.replace('_',' ').title()}")
    return "\n".join(lines)

def _check_availability(env, doctor_name, date_str, user_tz):
    doc = _find_doctor(env, doctor_name)
    if not doc:
        return f"❌ No doctor found: **{doctor_name}**."
    avail  = doc.availability_ids
    if not avail:
        return f"❌ Dr. {doc.name} has no schedule configured."
    status = "✅ Available" if doc.is_available else "❌ Currently Unavailable"
    lines  = [f"**Dr. {doc.name}** — {status}\n**Working Schedule:**"]
    for l in avail:
        lines.append(f"  {l.day.capitalize()}: {_fmt_time(l.start_time)} – {_fmt_time(l.end_time)}")
    if date_str:
        try:
            dln  = datetime.strptime(date_str, '%Y-%m-%d')
            wday = dln.strftime('%A').lower()
            ds   = user_tz.localize(dln.replace(hour=0,  minute=0,  second=0)).astimezone(pytz.utc).replace(tzinfo=None)
            de   = user_tz.localize(dln.replace(hour=23, minute=59, second=59)).astimezone(pytz.utc).replace(tzinfo=None)
            booked = env['clinic.appointment'].sudo().search_count([
                ('doctor_id', '=', doc.id),
                ('appointment_datetime', '>=', ds),
                ('appointment_datetime', '<=', de),
                ('status', 'not in', ['cancel']),
            ])
            lines.append(f"\n**For {dln.strftime('%A, %B %d, %Y')}:**")
            day_slots = avail.filtered(lambda l: l.day == wday)
            if day_slots:
                lines.append(f"  ✅ Working day — Booked: {booked}")
                if doc.total_appointment:
                    lines.append(f"  Slots remaining: {max(0, doc.total_appointment - booked)}/{doc.total_appointment}")
            else:
                lines.append(f"  ❌ Not available on {dln.strftime('%A')}s")
        except ValueError:
            pass
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# SMART INTENT ENGINE
# ══════════════════════════════════════════════════════════════════════════

_NAV_LABELS = {
    'appointments': 'Appointments',
    'patients':     'Patients',
    'doctors':      'Doctors',
    'consultations':'Consultations',
}

_NAV_PATTERNS = [
    (r'\b(show|open|view|go\s+to|list|see|display|manage|navigate|take\s+me\s+to|access|bring\s+up)\b.{0,20}\bappointments?\b', 'appointments'),
    (r'\b(show|open|view|go\s+to|list|see|display|manage|navigate|take\s+me\s+to|access|bring\s+up)\b.{0,20}\bpatients?\b',     'patients'),
    (r'\b(show|open|view|go\s+to|list|see|display|manage|navigate|take\s+me\s+to|access|bring\s+up)\b.{0,20}\bdoctors?\b',      'doctors'),
    (r'\b(show|open|view|go\s+to|list|see|display|manage|navigate|take\s+me\s+to|access|bring\s+up)\b.{0,20}\bconsultations?\b','consultations'),
    (r'\b(all|my|today.?s?|upcoming)\b.{0,10}\bappointments?\b', 'appointments'),
    (r'\b(all|my)\b.{0,10}\bpatients?\b',                         'patients'),
    (r'\b(all|my)\b.{0,10}\bdoctors?\b',                          'doctors'),
    (r'\b(all)\b.{0,10}\bconsultations?\b',                       'consultations'),
    (r'^appointments?$',   'appointments'),
    (r'^patients?$',       'patients'),
    (r'^doctors?$',        'doctors'),
    (r'^consultations?$',  'consultations'),
    (r'\bappointments?\s+(list|page|module|section|tab)\b', 'appointments'),
    (r'\bpatients?\s+(list|page|module|section|tab)\b',     'patients'),
    (r'\bdoctors?\s+(list|page|module|section|tab)\b',      'doctors'),
    (r'\bconsultations?\s+(list|page|module|section|tab)\b','consultations'),
    (r'\bappointment\s+module\b',   'appointments'),
    (r'\bpatient\s+module\b',       'patients'),
    (r'\bdoctor\s+module\b',        'doctors'),
    (r'\bconsultation\s+module\b',  'consultations'),
]

def _check_nav_intent(msg):
    m = msg.lower().strip()
    for pattern, page in _NAV_PATTERNS:
        if re.search(pattern, m):
            return (f"📋 Opening **{_NAV_LABELS[page]}** list…", "navigate", {"page": page})
    return None


_OPEN_PATTERNS = [
    (r'(?:open|show|find|get|view|pull\s+up|display|fetch)\s+patient\s+(.+)',                    'patient'),
    (r'(?:open|show|find|get|view)\s+(?:record|profile|details?)\s+(?:of|for)\s+patient\s+(.+)', 'patient'),
    (r'patient\s+(?:code\s+)?([A-Za-z]{2,5}[\s\-/]*\d{1,6})\b',                                 'patient'),
    (r'^(?:open|show|view|find|get)\s+(pat[\s\-/]*\d{1,6})\s*$',                                 'patient'),
    (r'(?:open|show|view|find|get)\s+(pat[\s\-/]*\d{1,6})\b',                                    'patient'),
    (r'(?:open|show|find|get|view|pull\s+up|display|fetch)\s+appointment\s+([A-Za-z0-9\-/\s]+)', 'appointment'),
    (r'appointment\s+(?:code\s+)?([A-Za-z]{2,5}[\s\-/]*\d{1,6})\b',                             'appointment'),
    (r'^(?:open|show|view|find|get)\s+(app[t]?[\s\-/]*\d{1,6})\s*$',                             'appointment'),
    (r'(?:open|show|view|find|get)\s+(app[t]?[\s\-/]*\d{1,6})\b',                                'appointment'),
    (r'(?:open|show|find|get|view|pull\s+up|display|fetch)\s+(?:dr\.?\s*|doctor\s+)(.+)',        'doctor'),
    (r'(?:dr\.?\s*)([A-Za-z\s]+?)\s+(?:profile|record|details?|info)\b',                         'doctor'),
]


def _check_open_intent(env, msg):
    m = msg.lower().strip()
    for pattern, rtype in _OPEN_PATTERNS:
        match = re.search(pattern, m, re.I)
        if not match:
            continue
        ident = match.group(1).strip().rstrip('.')
        if rtype == 'patient':
            rec = _find_patient(env, ident)
            if rec:
                return (
                    f"✅ Opening patient **{rec.name}** ({rec.patient_code})…",
                    "open_record",
                    {"model": "clinic.patient", "record_id": rec.id},
                )
            if re.search(r'\d', ident):
                return (f"❌ No patient found with code **{_normalize_code(ident)}**.", None, {})
            return None
        elif rtype == 'appointment':
            norm_ident = _normalize_code(ident)
            rec = _find_appointment(env, norm_ident)
            if rec:
                return (
                    f"✅ Opening appointment **{rec.appointment_code}**…",
                    "open_record",
                    {"model": "clinic.appointment", "record_id": rec.id},
                )
            return (f"❌ No appointment found: **{norm_ident}**.", None, {})
        elif rtype == 'doctor':
            rec = _find_doctor(env, ident)
            if rec:
                return (
                    f"✅ Opening Dr. **{rec.name}**…",
                    "open_record",
                    {"model": "clinic.doctor", "record_id": rec.id},
                )
            return None
    return None


def _check_records_intent(env, msg, user_tz):
    m = msg.lower().strip()
    pat_patterns = [
        r'(?:appointments?|records?|history)\s+(?:of|for|by)\s+(?:patient\s+)?([A-Za-z0-9\-/\s]+)',
        r'(?:patient\s+)?([A-Za-z]{2,5}[\s\-/]*\d{1,6})\s+(?:appointments?|records?|history)',
        r'(?:show|get|fetch|display)\s+(?:appointments?|records?)\s+(?:of|for)\s+(?:patient\s+)?([A-Za-z0-9\-/\s]+)',
    ]
    for p in pat_patterns:
        match = re.search(p, m)
        if match:
            ident = match.group(1).strip()
            reply = _fetch_patient_records(env, ident, user_tz)
            return (reply, None, {})
    doc_patterns = [
        r'(?:appointments?|schedule|slots?)\s+(?:of|for)\s+(?:dr\.?\s*|doctor\s+)?([A-Za-z\s]+)',
        r'(?:dr\.?\s*)([A-Za-z\s]+?)\s+(?:appointments?|schedule|slots?)',
        r'(?:show|get|fetch)\s+(?:appointments?|schedule)\s+(?:of|for)\s+(?:dr\.?\s*|doctor\s+)?([A-Za-z\s]+)',
    ]
    for p in doc_patterns:
        match = re.search(p, m)
        if match:
            ident = match.group(1).strip().rstrip('.')
            if len(ident) < 2:
                continue
            reply = _fetch_doctor_records(env, ident, user_tz)
            return (reply, None, {})
    return None


# ── Ollama helpers ─────────────────────────────────────────────────────────

def _ollama_payload(system_prompt, messages, stream=False):
    return {
        "model":   OLLAMA_MODEL,
        "stream":  stream,
        "options": {"temperature": 0.3, "num_predict": 300, "num_ctx": 2048},
        "messages": [{"role": "system", "content": system_prompt}] + messages,
    }

def _call_ollama(system_prompt, messages):
    try:
        res = http_requests.post(OLLAMA_URL, json=_ollama_payload(system_prompt, messages),
                                 timeout=OLLAMA_TIMEOUT)
        res.raise_for_status()
        return res.json()["message"]["content"]
    except http_requests.exceptions.ConnectionError:
        raise RuntimeError("Cannot connect to Ollama. Make sure 'ollama serve' is running.")
    except http_requests.exceptions.Timeout:
        raise RuntimeError("Ollama timed out — please retry.")
    except Exception as e:
        raise RuntimeError(f"Ollama error: {e}")

def _build_general_system_prompt(env):
    sample_pt   = env['clinic.patient'].sudo().search([], limit=1, order='id desc')
    sample_code = sample_pt.patient_code if sample_pt else 'PAT0001'
    sample_ap   = env['clinic.appointment'].sudo().search([], limit=1, order='id desc')
    sample_appt = sample_ap.appointment_code if sample_ap else 'APPT0001'
    prompt = (f"You are a friendly clinic reception assistant. "
              f"Answer questions about the clinic briefly and helpfully. "
              f"For booking, tell user to type 'book appointment'. "
              f"For navigation, tell user to say 'show appointments', 'show patients', 'show doctors'. "
              f"For specific records, tell user to say 'open patient PAT001' or 'open appointment APPT001'. "
              f"Sample codes: patient={sample_code}, appointment={sample_appt}.")
    return prompt, sample_code, sample_appt

DOCTOR_TRIGGERS = [
    'which doctor', 'what doctor', 'list doctor', 'show doctor', 'all doctor',
    'available doctor', 'doctor list', 'who are the doctor', 'doctors available',
]

def _is_doctor_query(msg):
    return any(kw in msg.lower() for kw in DOCTOR_TRIGGERS)

def _clean_reply(text):
    CMDS = ('FETCH_RECORDS:', 'CHECK_AVAILABILITY:', 'NAVIGATE_TO:', 'OPEN_RECORD:')
    lines = text.split('\n')
    result_lines = []; in_json = False; depth = 0
    for line in lines:
        s = line.strip()
        if any(s.startswith(c) for c in CMDS):
            in_json = True; depth = 0; continue
        if in_json:
            depth += s.count('{') - s.count('}')
            if depth <= 0 and ('}' in s or s == ''):
                in_json = False
            continue
        result_lines.append(line)
    result = '\n'.join(result_lines).strip()
    result = re.sub(r'\{[^{}]*?"[a-z_]+".*?\}', '', result, flags=re.DOTALL).strip()
    return result


def _handle(env, user_message, conv_history, user_tz, tz_name):
    """
    Returns (reply, store_msg, action, action_data).

    FIX: Booking state check is authoritative. If there's an active booking state,
    we route ONLY through the state machine — we do NOT fall through to other
    intent checks. This prevents the double-response bug where the conflict
    error was generated by the state machine AND THEN the nav/open/records
    checks also ran and generated a second response.
    """

    # 1. Check for active booking state first — EXCLUSIVE routing
    booking_state = _parse_booking_state(conv_history)

    if booking_state and booking_state.get('step') not in (None, '', 'done'):
        # We're mid-booking — ONLY run the state machine, nothing else
        reply, new_state, action, action_data, _ = _booking_state_machine(
            env, user_message, booking_state, user_tz, tz_name)
        store = _make_state_msg(new_state) if new_state else reply
        return reply, store, action, action_data

    # 2. New booking intent (no active state)
    if _is_booking_intent(user_message):
        initial_state = {'step': 'ask_patient'}
        reply = "Sure! Let's book an appointment.\n\nPlease provide your **patient code** (e.g. PAT0042)."
        return reply, _make_state_msg(initial_state), None, {}

    # 3. Open specific record (checked BEFORE nav so "open pat0042" doesn't hit nav)
    opn = _check_open_intent(env, user_message)
    if opn:
        return opn[0], opn[0], opn[1], opn[2]

    # 4. Navigate to list view
    nav = _check_nav_intent(user_message)
    if nav:
        return nav[0], nav[0], nav[1], nav[2]

    # 5. Inline records query
    rec = _check_records_intent(env, user_message, user_tz)
    if rec:
        return rec[0], rec[0], rec[1], rec[2]

    # 6. Doctor list shortcut
    if _is_doctor_query(user_message):
        reply = _format_doctor_list(env)
        return reply, reply, None, {}

    # 7. Ollama free-chat fallback
    system_prompt, sample_code, sample_appt = _build_general_system_prompt(env)

    STRIP_CMDS = ('FETCH_RECORDS:', 'CHECK_AVAILABILITY:', 'NAVIGATE_TO:', 'OPEN_RECORD:')
    clean_hist = [
        m for m in conv_history
        if not m.get('content', '').startswith('__BOOKING_STATE__:')
        and not (m.get('role') == 'assistant'
                 and any(t in m.get('content', '') for t in STRIP_CMDS))
    ][-6:]

    clean_hist_for_ollama = [
        {"role": m["role"], "content": m["content"]} for m in clean_hist
    ] + [{"role": "user", "content": user_message}]

    try:
        ai_text = _call_ollama(system_prompt, clean_hist_for_ollama)
    except RuntimeError as e:
        reply = f"⚠️ {e}"
        return reply, reply, None, {}

    final_reply = _clean_reply(ai_text)
    action = None; action_data = {}

    if "FETCH_RECORDS:" in ai_text:
        fd = _parse_json_block(ai_text, "FETCH_RECORDS:")
        if fd:
            final_reply = (_fetch_patient_records(env, fd.get('identifier', ''), user_tz)
                           if fd.get('type') == 'patient'
                           else _fetch_doctor_records(env, fd.get('identifier', ''), user_tz))
    elif "CHECK_AVAILABILITY:" in ai_text:
        cd = _parse_json_block(ai_text, "CHECK_AVAILABILITY:")
        if cd:
            final_reply = _check_availability(env, cd.get('doctor_name', ''), cd.get('date', ''), user_tz)
    elif "NAVIGATE_TO:" in ai_text:
        nd = _parse_json_block(ai_text, "NAVIGATE_TO:")
        if nd:
            page = nd.get('page', '').lower()
            if page in _NAV_LABELS:
                final_reply = f"📋 Opening **{_NAV_LABELS[page]}** list…"
                action = "navigate"; action_data = {"page": page}
    elif "OPEN_RECORD:" in ai_text:
        od = _parse_json_block(ai_text, "OPEN_RECORD:")
        if od:
            rtype = od.get('record_type', '').lower(); ident = od.get('identifier', '').strip()
            rec_obj = model = None
            if rtype == 'patient':       rec_obj = _find_patient(env, ident);     model = 'clinic.patient'
            elif rtype == 'appointment': rec_obj = _find_appointment(env, ident); model = 'clinic.appointment'
            elif rtype == 'doctor':      rec_obj = _find_doctor(env, ident);      model = 'clinic.doctor'
            if rec_obj and model:
                final_reply = "Opening record…"
                action = "open_record"; action_data = {"model": model, "record_id": rec_obj.id}

    if not final_reply.strip():
        final_reply = ("I'm not sure about that. "
                       "Try: **show appointments**, **open patient PAT001**, or **book appointment**.")

    return final_reply, final_reply, action, action_data




class ClinicChatbotController(http.Controller):

    @http.route('/api/v19/chatbot/doctors', type='jsonrpc', auth='user',
                methods=['POST'], csrf=False)
    def get_doctors(self, **kwargs):
        try:
            return {'doctors': _doctor_list(request.env)}
        except Exception:
            _logger.exception("get_doctors error")
            return {'doctors': []}

    @http.route('/api/v19/chatbot/booked_slots', type='http', auth='user',
                methods=['POST'], csrf=False)
    def get_booked_slots(self, **kwargs):
        try:
            data    = json.loads(request.httprequest.get_data(as_text=True))
            tz_name = data.get('tz_name', 'UTC')
            user_tz = pytz.timezone(tz_name) if tz_name else pytz.utc
            booked  = _get_booked_slots(request.env, data.get('doctor_id'), data.get('date'), user_tz)
            return self._json({'booked': booked})
        except Exception:
            _logger.exception("booked_slots error")
            return self._json({'booked': []})

    @http.route('/api/v19/chatbot/records', type='http', auth='user',
                methods=['POST'], csrf=False)
    def fetch_records(self, **kwargs):
        try:
            data    = json.loads(request.httprequest.get_data(as_text=True))
            tz_name = data.get('tz_name', 'UTC')
            user_tz = pytz.timezone(tz_name) if tz_name else pytz.utc
            rtype   = data.get('type', 'patient')
            ident   = data.get('identifier', '').strip()
            reply   = (_fetch_patient_records(request.env, ident, user_tz)
                       if rtype == 'patient'
                       else _fetch_doctor_records(request.env, ident, user_tz))
            return self._json({'reply': reply})
        except Exception:
            _logger.exception("fetch_records error")
            return self._json({'reply': '❌ Error fetching records.'})

    @http.route('/api/v19/chatbot/availability', type='http', auth='user',
                methods=['POST'], csrf=False)
    def check_availability_route(self, **kwargs):
        try:
            data    = json.loads(request.httprequest.get_data(as_text=True))
            tz_name = data.get('tz_name', 'UTC')
            user_tz = pytz.timezone(tz_name) if tz_name else pytz.utc
            reply   = _check_availability(request.env, data.get('doctor_name', ''),
                                          data.get('date', ''), user_tz)
            return self._json({'reply': reply})
        except Exception:
            _logger.exception("availability error")
            return self._json({'reply': '❌ Error checking availability.'})

    @http.route('/api/v19/chatbot/open_record', type='http', auth='user',
                methods=['POST'], csrf=False)
    def open_record_route(self, **kwargs):
        try:
            data  = json.loads(request.httprequest.get_data(as_text=True))
            rtype = data.get('type', 'patient')
            ident = data.get('identifier', '').strip()
            env   = request.env
            if rtype == 'patient':
                r = _find_patient(env, ident)
                if not r:
                    return self._json({'reply': f"❌ No patient found: **{ident}**", 'action': None, 'action_data': {}})
                return self._json({'reply': f"✅ Opening **{r.name}** ({r.patient_code})…",
                                   'action': 'open_record', 'action_data': {'model': 'clinic.patient', 'record_id': r.id}})
            elif rtype == 'appointment':
                r = _find_appointment(env, ident)
                if not r:
                    return self._json({'reply': f"❌ No appointment found: **{ident}**", 'action': None, 'action_data': {}})
                return self._json({'reply': f"✅ Opening **{r.appointment_code}**…",
                                   'action': 'open_record', 'action_data': {'model': 'clinic.appointment', 'record_id': r.id}})
            elif rtype == 'doctor':
                r = _find_doctor(env, ident)
                if not r:
                    return self._json({'reply': f"❌ No doctor found: **{ident}**", 'action': None, 'action_data': {}})
                return self._json({'reply': f"✅ Opening Dr. **{r.name}**…",
                                   'action': 'open_record', 'action_data': {'model': 'clinic.doctor', 'record_id': r.id}})
            return self._json({'reply': 'Unknown record type.', 'action': None, 'action_data': {}})
        except Exception:
            _logger.exception("open_record error")
            return self._json({'reply': '❌ Error opening record.', 'action': None, 'action_data': {}})

    @http.route('/api/v19/chatbot/message', type='http', auth='user',
                methods=['POST'], csrf=False)
    def handle_message(self, **kwargs):
        try:
            data           = json.loads(request.httprequest.get_data(as_text=True))
            user_message   = data.get('message', '').strip()
            conv_history   = data.get('history', [])
            tz_name        = data.get('tz_name', 'UTC')
            direct_booking = data.get('direct_booking', None)
            if not user_message and not direct_booking:
                return self._json({'error': 'Empty message'}, 400)
            try:
                user_tz = pytz.timezone(tz_name)
            except Exception:
                user_tz = pytz.utc; tz_name = 'UTC'
            if direct_booking:
                return self._do_direct_booking(direct_booking, user_tz, tz_name)
            reply, store_msg, action, action_data = _handle(
                request.env, user_message, conv_history, user_tz, tz_name)
            return self._json({'data': {
                'reply': reply, 'store_msg': store_msg,
                'action': action, 'action_data': action_data,
            }})
        except Exception:
            _logger.exception("handle_message error")
            return self._json({'data': {'reply': "Something went wrong. Please try again.",
                                        'store_msg': "Something went wrong.",
                                        'action': None, 'action_data': {}}})

    @http.route('/api/v19/chatbot/stream', type='http', auth='user',
                methods=['POST'], csrf=False)
    def handle_stream(self, **kwargs):
        try:
            data         = json.loads(request.httprequest.get_data(as_text=True))
            user_message = data.get('message', '').strip()
            conv_history = data.get('history', [])
            tz_name      = data.get('tz_name', 'UTC')
            if not user_message:
                return self._json({'error': 'Empty message'}, 400)
            try:
                user_tz = pytz.timezone(tz_name)
            except Exception:
                user_tz = pytz.utc; tz_name = 'UTC'
            reply, store_msg, action, action_data = _handle(
                request.env, user_message, conv_history, user_tz, tz_name)

            def generate(reply_text, act, act_data, sm):
                for word in reply_text.split(' '):
                    yield f"data: {json.dumps({'token': word + ' '})}\n\n"
                yield f"data: {json.dumps({'action': act, 'action_data': act_data or {}, 'store_msg': sm})}\n\n"
                yield "data: [DONE]\n\n"

            return Response(generate(reply, action, action_data, store_msg),
                            status=200, content_type='text/event-stream',
                            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
        except Exception:
            _logger.exception("stream endpoint error")
            err_msg = "Something went wrong."
            def err_gen(m):
                yield f"data: {json.dumps({'token': m})}\n\n"
                yield f"data: {json.dumps({'action': None, 'action_data': {}, 'store_msg': m})}\n\n"
                yield "data: [DONE]\n\n"
            return Response(err_gen(err_msg), status=200, content_type='text/event-stream',
                            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    def _do_direct_booking(self, booking, user_tz, tz_name):
        patient = _find_patient(request.env, booking.get('patient_code', ''))
        if not patient:
            return self._json({'data': {
                'reply': f"❌ Patient **{_normalize_code(booking.get('patient_code',''))}** not found.",
                'store_msg': '', 'action': None, 'action_data': {}}})
        doctor = _find_doctor(request.env, booking.get('doctor_name', ''))
        if not doctor:
            return self._json({'data': {'reply': "❌ Doctor not found.",
                                        'store_msg': '', 'action': None, 'action_data': {}}})
        try:
            local_naive = _parse_datetime_flexible(booking.get('appointment_datetime', ''))
        except ValueError:
            return self._json({'data': {'reply': "❌ Could not understand the date/time.",
                                        'store_msg': '', 'action': None, 'action_data': {}}})
        appt_utc = user_tz.localize(local_naive).astimezone(pytz.utc).replace(tzinfo=None)
        if appt_utc <= datetime.utcnow():
            return self._json({'data': {'reply': "❌ The appointment time is in the past.",
                                        'store_msg': '', 'action': None, 'action_data': {}}})
        if _has_conflict(request.env, doctor.id, appt_utc):
            return self._json({'data': {
                'reply': f"❌ Dr. {doctor.name} already has a confirmed booking at that time. "
                         f"Please select a different time slot.",
                'store_msg': '', 'action': None, 'action_data': {}}})
        appt = None
        try:
            appt = request.env['clinic.appointment'].sudo().with_context(tz=tz_name).create({
                'patient_id': patient.id, 'doctor_id': doctor.id,
                'appointment_datetime': appt_utc,
                'notes': booking.get('notes', ''), 'status': 'draft',
            })
            appt.action_confirm()
            appt.invalidate_recordset()
        except ValidationError as ve:
            if appt:
                try: appt.sudo().unlink()
                except Exception: pass
            return self._json({'data': {'reply': f"❌ {ve.args[0]}",
                                        'store_msg': '', 'action': None, 'action_data': {}}})
        except Exception:
            _logger.exception("Direct booking failed")
            if appt:
                try: appt.sudo().unlink()
                except Exception: pass
            return self._json({'data': {'reply': "❌ Booking failed.",
                                        'store_msg': '', 'action': None, 'action_data': {}}})
        display = pytz.utc.localize(appt_utc).astimezone(user_tz).strftime('%A, %B %d, %Y at %I:%M %p')
        reply = (f"✅ **Appointment Booked!**\n\n"
                 f"📋 **Ref:** {appt.appointment_code}\n"
                 f"👤 **Patient:** {patient.name} ({patient.patient_code})\n"
                 f"🩺 **Doctor:** Dr. {doctor.name}\n"
                 f"📅 **Date:** {display} ({tz_name})\n"
                 f"💳 **Fees:** ₹{int(doctor.fees) if doctor.fees else '—'}")
        return self._json({'data': {
            'reply': reply, 'store_msg': reply,
            'action': 'open_appointment', 'action_data': {'appointment_id': appt.id}}})

    @staticmethod
    def _json(data, status=200):
        return Response(json.dumps(data), status=status, content_type='application/json')