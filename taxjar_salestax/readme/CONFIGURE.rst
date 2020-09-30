To configure the API connection, go to the Financial Settings menu and look
for a menu item called "TaxJar API".

Create a new TaxJar API configuration with the details of your TaxJar account.
To be precise, you need to provide an API key for the TaxJar Service.
You need to create the configuration for the Odoo company to which it applies.
In the configuration, please select the countries to determine which orders
are in the scope of the TaxJar tax computation. By default, USA and Canada
are selected here.

There are two different modes to use the API:

* You can have TaxJar calculate the sales tax on your sale orders and sale
  invoices for transactions within a specific Odoo company, and additionally,
* you can have TaxJar declare your taxes, in which case the connector will
  also commit your orders in your TaxJar administration.

Both modes can be disabled in the API configuration.

When you have a working API configuration, you will want to import TaxJar
product codes to link to your products or product categories (if no code is
set on the product there is a fallback on the code of its category). The code
are passed with every order line with that product and it helps TaxJar to
decide which tax category a product belongs to.

Because the partner (address) on the warehouse is used in this module to
determine the origin that is passed to TaxJar, you need to configure these
warehouse addresses properly.

To determine the ledger account for the liable tax amounts, you need to
configure a native Odoo tax with name 'TaxJar' for each company that has a
TaxJar configuration. Please set the 'amount' of the tax to zero.

Amounts are not converted to USD when taxes are fetched from TaxJar. As per
TaxJar documentation
(https://support.taxjar.com/article/947-does-the-taxjar-api-convert-currency)
it is currency agnostic because taxes are applied on the basis of a percentage.
Amounts are converted to USD when orders are committed for tax declaration,
so that the registered data in TaxJar is always in the right currency.
