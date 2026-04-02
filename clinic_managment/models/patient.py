from datetime import date

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class Patient(models.Model):
    _name = 'clinic.patient'
    _description = 'Patient'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string="Name", tracking=True)
    age = fields.Integer(string="Age", compute='_compute_age', tracking=True)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string="Gender", tracking=True)
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")
    address = fields.Text(string="Address")
    patient_code = fields.Char(string="Patient ID")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirmed'),
    ], string="Status", default='draft', tracking=True)
    appointment_ids = fields.One2many(
        'clinic.appointment',
        'patient_id',
        string="Appointments"
    )
    date_of_birth = fields.Date(string="Date of Birth", tracking=True)
    confirmed_appointment_ids = fields.One2many('clinic.appointment', 'patient_id', string="Medical History",
                                                domain=[('status', '=', 'confirmed')])

    consultation_ids = fields.One2many('clinic.consultation', 'patient_id', string="Consultations History")
    partner_id = fields.Many2one('res.partner', string="Related Partner")
    image_1920 = fields.Image()
    active = fields.Boolean(default=True, string="Active")

    @api.depends('date_of_birth')
    def _compute_age(self):
        for rec in self:
            if rec.date_of_birth:
                today = date.today()
                birth_date = rec.date_of_birth
                rec.age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            else:
                rec.age = 0

    def action_confirm(self):
        for rec in self:
            rec.state = 'confirm'

    # patient.py - fix the create method
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('patient_code'):
                vals['patient_code'] = self.env['ir.sequence'].next_by_code('clinic.patient') or _('New')

            # create partner
            partner = self.env['res.partner'].create({
                'name': vals.get('name'),
                'email': vals.get('email'),
                'phone': vals.get('phone'),
            })

            vals['partner_id'] = partner.id

        records = super().create(vals_list)
        records.action_grant_access()

        return records

    def action_grant_access(self):
        for rec in self:
            partner = rec.partner_id

            if not partner or not partner.email:
                continue

            Users = self.env['res.users'].sudo()

            user = Users.search([
                '|',
                ('partner_id', '=', partner.id),
                ('login', '=', partner.email)
            ], limit=1)

            if user and user.partner_id != partner:
                user.partner_id = partner


            if not user:
                company = partner.company_id or self.env.company
                user = Users.with_company(company.id).create({
                    'name': partner.name,
                    'login': partner.email,
                    'partner_id': partner.id,
                })

                user.action_reset_password()

            group_portal = self.env.ref('base.group_portal')

            user.write({
                'active': True,
                'group_ids': [(6, 0, [group_portal.id])]
            })

    @api.onchange('phone')
    def _onchange_phone(self):
        if self.phone:
            # Remove spaces if any
            cleaned = self.phone.replace(' ', '')

            # Check if all digits
            if not cleaned.isdigit():
                return {
                    'warning': {
                        'title': 'Invalid Phone Number',
                        'message': 'Phone number must contain digits only. No letters or special characters allowed.'
                    }
                }

            # Check length (10 digits for Indian numbers)
            if len(cleaned) != 10:
                return {
                    'warning': {
                        'title': ' Invalid Phone Number',
                        'message': f'Phone number must be exactly 10 digits. You entered {len(cleaned)} digit(s).'
                    }
                }

    @api.onchange('email')
    def _onchange_email(self):
        if self.email:
            email = self.email.strip()

            # Must contain @
            if '@' not in email:
                return {
                    'warning': {
                        'title': ' Invalid Email',
                        'message': 'Email must contain "@". Example: name@gmail.com'
                    }
                }

            # Must end with @gmail.com
            if not email.endswith('@gmail.com'):
                return {
                    'warning': {
                        'title': 'Invalid Email Format',
                        'message': 'Only Gmail addresses are allowed. Email must end with "@gmail.com". Example: name@gmail.com'
                    }
                }

            # Part before @ should not be empty
            local_part = email.split('@')[0]
            if not local_part:
                return {
                    'warning': {
                        'title': 'Invalid Email',
                        'message': 'Email username cannot be empty. Example: name@gmail.com'
                    }
                }
