from odoo import models, fields


class Prescription(models.Model):
    _name = 'res.prescription'
    _description = 'Prescription'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    consultation_id = fields.Many2one('clinic.consultation', string="Consultation")

    medicine_id = fields.Many2one('product.template', string="Medicine" , domain=[('is_medicine', '=', True)])
    dosage = fields.Char(string="Dosage")
    frequency = fields.Selection([
        ('once_daily', 'Once Daily'),
        ('twice_daily', 'Twice Daily'),
        ('thrice_daily', 'Thrice Daily'),
        ('as_needed', 'As Needed'),
    ], string="Frequency")
    duration = fields.Integer(string="Duration")

