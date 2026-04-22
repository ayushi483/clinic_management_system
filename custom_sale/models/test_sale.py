from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    delivery_ref = fields.Char(string="Delivery Reference")
    invoice_ref = fields.Char(string="Invoice Reference")

    def _prepare_invoice(self):
        res = super()._prepare_invoice()
        res['sale_reference'] = self.invoice_ref
        return res

    def action_confirm(self):
        res = super().action_confirm()
        if self.picking_ids:
            self.picking_ids.update({"sale_reference": self.delivery_reference})

            for picking in self.picking_ids:
                for move in picking.move_ids:
                    move.update({"sale_line_reference": move.sale_line_id.stock_move_reference})
        return res


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    stock_invoice_ref = fields.Char(string="Stock Invoice Reference")
    invoice_line_ref = fields.Char(string="Invoice Line Reference")

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        res['sale_line_reference'] = self.invoice_line_ref
        return res
