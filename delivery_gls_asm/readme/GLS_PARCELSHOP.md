GLS Spain ParcelShop search
==========================

This version adds the official GLS Spain ParcelShop locator documented by GLS
in the iClientes ParcelShop integration guide.

Service
-------

* Endpoint: ``https://ws-customer.gls-spain.es/infoasm.asmx``
* Operation: ``GetParcelShopProximosV3``
* Parameters:

  * ``direccion``: address, town or postal code.
  * ``redes``: ``1`` means all available networks; GLS also accepts specific
    network codes.
  * ``pais``: ISO country code, for example ``ES``.

The GLS ``infoasm.wsdl`` supplied by GLS is included in ``api/infoasm.wsdl`` as
technical reference. Runtime requests are sent as SOAP 1.1 directly so the
``xsd:any`` result can be parsed reliably.

Odoo usage
----------

Open a GLS ASM delivery carrier and use **Search GLS ParcelShops**. Enter a
postal code and country. The result wizard shows the GLS point code, network,
name, address, coordinates, distance value returned by GLS and opening hours.

The carrier method ``gls_asm_search_parcelshops(postal_code, country_code,
networks)`` is reusable by a future checkout/pickup module.

This change only locates ParcelShops. It does not yet turn a normal shipment
into a ParcelShop shipment or store a customer selection on a sale/picking.
