# Optima Delivery Pickup

Generic multi-provider pickup core for Odoo 18 ecommerce.

Current development phase (18.0.0.5.1):

- Phase 1 remains intact: one-parcel logistics validation, packing estimation,
  pickup persistence, atomic point replacement, loading spinner and stable
  carrier/price application.
- Phase 2 separates **discovery** from **selection**. The core exposes a generic
  provider hook and checkout endpoint for customer-facing pickup options.
- Compatible points can be rendered with distance, concrete delivery offers,
  price and estimated transit time.
- The customer chooses the offer; the core never ranks or auto-selects by price.
- The provider picker can then be opened with context for the chosen point and
  offer, while the final `set_point` request keeps the proven Phase 1 atomic
  validation/rating flow.
- The generic option model is provider-neutral so future UPS/GLS/etc. adapters
  can feed the same comparison UI.

Pickup visibility restrictions are still deliberately postponed.

## 18.0.0.4.0

- Adds conservative one-parcel weight/dimension calculation.
- Adds generic provider package validation before carrier/price resolution.
- Shows the calculated logistics profile on the sale order pickup tab.

## 18.0.0.4.1

- Homogeneous quantities use an exhaustive rectangular rows/columns/layers
  search across all unit orientations, minimizing the parcel's longest side,
  then second and third sides.
- Mixed carts optimize each homogeneous product block first and then combine
  those blocks conservatively.

## 18.0.0.4.2

- The sale-order tab becomes **Método de entrega** and is available on every
  quotation/order.
- Adds selected method, suggested packaging and method-limit snapshot.

## 18.0.0.4.4 - 18.0.0.4.6

- Immediate point preview plus circular loading spinner.
- Atomic `set_point` store + validation + price flow.
- Empty carts clear pickup state.
- Network-interruption recovery and one safe retry.
- Checkout confirmation remains blocked until a valid pickup resolution exists.

## 18.0.0.5.1

- Adds provider-neutral `/shop/optima_pickup/options` discovery endpoint.
- Adds normalized customer option groups with distance, price and ETA.
- Adds checkout comparison cards and explicit customer choice.
- Adds contextual provider-picker opening for one offer or all compatible
  carriers.
- No cheapest-service auto-selection is performed by the core.
