# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Taxjar integration for sales tax calculation",
    "version": "12.0.1.0.0",
    "author": "Vanmoof B.V.,Opener B.V.,Odoo Community Association (OCA)",
    "summary": "Enables integration with TaxJar tax calculation provider",
    "category": "Accounting & Finance",
    'website': 'https://github.com/OCA/account-fiscal-rule',
    "depends": [
        "queue_job",
        "sale_stock",
    ],
    "data": [
        "data/account_tax.xml",
        "security/ir.model.access.csv",
        "views/account_invoice.xml",
        "views/product_category.xml",
        "views/product_template.xml",
        "views/res_partner.xml",
        "views/sale_order.xml",
        "views/taxjar_config.xml",
        "views/taxjar_product_code.xml",
    ],
    "external_dependencies": {"python": ["taxjar"]},
    "installable": True,
    "license": "AGPL-3",
}
