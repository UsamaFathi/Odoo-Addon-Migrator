from odoo import http


class RealisticController(http.Controller):
    @http.route('/odoo18-realistic/ping', type='http', auth='user')
    def ping(self):
        return 'ok'
