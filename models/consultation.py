from odoo import models, fields


class Consultation(models.Model):
    _name = 'clinic.consultation'
    _description = 'Consultation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'


    patient_id = fields.Many2one(
        'clinic.patient',
        string="Patient",
        tracking = True
    )

    doctor_id = fields.Many2one(
        'clinic.doctor',
        string="Doctor",
        tracking=True

    )

    appointment_id = fields.Many2one(
        'clinic.appointment',
        string="Appointment",
        tracking=True
    )
    prescription_ids = fields.One2many('res.prescription', 'consultation_id', string="Prescriptions")
    symptoms = fields.Text(string="Symptoms" ,tracking = True)

    diagnosis = fields.Text(string="Diagnosis",tracking = True)
    date = fields.Datetime(string="Date of Consultation",tracking = True)
    note= fields.Html(string="Note")
    status = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancel', 'Cancelled'),
    ], default='draft',tracking = True)

    def action_consultation_confirm(self):
        for rec in self:
            rec.status = 'confirmed'

            if rec.appointment_id:
                rec.appointment_id.status = 'done'

