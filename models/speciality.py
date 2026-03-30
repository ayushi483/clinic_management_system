from odoo import models, fields


class Speciality(models.Model):
    _name = 'res.speciality'
    _description = 'Doctor Speciality'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'


    name = fields.Char(string="Speciality")
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True, string="Active")


