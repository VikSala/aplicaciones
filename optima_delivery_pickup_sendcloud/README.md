# Optima Delivery Pickup - Sendcloud

Sendcloud adapter for `optima_delivery_pickup`.

Current development phase (18.0.0.5.1):

- Keeps the stable Phase 1 one-request package validation at final selection.
- Uses Shipping Products to discover compatible synchronized PUDO services for
  the estimated parcel and to read dimensional limits / transit hours.
- Uses the Service Points API for non-mutating discovery of nearby points and
  their distance/opening state.
- Returns **all safely mapped compatible offers** to the core; it never chooses
  the cheapest one.
- A customer-selected offer is carried as an opaque key to the final point
  selection and fixes the exact local Odoo delivery carrier/service.
- If Sendcloud changes a remote method id between discovery and selection, the
  adapter recovers only when the mapping is still unique and unambiguous.
- Exploratory map selection is accepted automatically only when exactly one
  compatible service remains; multiple services require an explicit customer
  choice.
- The hosted Sendcloud picker can be filtered to the compatible carrier(s) and
  pre-positioned on the point the customer is evaluating.

## 18.0.0.4.2 - 18.0.0.4.4

- Stores method-limit snapshots in the order.
- Stabilizes zonal carrier mapping and volatile Sendcloud ids.
- Phase 1 final validation is reduced to one bounded Shipping Products request
  to avoid chained API calls during checkout mutation.

## 18.0.0.5.1

- Adds nearby Service Points discovery using Sendcloud's maximum 50 km search
  radius, returning all compatible points in that area sorted by distance.
- Groups points by compatible Sendcloud carrier/service and exposes distance,
  route price and Sendcloud transit estimate.
- Persists the customer's selected offer key with the point.
- Removes any price-based automatic service selection from the resolver.
- Filters/prefills the hosted picker with `carriers` and `servicePointId` context.

> Note: the earlier experimental 18.0.0.5.0 approach that auto-selected the
> cheapest compatible service is intentionally superseded by 18.0.0.5.1.
