# Website B2B Private - Phase 4

Cumulative Odoo 18 module.

## Phase 1
- Blocking B2B pricelist (`B2B - SIN VERIFICAR`) with one global fixed-price rule at 1000.
- Automatic assignment on free website signup.
- Central `website.b2b_can_purchase()` authorization rule.

## Phase 2
- Hides prices for public visitors and registered users still assigned to the blocking pricelist.
- Keeps prices visible for customers with a normal pricelist and for internal users.
- Covers shop cards, product page, UoM price, variant surcharges, price-range filter,
  pricelist selector, dynamic product snippets, cart line prices and checkout totals.

## Phase 3
- Hides the header cart and purchase controls for blocked users.
- Disables standard quick-add through `product.product._website_show_quick_add()`.
- Makes `product.product._is_add_to_cart_allowed()` return False for blocked users.
- Adds a hard `sale.order._cart_update()` backend guard.
- Blocks cart/checkout/payment HTTP and JSON flows.

## Phase 4
- Adds `website_sale_stock` as an explicit dependency.
- Sanitizes native `website_sale_stock` combination/configurator responses so real
  `free_qty`, cart-derived stock and stock limits do not reach blocked browsers.
- Hides native availability, low-stock, out-of-stock and stock-notification UI.
- Blocks the stock-notification endpoint for blocked users.
- Protects the supplied custom warehouse stock view server-side through a conditional runtime QWeb inheritance (no hard dependency on a third-party theme/view XML-ID):
  - `x_almacen1_custom`
  - `x_almacen2_custom`
  - `x_transit_stock_custom`
  - `x_almacen_local`
- Keeps the Terms and Conditions cards visible.
- Fixes Phase 3 compatibility with Odoo's stock JS by keeping
  `#o_wsale_cta_wrapper` in the DOM while hiding it with CSS and enforcing the
  purchase restriction in backend/model guards.

## Phase 4 correction 18.0.4.0.1
- Shows the native **Contáctenos** CTA for both public visitors and registered
  users still assigned to the blocking B2B pricelist.
- The CTA points to `/#contacto`.
- The custom warehouse availability remains absent for blocked users, so the
  contact CTA occupies its place before Terms and Conditions.
- Keeps the CTA stable when product variants change by forcing Odoo's native
  `prevent_zero_price_sale` contact mode in blocked combination payloads.

## Phase 4.0.2 placement correction

For blocked visitors and blocked registered users, the module keeps Odoo's native `#contact_us_wrapper` and moves that exact element immediately below **Disponibilidad en nuestros almacenes:**. This avoids duplicate CTAs and keeps the same placement for public and registered-but-unverified users. Verified customers keep the normal stock blocks.


## Phase 4 base correction 18.0.4.1.0
- The canonical blocking pricelist is resolved first by exact name `B2B - SIN VERIFICAR`.
- On install and every module upgrade, the module reuses that record instead of creating a duplicate.
- Ensures one unrestricted `Todos los productos` fixed-price rule at `1000`.
- Existing old global rules on that blocking pricelist are updated to 1000; duplicate global rules are removed.

## Phase 5

Adds state-aware UX notices for public visitors and registered customers pending
commercial validation. Catalogue browsing remains available while explaining
why prices, stock and purchasing controls are unavailable. Blocked cart and
checkout attempts redirect to `/shop?b2b_purchase_blocked=1`, where the same
notice is rendered as a warning.


## Phase 6 - final privacy audit / hardening

Final defense-in-depth additions:

- Neutralizes price fields in variant-combination JSON for blocked sessions.
- Removes product prices from website search/autocomplete results.
- Blocks manual pricelist switching for blocked sessions.
- Ignores hand-crafted min/max price filters and price sorting as inference side channels.
- Blocks product/combo configurator JSON endpoints while the B2B account is blocked.
- Hides the mobile pricelist selector and price sorting entries.
- Dynamically protects the custom `Productos similares` block that renders
  `sim_prod.list_price` directly.

No third-party theme dependency is introduced.
