# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from .common import TaxJarCase
import json
import responses


class TestCategoryImport(TaxJarCase):
    def setUp(self):
        super().setUp()
        self.code = self.env['taxjar.product.code'].create({
            'code': '40050',
            'name': 'Lemon Soda',
            'description': 'Fizzy drinks'
        })

    @responses.activate
    def test_01_category_import(self):
        """ Category import updates existing codes and creates new ones """
        def callback(request):
            response = {
                'categories': [
                    {
                        'product_tax_code': '40050',
                        'name': 'Soft Drinks',
                        'description': 'Soft drinks. Soda and similar drinks.',
                    },
                    {
                        'product_tax_code': '40060',
                        'name': 'Bottled Water',
                        'description': 'Bottled water for human consumption.'
                    },
                    {
                        'product_tax_code': '41000',
                        'name': 'Prepared Foods',
                        'description': 'Ready to eat foods',
                    },
                ],
            }
            return (200, {}, json.dumps(response))

        self.assertEqual(
            self.env['taxjar.product.code'].search([], count=True), 2)
        self.assertEqual(self.code.name, 'Lemon Soda')

        responses.add_callback(
            responses.GET,
            'https://api.sandbox.taxjar.com/v2/categories',
            callback=callback)
        self.config.import_categories()

        # Two new codes are created
        self.assertEqual(
            self.env['taxjar.product.code'].search([], count=True), 4)
        # While the existing one is updated
        self.assertEqual(self.code.name, 'Soft Drinks')
