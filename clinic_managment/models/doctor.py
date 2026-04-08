from odoo import models, fields, api
from odoo.exceptions import ValidationError


class Doctor(models.Model):
    _name = 'clinic.doctor'
    _description = 'Doctor'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string="Doctor Name")
    phone = fields.Char(string="Phone")
    email = fields.Char(string="Email")
    fees = fields.Float(string="Fees")
    is_available = fields.Boolean(string="Available")
    total_appointment = fields.Integer(string="Total Appointment")
    active = fields.Boolean(default=True, string="Active")

    availability_ids = fields.One2many(
        'clinic.doctor.line',
        'doctor_id',
        string="Availability"
    )
    speciality_id = fields.Many2one(
        'res.speciality', string="Speciality"
    )
    consultation_ids = fields.One2many(
        'clinic.consultation',
        'doctor_id',
        string="Consultations"
    )
    image_1024 = fields.Image(max_width=256, max_height=256)


    # ✅ Moved here — phone/email belong to clinic.doctor, not DoctorLine
    @api.onchange('phone')
    def _onchange_phone(self):
        if self.phone:
            cleaned = self.phone.replace(' ', '')
            if not cleaned.isdigit():
                return {
                    'warning': {
                        'title': 'Invalid Phone Number',
                        'message': 'Phone number must contain digits only. No letters or special characters allowed.'
                    }
                }
            if len(cleaned) != 10:
                return {
                    'warning': {
                        'title': 'Invalid Phone Number',
                        'message': f'Phone number must be exactly 10 digits. You entered {len(cleaned)} digit(s).'
                    }
                }

    @api.onchange('email')
    def _onchange_email(self):
        if self.email:
            email = self.email.strip()
            if '@' not in email:
                return {
                    'warning': {
                        'title': 'Invalid Email',
                        'message': 'Email must contain "@". Example: name@gmail.com'
                    }
                }
            if not email.endswith('@gmail.com'):
                return {
                    'warning': {
                        'title': 'Invalid Email Format',
                        'message': 'Only Gmail addresses are allowed. Email must end with "@gmail.com".'
                    }
                }
            local_part = email.split('@')[0]
            if not local_part:
                return {
                    'warning': {
                        'title': 'Invalid Email',
                        'message': 'Email username cannot be empty. Example: name@gmail.com'
                    }
                }


class DoctorLine(models.Model):
    _name = 'clinic.doctor.line'
    _description = 'Doctor Availability Line'

    doctor_id = fields.Many2one(
        'clinic.doctor',
        string="Doctor",
        required=True
    )
    day = fields.Selection([
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ], string='Day')
    start_time = fields.Float(string='Start Time')
    end_time = fields.Float(string='End Time')

    # ✅ Optional: validate start < end on the line itself
    @api.constrains('start_time', 'end_time')
    def _check_time_range(self):
        for rec in self:
            if rec.start_time and rec.end_time and rec.start_time >= rec.end_time:
                raise ValidationError(
                    "Start time must be earlier than end time for day: %s" % rec.day
                )