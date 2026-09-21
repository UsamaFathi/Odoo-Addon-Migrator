{
    'name': 'Realistic Odoo 17 Addon',
    'version': '17.0.4.2.1',
    'depends': ['base', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_order_views.xml',
        'reports/report.xml',
    ],
    'assets': {
        'web.pdf_js_lib': ['realistic_17/static/src/js/widget.js'],
    },
}
