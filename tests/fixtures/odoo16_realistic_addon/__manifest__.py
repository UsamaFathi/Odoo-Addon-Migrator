{
    'name': 'Realistic Odoo 16 Addon',
    'version': '16.0.3.2.1',
    'depends': ['base', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_order_views.xml',
        'reports/report.xml',
    ],
    'assets': {'web.assets_backend': ['realistic_16/static/src/js/widget.js']},
}
