from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from io import BytesIO
import base64
import xlsxwriter
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class Appointment(models.Model):
    _name = 'clinic.appointment'
    _description = 'Appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    patient_id = fields.Many2one('clinic.patient', string="Patient", tracking=True)
    doctor_id = fields.Many2one('clinic.doctor', string="Doctor", tracking=True)
    appointment_datetime = fields.Datetime(string="Appointment Date & Time")

    status = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
        ('no_show', 'No Show'),
    ], default='draft', tracking=True)

    notes = fields.Text()
    appointment_code = fields.Char()

    doctor_fees = fields.Float(
        related='doctor_id.fees',
        string="Doctor Fees",
    )
    invoice_count = fields.Integer(
        string="Invoices",
        compute='_compute_invoice_count'
    )
    consultation_ids = fields.One2many(
        'clinic.consultation',
        'appointment_id',
        string="Consultations"
    )
    consultation_count = fields.Integer(
        string="Consultation Count",
        compute="_compute_consultation_count"
    )
    doctor_speciality = fields.Many2one(
        related='doctor_id.speciality_id',
        string="Speciality",
    )
    doctor_phone = fields.Char(
        related='doctor_id.phone',
        string="Doctor Phone",
    )
    doctor_email = fields.Char(
        related='doctor_id.email',
        string="Doctor Email",
    )
    patient_phone = fields.Char(
        related='patient_id.phone',
        string="Patient Phone",
    )
    patient_email = fields.Char(
        related='patient_id.email',
        string="Patient Email",
    )
    patient_gender = fields.Selection(
        related='patient_id.gender',
        string="Patient Gender",
    )

    def _utc_to_local(self, dt_utc):
        utc_offset = fields.Datetime.now() - datetime.utcnow()
        return dt_utc + utc_offset

    def _format_time(self, float_time):
        """Convert a float hour value to 'H:MM AM/PM' string."""
        hours = int(float_time)
        minutes = int(round((float_time - hours) * 60))
        period = "AM" if hours < 12 else "PM"
        display_hour = hours % 12 or 12
        return f"{display_hour}:{minutes:02d} {period}"


    @api.depends('consultation_ids')
    def _compute_consultation_count(self):
        for rec in self:
            rec.consultation_count = len(rec.consultation_ids)

    @api.depends('appointment_code')
    def _compute_invoice_count(self):
        appointment_codes = self.mapped('appointment_code')

        if not appointment_codes:
            for rec in self:
                rec.invoice_count = 0
            return

        data = self.env['account.move']._read_group(
            domain=[
                ('ref', 'in', appointment_codes),
                ('move_type', '=', 'out_invoice')
            ],
            groupby=['ref'],
            aggregates=['__count']
        )

        count_map = {item[0]: item[1] for item in data}

        for rec in self:
            rec.invoice_count = count_map.get(rec.appointment_code, 0)

    # ─────────────────────────────────────────────
    # CONSTRAINTS / VALIDATIONS
    # ─────────────────────────────────────────────

    @api.constrains('doctor_id', 'appointment_datetime')
    def _check_doctor_availability(self):
        """Validation 1 — Day & time slot check."""
        for rec in self:
            if not rec.doctor_id or not rec.appointment_datetime:
                continue

            # Convert stored UTC → local time using server clock offset
            local_dt = fields.Datetime.context_timestamp(self, rec.appointment_datetime)
            day_key = local_dt.strftime('%A').lower()
            appt_time = local_dt.hour + (local_dt.minute / 60.0)

            availability_lines = rec.doctor_id.availability_ids.filtered(
                lambda l: l.day == day_key
            )

            if not availability_lines:
                available_days = rec.doctor_id.availability_ids.mapped('day')
                available_days_str = ", ".join(
                    d.capitalize() for d in available_days
                ) or "No days configured"

                raise ValidationError(_(
                    "❌ Appointment Not Allowed!\n\n"
                    "Doctor: %s\n"
                    "Requested Day: %s\n\n"
                    "Dr. %s is NOT available on %s.\n"
                    "Available Days: %s\n\n"
                    "Please choose a valid day."
                ) % (
                    rec.doctor_id.name,
                    day_key.capitalize(),
                    rec.doctor_id.name,
                    day_key.capitalize(),
                    available_days_str,
                ))

            is_valid = any(
                line.start_time <= appt_time <= line.end_time
                for line in availability_lines
            )

            if not is_valid:
                time_slots = "\n".join(
                    f"   • {self._format_time(line.start_time)} – {self._format_time(line.end_time)}"
                    for line in availability_lines
                )

                raise ValidationError(_(
                    "❌ Appointment Time Not Allowed!\n\n"
                    "Doctor: %s\n"
                    "Requested Day: %s\n"
                    "Requested Time: %s\n\n"
                    "Dr. %s is available on %s only during:\n%s\n\n"
                    "Please book within the above time slot(s)."
                ) % (
                    rec.doctor_id.name,
                    day_key.capitalize(),
                    self._format_time(appt_time),
                    rec.doctor_id.name,
                    day_key.capitalize(),
                    time_slots,
                ))

    @api.constrains('doctor_id', 'appointment_datetime')
    def _check_doctor_daily_limit(self):
        """Validation 2 — Daily appointment limit."""
        for rec in self:
            if not rec.doctor_id or not rec.appointment_datetime:
                continue

            if not rec.doctor_id.total_appointment:
                continue

            local_dt = fields.Datetime.context_timestamp(self, rec.appointment_datetime)
            # Build UTC day boundaries from local day boundaries
            utc_offset = fields.Datetime.now() - datetime.utcnow()
            day_start_local = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end_local = local_dt.replace(hour=23, minute=59, second=59, microsecond=0)
            day_start_utc = day_start_local - utc_offset
            day_end_utc = day_end_local - utc_offset

            booked_count = self.search_count([
                ('doctor_id', '=', rec.doctor_id.id),
                ('appointment_datetime', '>=', day_start_utc),
                ('appointment_datetime', '<=', day_end_utc),
                ('status', 'not in', ['cancel']),
                ('id', '!=', rec.id),
            ])

            limit = rec.doctor_id.total_appointment

            if booked_count >= limit:
                raise ValidationError(_(
                    "❌ Doctor Fully Booked!\n\n"
                    "Doctor: %s\n"
                    "Date: %s\n"
                    "Max Appointments Allowed: %s\n"
                    "Already Booked: %s\n\n"
                    "Dr. %s has reached the maximum appointment limit for this day.\n"
                    "Please choose a different date."
                ) % (
                    rec.doctor_id.name,
                    local_dt.strftime('%A, %d %B %Y'),
                    limit,
                    booked_count,
                    rec.doctor_id.name,
                ))

    @api.constrains('doctor_id', 'appointment_datetime')
    def _check_doctor_double_booking(self):
        """Validation 3 — Double-booking guard."""
        for rec in self:
            if not rec.doctor_id or not rec.appointment_datetime:
                continue

            existing = self.search([
                ('doctor_id', '=', rec.doctor_id.id),
                ('appointment_datetime', '=', rec.appointment_datetime),
                ('status', 'not in', ['cancel']),
                ('id', '!=', rec.id),
            ])

            if existing:
                local_dt = fields.Datetime.context_timestamp(self, rec.appointment_datetime)
                raise ValidationError(_(
                    "❌ Time Slot Already Taken!\n\n"
                    "Doctor: %s\n"
                    "Requested Slot: %s\n\n"
                    "This time slot is already booked for Dr. %s.\n"
                    "Please select a different time."
                ) % (
                    rec.doctor_id.name,
                    local_dt.strftime('%A, %d %B %Y at %I:%M %p'),
                    rec.doctor_id.name,
                ))

    @api.constrains('appointment_datetime')
    def _check_appointment_future_datetime(self):
        """Validation 4 — Must be a future datetime."""
        for rec in self:
            if not rec.appointment_datetime:
                continue

            local_appt = fields.Datetime.context_timestamp(self, rec.appointment_datetime)
            now_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())

            if local_appt <= now_local:
                fmt = '%A, %d %B %Y at %I:%M %p'
                raise ValidationError(_(
                    "❌ Invalid Appointment Date & Time!\n\n"
                    "Appointment Time : %s\n"
                    "Current Time     : %s\n\n"
                    "Appointments can only be booked for a future date and time.\n"
                    "Please select a valid upcoming slot."
                ) % (
                    local_appt.strftime(fmt),
                    now_local.strftime(fmt),
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('appointment_code'):
                vals['appointment_code'] = 'New'
        return super().create(vals_list)

    def action_confirm(self):
        for rec in self:
            if not rec.appointment_code or rec.appointment_code == 'New':
                seq = self.env['ir.sequence'].sudo().search([
                    ('code', '=', 'clinic.appointment')
                ], limit=1)
                if seq:
                    rec.appointment_code = seq._next()
            rec.status = 'confirmed'
            template = self.env.ref('clinic_managment.email_template_appointment_confirmed', raise_if_not_found=False)
            if template and rec.patient_email:
                template.send_mail(rec.id, force_send=True)

    def action_cancel(self):
        for rec in self:
            rec.status = 'cancel'
            rec.consultation_ids.write({'status': 'cancel'})

            invoices = self.env['account.move'].search([
                ('ref', '=', rec.appointment_code),
                ('move_type', '=', 'out_invoice'),
                ('state', '!=', 'cancel')
            ])

            for invoice in invoices:
                if invoice.state == 'posted':
                    invoice.button_draft()
                invoice.button_cancel()

            template = self.env.ref('clinic_managment.email_template_appointment_cancelled', raise_if_not_found=False)
            if template and rec.patient_email:
                template.send_mail(rec.id, force_send=True)

    def action_no_show(self):
        for rec in self:
            rec.status = 'no_show'

    def action_reset_to_draft(self):
        for rec in self:
            rec.status = 'draft'



    def action_view_consultation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Consultations',
            'res_model': 'clinic.consultation',
            'view_mode': 'list,form',
            'domain': [('appointment_id', '=', self.id)],
            'context': {
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id,
                'default_appointment_id': self.id,
            }
        }

    def action_do_consultation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Consultation',
            'res_model': 'clinic.consultation',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id,
                'default_appointment_id': self.id,
            }
        }

    def action_create_invoice(self):
        self.ensure_one()

        move = self.env['account.move'].search([
            ('ref', '=', self.appointment_code)
        ], limit=1)

        if not move:
            move = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.patient_id.partner_id.id,
                'invoice_origin': self.appointment_code,
                'ref': self.appointment_code,
                'invoice_line_ids': [(0, 0, {
                    'name': 'Doctor Consultation',
                    'quantity': 1,
                    'price_unit': self.doctor_id.fees if self.doctor_id else 0.0,
                })]
            })
            move.action_post()

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoices',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('ref', '=', self.appointment_code)],
        }

    def action_report_appointment(self):
        return self.env.ref("clinic_managment.action_report_appointment").report_action(self)

    def action_download_appointment_excel(self):
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Appointment Report')

        header_format = workbook.add_format({'bold': True, 'border': 1, 'align': 'center'})
        cell_format = workbook.add_format({'border': 1, 'align': 'center'})

        headers = ['No.', 'Patient Name', 'Doctor', 'Appointment Time', 'Total Amount']
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)

        row = 1
        sr_no = 1
        for record in self:
            worksheet.write(row, 0, sr_no, cell_format)
            worksheet.write(row, 1, record.patient_id.name or '', cell_format)
            worksheet.write(row, 2, record.doctor_id.name or '', cell_format)
            worksheet.write(row, 3, str(record.appointment_datetime) or '', cell_format)
            worksheet.write(row, 4, record.total_payment or 0.0, cell_format)
            row += 1
            sr_no += 1

        workbook.close()
        output.seek(0)
        file_data = output.read()

        attachment = self.env['ir.attachment'].create({
            'name': 'appointment_report.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(file_data),
            'res_model': 'clinic.appointment',
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true&filename=appointment_report.xlsx',
            'target': 'new',
        }

    # ─────────────────────────────────────────────
    # SCHEDULER
    # ─────────────────────────────────────────────

    def _cron_mark_no_show(self):
        """
        Scheduled action: automatically mark confirmed appointments as 'No Show'
        if the appointment datetime has passed the grace period (default: 30 minutes).
        """
        grace_minutes = 30  # should be >= cron interval
        grace_deadline = datetime.utcnow() - timedelta(minutes=grace_minutes)
        appointments = self.search([
            ('status', '=', 'confirmed'),
            ('appointment_datetime', '<', grace_deadline),
        ])

        if appointments:
            _logger.info(
                "Auto No-Show Scheduler: marking %d appointment(s) as no_show.",
                len(appointments)
            )
            appointments.write({'status': 'no_show'})