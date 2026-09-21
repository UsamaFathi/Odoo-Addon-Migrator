from odoo import fields, models

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    legacy_note = fields.Char()

    def legacy_method(self):
        return super().legacy_method()
