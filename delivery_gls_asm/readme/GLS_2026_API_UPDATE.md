# GLS API update applied locally

This build incorporates the GLS Spain iClientes documentation supplied in September 2026:

- Local WSDL updated to the supplied b2b service definition and current endpoint
  `https://ws-customer.gls-spain.es/b2b.asmx`.
- Label recovery migrated from `EtiquetaEnvio` to `EtiquetaEnvioV2` using
  `uidCliente` + the shipment barcode returned by `GrabaServicios`.
- `GetExpCli` tracking now prefers that barcode when it is available.
- Shipment error messages refreshed with codes documented in the supplied
  shipment examples.

ParcelShop discovery, carrier rating and package-dimension validation are not
implemented because the supplied GLS documents do not provide those APIs.

## ParcelShop search (18.0.1.1.5)

A diagnostic GLS ShipIT ParcelShop search has been added to the carrier configuration.
The integration follows the official REST `findNearestParcelShopForAddress` operation
(`POST <ParcelShop base URL>/address`) and uses HTTP Basic authentication.

The following values are configurable on each GLS carrier:

- ShipIT ParcelShop REST base URL (normally ending in `/backend/rs/parcelshop`).
- ParcelShop service username.
- ParcelShop service password.

The central hostname is intentionally not embedded in the module. GLS documentation
states that central service endpoints are supplied by the customer's GLS contact with
the service credentials.

From the GLS Configuration tab, **Search ParcelShops by Postal Code** opens a wizard
that can search by ZIP/country and optionally limit radius, result count and point type.
Returned values include ParcelShop ID, type, name/address, coordinates, distance and
opening hours. This is a diagnostic/configuration feature and does not yet alter the
checkout or shipment destination automatically.
