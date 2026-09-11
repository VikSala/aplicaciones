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
