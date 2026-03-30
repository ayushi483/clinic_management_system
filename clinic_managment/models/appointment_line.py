from odoo import models, fields


class AppointmentLine(models.TransientModel):
    _name = 'appointment.line'
    _description = 'Appointment Report Line'

    appointment_wizard_id = fields.Many2one(
        'appointment.report.wizard',
        string='Appointment Wizard',
        ondelete='cascade',
    )
    # Patient fields
    patient_name = fields.Char(string='Patient Name')
    patient_age = fields.Integer(string='Age')
    patient_address = fields.Text(string='Address')
    phone_number = fields.Char(string='Phone Number')
    email = fields.Char(string='Email')

    # Doctor fields
    doctor_name = fields.Char(string='Doctor')
    doctor_phone = fields.Char(string='Doctor Phone')
    doctor_email = fields.Char(string='Doctor Email')
    doctor_fees = fields.Float(string='Doctor Fees')
    specialty_of_doctor = fields.Char(string='Speciality')

    # Appointment fields
    appointment_code = fields.Char(string='Appointment Code')
    appointment_datetime = fields.Datetime(string='Appointment Date & Time')
    notes = fields.Text(string='Notes')
    status = fields.Char(string='Status')
    total_payment = fields.Float(string='Total Payment')