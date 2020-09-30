# Copyright 2017-2020 Vanmoof B.V.
# Copyright 2017-2020 Opener B.V.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class TaxjarProductCode(models.Model):
    _name = 'taxjar.product.code'
    _order = 'code asc'
    _description = 'TaxJar Product Code'

    active = fields.Boolean(default=True)
    code = fields.Char(required=True)
    description = fields.Char()
    name = fields.Char(required=True)

    _sql_constraints = [
        ('code_uniq', 'unique (code)',
         'This TaxJar product code already exists'),
    ]
