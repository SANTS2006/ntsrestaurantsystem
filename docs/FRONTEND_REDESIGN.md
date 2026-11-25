# Premium frontend redesign: what changed, what is wired, what is missing

Stack unchanged (React 19, TypeScript, Vite, react-router, lucide-react; no new dependencies). All data comes from the existing API; no
statistic is invented. Where a requested module has no backend, it is listed under "Missing endpoints" and was NOT faked.

## Design language
* Warm hospitality palette: ivory and espresso surfaces, brass (gold) accent, a deep emerald default brand colour. `--brand` is still
  overridden per restaurant, so each tenant keeps its own identity inside the same system. Automatic dark mode (warm charcoal).
* Serif display type (Iowan Old Style / Palatino / Georgia stack) for headings and figures, clean sans body, tabular numerals for money.
  System fonts only: no font download, no third-party request.
* Layered warm shadows, 14 px radii, 44 px touch targets, visible focus rings, reduced-motion support, print styles kept.
* All tokens live in `frontend/src/index.css`; pages pick them up automatically.

## New or rebuilt shared components (`src/ui`)
| Component | Purpose |
|---|---|
| `Shell` | Application shell: dark brand sidebar with grouped navigation, sticky top bar with current page, user menu, off-canvas navigation on tablet and phone. Used by the restaurant workspace and the platform admin. |
| `charts.tsx`: `AreaChart`, `BarList`, `Donut`, `Sparkline` | Dependency-free SVG charts with tooltips on hover and focus, screen-reader text and honest empty states. |
| `Kpi`, `PageHeader`, `Drawer`, `Dropdown`, `SearchInput`, `Pager` | Stat cards, page headers with actions, side drawers, menus, search fields, pagination. |
| existing `Modal`, `Field`, `Toast`, `Skeleton`, `Empty`, `ErrorState` | Restyled through the tokens. |

## Pages redesigned
* **Shell for everyone:** `ManageLayout` (restaurant staff) and `AdminLayout` (platform) now use `Shell`. The menu is grouped (Service, Menu and stock, Business, Website) and shows only what the role may use; a role without access to a URL sees a clear "not available for your role" screen instead of a raw error (the API still enforces every rule).
* **Dashboard:** greeting, period switch (7/30/90 days), branch filter, CSV exports, quick actions, KPI cards with sparkline (collected, booked sales, orders, outstanding), revenue area chart with refunds, order-status donut, payment mix, popular menu items, recent orders, activity feed (audit trail for administrators, staff order activity for managers), stock alerts, branch comparison, cashier performance.
* **Point of sale (`/manage/cashier`):** category chips, product tiles with images, search, option/extras picker, sticky cart with steppers, server-priced totals, order type switch (dine in, takeaway, delivery), payment switch (cash, mobile money, pay later), quick-cash buttons and change due, customer and notes panel, branch selector for administrators and multi-branch managers (the API already accepted `branch_id`; the old screen never sent it), receipt link, shift, table requests and "my sales" tabs.
* **Kitchen display (new, `/manage/kitchen`):** live board (New, Preparing, Ready to go) with ticket age colouring, items, extras and notes, role-checked action buttons, 10-second refresh, branch filter.
* **Orders:** status chips, search, pagination, order detail in a drawer.
* **Reports, Payroll, Catering, Staff, Shifts, Branches, Products, Categories, Inventory, Services, Gallery, Website content, Tables and QR, My pay, platform Restaurants/Plans/Reports/Audit/System/Settings:** new shell, tokens, tables, forms, badges, headers and responsive behaviour.
* **Public restaurant site and marketing site:** inherit the new palette and type.

## API integrations used (all pre-existing)
`/reports/branch/`, `/reports/export/`, `/reports/audit/`, `/orders/manage/` (list, detail, transition, statuses), `/catalog/public/menu/`,
`/orders/quote/`, `/cashier/orders/`, `/cashier/shift/*`, `/cashier/dashboard/`, `/payments/cash/`, `/payments/<id>/refund/`, `/system/*`,
plus every endpoint the untouched pages already used.

## Previously missing endpoints: now built (Session 17)
Reservations and floor plan (zones, table layout, live board, public booking with a private manage link), suppliers and purchase orders, ingredient-level stock with recipes and per-branch ledgers, expenses and invoices (PDF, payments, voiding), POS discounts (percent or amount, reason required, cashier cap enforced by the server), a staff customer directory with append-only notes, and a kitchen list that includes items (`/orders/manage/?include=items`: one request). Screens: Floor and bookings, Stock and purchasing, Expenses and invoices, Customers, public Reserve page; POS discount panel; payroll tax and pension rules; two-step verification.

## Still not built
* Push updates to the kitchen and floor boards (they poll every 10 to 15 seconds; the WebSocket channel carries only cashier QR-request events).
* Drag-and-drop floor-plan drawing (tables are assigned to zones with shape and seat count; coordinates are stored by the API but not edited visually).
* Product image upload from the POS.
* Supplier invoices and three-way matching (a purchase order is linked to the expense you record for it).

## Verification performed
* Unit tests: 31 frontend tests pass (10 new for charts, empty states, drawer, pager, search, KPI, shell navigation and mobile menu). Production build and type-check clean; main bundle about 334 kB (102 kB gzip) with lazy-loaded routes.
* Real browser, signed in as the restaurant administrator, the cashier and the platform administrator: all 18 workspace pages and all platform pages load without console errors; no horizontal overflow at 1440, 820 and 390 px for the pages checked; the mobile menu opens and closes; a real sale (item with option, quick-cash, change due, charge) created an order and receipt; the kitchen board moved real orders between columns; the order drawer opens and closes with Escape; role checks: a cashier's menu shows only Point of sale, Orders, Kitchen display and My pay, and Dashboard and Payroll show "not available" while the API also refuses them.
* Not verified: the screenshot pane was too small for detailed visual inspection, so spacing, colour and typography were checked through layout measurements and code rather than by eye on a full-size display; Safari/Firefox; real tablets; kitchen-role and waiter accounts (none exist in the dev data); print layouts; keyboard-only walkthrough of every page.
