from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
from io import BytesIO
import base64
import xlsxwriter

_logger = logging.getLogger(__name__)


class AppointmentWizard(models.TransientModel):
    _name = 'appointment.report.wizard'
    _description = 'Appointment Report Wizard'

    patient_id = fields.Many2one('clinic.patient', string="Patient")
    date_from = fields.Date(string="Date From")
    date_to = fields.Date(string="Date To")
    appointment_line_ids = fields.One2many(
        'appointment.line', 'appointment_wizard_id', string='Report Lines'
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_("Date From must be less than Date To."))

    def _fetch_report_data(self):
        self.ensure_one()

        self.env.cr.execute("""
            SELECT ca.id
            FROM clinic_appointment ca
            LEFT JOIN clinic_patient cp ON cp.id = ca.patient_id
            WHERE
                cp.name ILIKE '%%' || COALESCE(
                    (SELECT name FROM clinic_patient WHERE id = %s), ''
                ) || '%%'
                AND (%s IS NULL OR ca.create_date::date >= %s)
                AND (%s IS NULL OR ca.create_date::date <= %s)
            ORDER BY ca.appointment_datetime ASC
        """, [
            self.patient_id.id if self.patient_id else None,
            self.date_from, self.date_from,
            self.date_to,   self.date_to,
        ])

        appointment_ids = [row[0] for row in self.env.cr.fetchall()]
        _logger.info("AppointmentWizard ► appointments found: %d", len(appointment_ids))

        if not appointment_ids:
            return []

        appointments = self.env['clinic.appointment'].browse(appointment_ids)
        status_map = dict(self.env['clinic.appointment']._fields['status'].selection)

        rows = []
        for appt in appointments:
            rows.append({
                'appointment_wizard_id': self.id,
                'patient_name': appt.patient_id.name or '',
                'patient_age': appt.patient_id.age or 0,
                'patient_address': appt.patient_id.address or '',
                'doctor_name': appt.doctor_id.name or '',
                'doctor_phone': appt.doctor_id.phone or '',
                'doctor_email': appt.doctor_id.email or '',
                'doctor_fees': appt.doctor_id.fees or 0.0,
                'specialty_of_doctor': appt.doctor_speciality.name if appt.doctor_speciality else '',
                'appointment_code': appt.appointment_code or '',
                'appointment_datetime': appt.appointment_datetime,
                'phone_number': appt.patient_id.phone or '',
                'email': appt.patient_id.email or '',
                'notes': appt.notes or '',
                'status': status_map.get(appt.status, appt.status or ''),
                'doctor_fees': appt.doctor_fees if appt.doctor_fees else appt.doctor_id.fees or 0.0,  # ← fix
            })

        return rows

    def _prepare_lines(self):
        self.appointment_line_ids.unlink()
        report_data = self._fetch_report_data()

        if not report_data:
            raise ValidationError(_('No data found for the selected filter.'))

        self.write({'appointment_line_ids': [(0, 0, data) for data in report_data]})

    def action_onscreen_report(self):
        self.ensure_one()
        self._prepare_lines()

        return {
            'name': _('Summary Appointment Report'),
            'type': 'ir.actions.act_window',
            'res_model': 'appointment.line',
            'view_mode': 'list',
            'domain': [('appointment_wizard_id', '=', self.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
            'target': 'current',
        }

    def action_html_report(self):
        self.ensure_one()
        self._prepare_lines()
        return self.env.ref(
            'clinic_managment.action_report_appointment_wizard_html'
        ).report_action(self)

    def action_pdf_report(self):
        self.ensure_one()
        self._prepare_lines()
        return self.env.ref(
            'clinic_managment.action_report_appointment_wizard_pdf'
        ).report_action(self)

    def action_excel_report(self):
        self.ensure_one()
        self._prepare_lines()


        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Appointment Report')
        section_format = workbook.add_format({
            'bold': True, 'font_size': 11, 'bg_color': '#D9E1F2',
            'border': 1, 'valign': 'vcenter',
        })
        label_format = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#F2F2F2',
            'valign': 'vcenter',
        })
        value_format = workbook.add_format({
            'border': 1, 'valign': 'vcenter',
        })
        header_format = workbook.add_format({
            'bold': True, 'border': 1, 'align': 'center',
            'bg_color': '#E6E6E6', 'valign': 'vcenter',
        })
        cell_format = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter',
        })
        cell_left = workbook.add_format({
            'border': 1, 'align': 'left', 'valign': 'vcenter',
        })
        cell_right = workbook.add_format({
            'border': 1, 'align': 'right', 'valign': 'vcenter',
        })
        total_format = workbook.add_format({
            'bold': True, 'border': 1, 'align': 'right',
            'bg_color': '#E6E6E6', 'valign': 'vcenter',
        })

        worksheet.set_column(0, 0, 5)  # S.No
        worksheet.set_column(1, 1, 25)  # labels / appointment code
        worksheet.set_column(2, 2, 25)  # values / speciality
        worksheet.set_column(3, 3, 35)
        worksheet.set_column(4, 4, 15)
        worksheet.set_column(5, 5, 15)

        lines = self.appointment_line_ids
        first = lines[0] if lines else None

        row = 0

        worksheet.merge_range(row, 0, row, 2, 'Patient Information', section_format)
        worksheet.merge_range(row, 3, row, 5, 'Doctor Information', section_format)
        row += 1

        patient_info = [
            ('Name', first.patient_name if first else ''),
            ('Phone', first.phone_number if first else ''),
            ('Email', first.email if first else ''),
            ('Age', first.patient_age if first else ''),
            ('Address', first.patient_address if first else ''),
        ]
        doctor_info = [
            ('Name', first.doctor_name if first else ''),
            ('Speciality', first.specialty_of_doctor if first else ''),
            ('Phone', first.doctor_phone if first else ''),
            ('Email', first.doctor_email if first else ''),
            ('Fees', first.doctor_fees if first else ''),
            ('', ''),
        ]

        for (p_label, p_val), (d_label, d_val) in zip(patient_info, doctor_info):
            worksheet.write(row, 0, p_label, label_format)
            worksheet.merge_range(row, 1, row, 2, p_val, value_format)
            worksheet.write(row, 3, d_label, label_format)
            worksheet.merge_range(row, 4, row, 5, d_val, value_format)
            row += 1

        row += 1  # blank row

        worksheet.merge_range(row, 0, row, 5, 'Appointment Details', section_format)
        row += 1

        headers = ['S.No', 'Appointment Code', 'Speciality', 'Diagnosis / Notes', 'Status', 'Total Payment']
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)
        row += 1

        doctor_fees = 0.0
        for idx, line in enumerate(lines, start=1):
            worksheet.write(row, 0, idx, cell_format)
            worksheet.write(row, 1, line.appointment_code, cell_left)
            worksheet.write(row, 2, line.specialty_of_doctor, cell_left)
            worksheet.write(row, 3, line.notes or '', cell_left)
            worksheet.write(row, 4, line.status, cell_format)
            worksheet.write(row, 5, line.doctor_fees, cell_right)
            doctor_fees += line.doctor_fees  # ← this already uses the corrected value
            row += 1

        worksheet.merge_range(row, 0, row, 4, 'Total', total_format)
        worksheet.write(row, 5, doctor_fees, total_format)

        workbook.close()
        output.seek(0)
        file_data = output.read()

        attachment = self.env['ir.attachment'].create({
            'name': 'appointment_report.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(file_data),
            'res_model': 'appointment.report.wizard',
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true&filename=appointment_report.xlsx',
            'target': 'new',
        }