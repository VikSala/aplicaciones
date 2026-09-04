# Optima Sendcloud Zonal Test

Diagnostic addon for Odoo 18 + `delivery_sendcloud_oca`.

It does not modify or synchronize shipping methods. It only performs two read-only API calls to Sendcloud and compares them:

1. OCA-style query: `sender_address=all`
2. Zonal query: specific sender address + origin postal code + destination postal code + destination country.

## Use

After installation:

`Sendcloud > Configuration > Wizards > Test Spain Shipping Methods`

Recommended first test:

- Sender Address: your Spanish Sendcloud sender address
- From Postal Code: the real sender postal code (auto-filled)
- Destination Country: Spain
- To Postal Code: `28001`
- Service Point ID: empty
- Carrier Filter: `correos`
- Name Filter: `pudo`

Press **Run Test**.

The full Sendcloud HTTP responses are also recorded by the base connector in `Sendcloud > Logging`.
