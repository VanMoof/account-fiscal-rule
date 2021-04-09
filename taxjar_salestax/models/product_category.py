# Copyright 2017-2020 Vanmoof B.V.
# Copyright 2017-2020 Opener B.V.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    taxjar_code_id = fields.Many2one(
        'taxjar.product.code', 'TaxJar Code',
        help='Default TaxJar code for products in this category')
