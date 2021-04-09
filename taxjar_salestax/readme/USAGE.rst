US VAT in TaxJar is always a function of the origin address and the delivery
address. You can therefore select on each sale order which address is leading
to determine the delivery address, whereas the origin address is determined
by the address configured on the Odoo warehouse with a fallback on the company
partner.

For this purpose, there is a new warehouse field on the invoice so that it
can provide the correct origin address for invoices that are not linked to a
sale order. For invoices that are linked to a sale order, the warehouse on
the invoice form is ignored.

The destination address can be altered by changing the TaxJar policy on the
sale order. The options are to use the delivery address of the sale order, or
the warehouse address in the case of a shop/warehouse pickup by the customer.

For invoices linked to a sale order, the destination address used for tax
computation is taken from that sale order. For invoices that are not linked
to a sale order the destination is always the customer address on the invoice.

Tax amounts for orders or invoices are fetched for orders and invoices on
demand (clicking Update from TaxJar on the invoice form or the sale order
form), as well as on confirmation of the sale order and the invoice.

Note that the TaxJar tax amounts are collected regardless of the fiscal
position. No taxes need to be present on invoice or order lines. A dedicated
TaxJar placeholder tax will be added automatically.

TaxJar provides an address validation/autocompletion service. When enabled in
the configuration, partner addresses in the supported countries will be
validated and enriched automatically on creation, or on demand with a new
button on one of the tabs on the partner form.
