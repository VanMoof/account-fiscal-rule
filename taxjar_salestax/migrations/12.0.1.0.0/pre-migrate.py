# © 2017-2020 Vanmoof B.V.
# © 2017-2020 Opener B.V.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from openupgradelib import openupgrade


def migrate(cr, version):
    """ Custom migration, to be excluded from OCA PR """
    if not version or not openupgrade.column_exists(
            cr, 'account_invoice_line', 'tax_amt'):
        return
    openupgrade.rename_models(cr, [('taxjar.salestax', 'taxjar.config')])
    openupgrade.rename_tables(
        cr, [('product_tax_code', 'taxjar_product_code'),
             ('taxjar_salestax', 'taxjar_config'),
             ('taxjar_to_shp_product', 'taxjar_config_shipping_product_rel'),
             ('taxjar_salestax_country_rel', 'taxjar_config_country_rel')])
    openupgrade.logged_query(
        cr, "UPDATE sale_order_line SET taxjar_amount = tax_amt")
    openupgrade.rename_columns(
        cr, {
            'taxjar_config_country_rel': [
                ('taxjar_salestax_id', 'taxjar_config_id'),
            ],
            'taxjar_config_shipping_product_rel': [
                ('taxjar_id', 'taxjar_config_id'),
            ],
            'account_invoice': [
                ('tax_amount', 'taxjar_amount'),
                ('shipping_amt', 'taxjar_shipping_amount'),
            ],
            'account_invoice_line': [('tax_amt', 'taxjar_amount')],
            'product_category': [('tax_code_id', 'taxjar_code_id')],
            'product_template': [('tax_code_id', 'taxjar_code_id')],
            'sale_order': [
                ('tax_amount', 'taxjar_amount'),
                ('tax_location', 'taxjar_policy'),
            ],
            'taxjar_config': [
                ('disable_tax_calculation', 'enable_tax_calculation'),
                ('disable_tax_reporting', 'enable_tax_reporting'),
            ],
            'taxjar_product_code': [('taxjar_code', 'code')],
        })
    cr.execute(
        """ UPDATE taxjar_product_code
        SET code = 'Old Avatax Category' WHERE code IS NULL""")
    if openupgrade.column_exists(
            cr, 'account_invoice', 'invoice_doc_no'):
        cr.execute(
            """ UPDATE account_invoice rf
            SET refund_invoice_id = ai.id
            FROM account_invoice ai
            WHERE ai.refund_invoice_id IS NULL
                AND rf.invoice_doc_no = ai.number
                AND ai.company_id = rf.company_id
                AND ai.partner_id = rf.partner_id; """)

    # Adapt to reverse semantics
    cr.execute(
        """ UPDATE taxjar_config
        SET enable_tax_calculation =
            enable_tax_calculation IS NOT TRUE """)
    cr.execute(
        """ UPDATE taxjar_config
        SET enable_tax_reporting =
            enable_tax_reporting IS NOT TRUE """)

    # Remove obsolete group from views
    cr.execute(
        """ DELETE FROM ir_ui_view_group_rel
        WHERE view_id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module = 'taxjar_salestax'
                AND model = 'ir.ui.view')""")

    # Store the tax amount in the Odoo data model
    openupgrade.logged_query(
        cr,
        """ UPDATE sale_order_line
        SET price_tax = taxjar_amount,
            price_total = price_subtotal + taxjar_amount
        WHERE price_tax = 0 AND taxjar_amount != 0
        """)
    openupgrade.logged_query(
        cr,
        """ UPDATE account_invoice_line
        SET price_total = price_total + taxjar_amount
        WHERE taxjar_amount != 0
        AND price_subtotal = price_total;
        """)
    # Reset removed (and virtually unused) values for taxjar policy
    # (called tax_location in 8.0)
    openupgrade.logged_query(
        cr,
        """ UPDATE sale_order SET taxjar_policy = 'shipping'
        WHERE taxjar_policy IN ('default', 'invoice') """)
