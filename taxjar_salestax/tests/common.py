# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo.tests.common import TransactionCase
from odoo.addons.queue_job.job import Job


class TaxJarCase(TransactionCase):
    def setUp(self):
        super(TaxJarCase, self).setUp()
        self.maxDiff = None
        self.company = self.env.user.company_id
        self.shipping_product = self.env.ref(
            'product.product_product_1').copy(
                default={'name': 'Shipping', 'default_code': 'SHP'})
        self.tax = self.env.ref('taxjar_salestax.account_tax_taxjar')
        self.config = self.env['taxjar.config'].create({
            'company_id': self.company.id,
            'api_key': 'xxx',
            'sandbox': True,
            'shipping_product_ids': [(4, self.shipping_product.id)],
            'address_validation': False,
            'enable_tax_reporting': True,
        })
        self.env['taxjar.product.code'].search([]).unlink()
        self.taxjar_code = self.env['taxjar.product.code'].create({
            'code': 'x20010',
            'name': 'x20010',
        })

    def _run_connector_job(self, job_record):
        return Job.load(self.env, job_record.uuid).perform()
