from odoo import models, fields, api
from datetime import date
import pytz
from datetime import datetime


class ClinicDashboard(models.Model):
    _name = 'clinic.dashboard'
    _description = 'Clinic Dashboard'

    name = fields.Char(default='Dashboard')

    total_patients = fields.Integer(compute='_compute_dashboard_data')
    todays_appointments = fields.Integer(compute='_compute_dashboard_data')
    total_doctors = fields.Integer(compute='_compute_dashboard_data')
    confirmed_appointments = fields.Integer(compute='_compute_dashboard_data')
    cancelled_appointments = fields.Integer(compute='_compute_dashboard_data')
    no_show_appointments = fields.Integer(compute='_compute_dashboard_data')

    def _compute_dashboard_data(self):
        for rec in self:
            Appointment = self.env['clinic.appointment']

            # Get today's date in the user's timezone, then convert boundaries to UTC
            tz = pytz.timezone(self.env.user.tz or 'UTC')
            now_user = datetime.now(tz)

            today_start_user = now_user.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end_user = now_user.replace(hour=23, minute=59, second=59, microsecond=0)

            # Convert to UTC for querying (Odoo stores datetimes in UTC)
            today_start_utc = today_start_user.astimezone(pytz.utc).replace(tzinfo=None)
            today_end_utc = today_end_user.astimezone(pytz.utc).replace(tzinfo=None)

            rec.total_patients = self.env['clinic.patient'].search_count([])
            rec.total_doctors = self.env['clinic.doctor'].search_count([])

            rec.todays_appointments = Appointment.search_count([
                ('appointment_datetime', '>=', today_start_utc),
                ('appointment_datetime', '<=', today_end_utc),
            ])

            rec.confirmed_appointments = Appointment.search_count([('status', '=', 'confirmed')])
            rec.cancelled_appointments = Appointment.search_count([('status', '=', 'cancel')])
            rec.no_show_appointments = Appointment.search_count([('status', '=', 'no_show')])
    def action_open_patients(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'clinic.patient', 'view_mode': 'list,form'}

    def action_open_doctors(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'clinic.doctor', 'view_mode': 'list,form'}

    def action_open_todays(self):
        today = date.today()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'clinic.appointment',
            'view_mode': 'list,form',
            'domain': [
                ('appointment_datetime', '>=', f'{today} 00:00:00'),
                ('appointment_datetime', '<=', f'{today} 23:59:59')
            ]
        }

    def action_open_doctor_wise(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'clinic.appointment',
            'view_mode': 'list,form',
            'context': {'group_by': 'doctor_id'},
        }

    def action_open_confirmed(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'clinic.appointment',
            'view_mode': 'list,form',
            'domain': [('status', '=', 'confirmed')],
            'name': 'Confirmed Appointments',
        }

    def action_open_cancelled(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'clinic.appointment',
            'view_mode': 'list,form',
            'domain': [('status', '=', 'cancel')],
            'name': 'Cancelled Appointments',
        }

    def action_open_no_show(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'clinic.appointment',
            'view_mode': 'list,form',
            'domain': [('status', '=', 'no_show')],
            'name': 'No Show Appointments',
        }

    @api.model_create_multi
    def create(self, vals_list):
        record = self.search([], limit=1)
        if record:
            return record

        return super().create(vals_list)

    @api.model
    def _ensure_single_record(self):
        """Run once via shell to remove duplicate records."""
        records = self.search([])
        if len(records) > 1:
            records[1:].unlink()


class ClinicDashboardDoctorLine(models.Model):
    _name = 'clinic.dashboard.doctor.line'
    _description = 'Dashboard Doctor Line'

    dashboard_id = fields.Many2one('clinic.dashboard', string='Dashboard')
    doctor_id = fields.Many2one('clinic.doctor', string='Doctor')
    appointment_count = fields.Integer(string='Appointments')