# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    taxjar_code_id = fields.Many2one(
        'taxjar.product.code', 'TaxJar Code',
        help=('When left empty, the taxjar code of the product category is '
              'used'))
