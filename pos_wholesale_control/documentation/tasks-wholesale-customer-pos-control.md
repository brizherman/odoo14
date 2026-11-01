# Wholesale Customer POS Control — Implementation Tasks

## Relevant Files

- `pos_wholesale_control/__init__.py` - Initializes the independent custom module.
- `pos_wholesale_control/__manifest__.py` - Declares dependencies on `point_of_sale` and `alta_mayoristas`, plus security, views, POS assets, and QWeb templates.
- `pos_wholesale_control/models/__init__.py` - Imports all backend model extensions and new models.
- `pos_wholesale_control/models/res_company.py` - Stores company-specific thresholds, retail/wholesale pricelists, timezone behavior, and activation state.
- `pos_wholesale_control/models/res_config_settings.py` - Exposes wholesale-control configuration through Odoo settings.
- `pos_wholesale_control/models/wholesale_pricelist_mapping.py` - Maps the four existing `customer_type` values to configured pricelists without modifying `alta_mayoristas`.
- `pos_wholesale_control/models/res_partner.py` - Provides the trusted eligibility and three-month aggregation API for selected customers.
- `pos_wholesale_control/models/pos_order.py` - Persists decision snapshots and performs final server-side pricing validation.
- `pos_wholesale_control/models/pos_wholesale_override.py` - Stores immutable, auditable manager override records.
- `pos_wholesale_control/security/wholesale_security.xml` - Defines administrator and manager permissions for configuration and overrides.
- `pos_wholesale_control/security/ir.model.access.csv` - Defines ACLs for every new persistent model.
- `pos_wholesale_control/views/res_config_settings_views.xml` - Adds thresholds, pricelists, mappings, and validation warnings to settings.
- `pos_wholesale_control/views/pos_order_views.xml` - Shows final pricing decisions, snapshots, and override audit details on completed POS orders.
- `pos_wholesale_control/views/pos_wholesale_override_views.xml` - Provides read-only audit views for authorized backend users.
- `pos_wholesale_control/views/assets.xml` - Loads Odoo 14 POS JavaScript, QWeb, and SCSS assets.
- `pos_wholesale_control/static/src/js/models.js` - Loads required fields and extends POS order state and JSON serialization.
- `pos_wholesale_control/static/src/js/wholesale_eligibility.js` - Coordinates eligibility RPCs, retail-total calculation, state transitions, and complete-order repricing.
- `pos_wholesale_control/static/src/js/ProductScreen.js` - Reevaluates pricing when the customer, lines, quantities, or discounts change.
- `pos_wholesale_control/static/src/js/PaymentScreen.js` - Runs the final trusted validation and blocks payment when pricing is invalid.
- `pos_wholesale_control/static/src/js/SetPricelistButton.js` - Prevents cashier selection of unauthorized pricelists.
- `pos_wholesale_control/static/src/js/WholesaleStatusPanel.js` - Displays customer type, pricing status, reason, active pricelist, and monthly totals.
- `pos_wholesale_control/static/src/js/ManagerOverridePopup.js` - Collects manager authorization and a mandatory override reason.
- `pos_wholesale_control/static/src/xml/wholesale_status_panel.xml` - Defines the persistent POS status panel.
- `pos_wholesale_control/static/src/xml/manager_override_popup.xml` - Defines the manager override dialog.
- `pos_wholesale_control/static/src/scss/wholesale_control.scss` - Styles distinct and accessible retail, wholesale, error, and override states.
- `pos_wholesale_control/tests/__init__.py` - Imports backend test modules so Odoo discovers them.
- `pos_wholesale_control/tests/common.py` - Creates shared companies, pricelists, users, customers, products, taxes, sessions, sales, and returns.
- `pos_wholesale_control/tests/test_configuration.py` - Tests settings, mappings, required pricelists, permissions, and activation constraints.
- `pos_wholesale_control/tests/test_eligibility.py` - Tests calendar-month aggregation and wholesale eligibility rules.
- `pos_wholesale_control/tests/test_pos_order_validation.py` - Tests server-side tamper resistance, snapshots, and overrides.
- `pos_wholesale_control/static/tests/wholesale_eligibility_tests.js` - Tests POS state changes, retail-total thresholds, repricing, and stale-response handling.
- `pos_wholesale_control/static/tests/wholesale_ui_tests.js` - Tests cashier restrictions, status display, errors, and override interactions.
- `alta_mayoristas/models/res_partner.py` - Read-only integration reference for the four existing `customer_type` values; do not modify.
- `alta_mayoristas/static/src/js/models.js` - Existing POS customer-field loader to account for; do not modify.
- `odoo-src/odoo14-server/addons/point_of_sale/static/src/js/models.js` - Odoo 14 reference for `Order.set_pricelist`, `updatePricelist`, totals, and JSON export; do not modify.
- `odoo-src/odoo14-server/addons/point_of_sale/models/pos_order.py` - Odoo 14 reference for `_order_fields`, `_process_order`, and `create_from_ui`; do not modify.

### Notes

- Implement this feature in the new `pos_wholesale_control` module. Do not change the models, selections, or behavior of `alta_mayoristas`.
- Odoo 14 POS uses legacy JavaScript modules, Backbone order models, OWL POS components, and `Registries.Component.extend`; do not use modern Odoo POS patch APIs.
- Standard Odoo applies a selected customer's pricelist and allows manual pricelist selection. This feature must override both behaviors so only the trusted eligibility decision controls retail versus wholesale pricing.
- Dynamic monthly totals should be fetched when a customer is selected, not preloaded for every customer at POS startup.
- The backend must independently recalculate the qualifying history, retail-priced order amount, expected pricelist, and override validity. Never trust a client-provided eligibility result.
- Monetary threshold comparisons must use the company currency's precision and Odoo comparison helpers or a fixed-precision decimal representation; do not use unrounded binary-float comparisons.
- Unit tests must be inside `pos_wholesale_control/tests/` and imported by `tests/__init__.py`.

### Local `produccion` replica — October 29, 2026

The local database `produccion` is the live replica. The live server was not changed.

**Install.** `pos_wholesale_control` `14.0.1.1.0` was installed with `-i` and `--stop-after-init`. Odoo exited 0 and logged `Modules loaded`. `alta_mayoristas` stayed `14.0.1.9.0`. The new tables are `pos_wholesale_override` and `pos_wholesale_pricelist_mapping`. **Activar control de mayoreo** stayed off on all six companies. Completed POS orders were not given a wholesale decision.

**Scenario checks.** Fifty server-side checks passed against that installed module. Configuration, mappings, one temporary Distribuidor, and one manager override were created inside the transaction and then rolled back. After the rollback, order counts, partner and company write dates, mappings, overrides, and the inactive switch matched the pre-check snapshot.

The replica's last paid POS order is August 19, 2026, so September and October 2026 have no sales. History was evaluated as of August 15, 2026, which makes July the previous month. The register was Caja 2 (Ins), company Factor Fiesta | Tijuana Insurgentes. Source pricelists are `Public Pricelist` (id 1), `Club Mayorista` (id 2), and `Super Precios a Distribuidores` (id 3). On screen those are Lista de precios a Publico en General, Lista de precios de Mayorista, and Super Precios a Distribuidores. All three active Insurgentes registers already offer the retail list and Club Mayorista.

What passed:

- Activation is rejected until both pricelists are set. A second mapping for the same customer type is rejected.
- With the switch off, partner 9082 (July MXN $15,617.15) stays retail. With the switch on, that history applies Club Mayorista in 9–42 ms.
- Partner 30455 at MXN $799.44 stays retail. The exact July total qualifies, and one cent above that minimum does not. MXN $1,499.99 stays retail and MXN $1,500.00 applies wholesale for that ticket only.
- `mayorista`, `publico_general`, and `mayorista_dormido` map to Club Mayorista. The replica has 4, 2, and 1 of those customers, and no `distribuidores` customer. A temporary Distribuidor mapped to Super Precios and was rolled back.
- A real product priced from Public Pricelist ignored a submitted unit price of MXN $9,999. Payment rejected the wrong list and accepted the server list.
- A real Caja 2 manager PIN was required. A wrong PIN, a blank reason, and a direct audit create were rejected. The override was stored once, did not apply to the next ticket, and did not change the customer type or permanent pricelist. The audit row could not be edited, deleted, or copied.
- July totals for partner 9082 included both stores: MXN $13,563.64 at Insurgentes and MXN $15,617.15 across companies.
- Partner 23679's January 22, 2023 return of MXN $1,940.88 reduced January. The month net was MXN $4,099.48.
- A user outside Point of Sale, and a register from another company, were denied.

The POS screen was not opened. On today's clock the previous month is September 2026, which has no sales in this replica, so a screen test will not show previous-month wholesale from real history. The current-ticket MXN $1,500 path and the manager override can still be clicked.

## Confirmed Decisions

Recorded October 28, 2026. These decisions close tasks 1.2 through 1.8.

1. **Qualifying history.** Count paid/completed POS orders (`paid`, `done`, `invoiced`) and confirmed sales orders (`sale`, `done`). Include every company. The store where the customer buys now does not limit the total.
2. **Return month.** A return reduces the calendar month of the original sale, in `America/Tijuana`.
   - Odoo 14 creates a POS refund as a new order dated now, named `{original} REFUND`, with a negative `amount_total` and no link field. Attribute that negative total to the original order's `date_order`. Match the original by removing the ` REFUND` suffix, then by the copied `pos_reference` if the name match fails.
   - A sales credit note does not reduce `sale.order.amount_total`. Subtract `out_refund` invoices that belong to a sales order from the original sale month. Do not also subtract a POS credit note, because the negative POS order already represents that return.
3. **Pricelists.** Retail is always `Public Pricelist`. When the customer qualifies, `mayorista` uses `Club Mayorista`, and `distribuidores` uses `Super Precios a Distribuidores`. `publico_general` and `mayorista_dormido` stay on `Public Pricelist` until the current retail-priced order reaches MXN $1,500, then they use `Club Mayorista`. Resolve the list by name inside the current register's available pricelists, because the same name exists on more than one record.
4. **Company scope.** Monthly totals combine all companies. Pricelist selection stays on the current register.
5. **Manager override.** The manager must be a POS employee whose user is in Point of Sale / Manager, confirmed with the employee PIN from `pos_hr`. The override is transaction-only.
6. **Offline.** If history cannot be loaded, keep retail pricing, show the error, and allow only an audited manager override.
7. **Business timezone.** `America/Tijuana`, the timezone already used by `alta_mayoristas`.
8. **Eligibility response.** One RPC returns `customer_id`, `customer_type`, three month rows (`label`, `year`, `month`, `amount`, `is_current`), `previous_month_amount`, both thresholds, `retail_order_amount`, `automatic_decision` (`retail` or `wholesale`), `reason_code`, `reason_text`, `retail_pricelist`, `expected_pricelist`, `timezone`, `currency`, and `error`. Reason codes are `previous_month`, `current_order`, `below_threshold`, `no_identified_customer`, and `history_unavailable`. An unidentified customer returns retail and `no_identified_customer` without a history query.

## Instructions for Completing Tasks

**IMPORTANT:** Check off each completed item by changing `- [ ]` to `- [x]`. Update this file after each subtask, not only after an entire parent task.

## Tasks

- [x] 0.0 Create and check out a feature branch for wholesale customer POS control
  - [x] 0.1 Create and check out a branch such as `feature/wholesale-customer-pos-control`.
- [x] 1.0 Confirm business-rule decisions and design the independent `pos_wholesale_control` module architecture
  - [x] 1.1 Review the PRD, the existing `alta_mayoristas` public fields, and the referenced Odoo 14 POS extension points before implementation.
  - [x] 1.2 Confirm whether qualifying history includes only POS orders or both POS and Sales orders, and document how invoiced credit notes or POS refunds reduce totals.
  - [x] 1.3 Confirm whether a return reduces the month in which the return is processed or restates the original sale month.
  - [x] 1.4 Define the exact meaning of customer-type mappings: whether each type supplies a wholesale pricelist, a default pricelist, or both retail and wholesale candidates.
  - [x] 1.5 Confirm the initial retail and wholesale pricelists for each company and whether totals combine all allowed companies or remain company-specific.
  - [x] 1.6 Confirm the manager authorization mechanism available in this Odoo 14 deployment, including the permission group and whether POS employee PIN authentication is enabled.
  - [x] 1.7 Confirm the fail-closed offline policy: historical-data validation requires connectivity, with retail pricing or an audited manager override when the backend cannot be reached.
  - [x] 1.8 Define one server response contract containing the customer type, three monthly totals, previous-month amount, retail-calculated order amount, automatic decision, reason code, expected pricelist, thresholds, timezone, and error state.
  - [x] 1.9 Create the module skeleton with dependencies on `point_of_sale` and `alta_mayoristas`, keeping all integration code outside the classification module.
- [x] 2.0 Implement configurable pricelist mappings, thresholds, permissions, and validation in the Odoo backend
  - [x] 2.1 Add company-specific default thresholds of MXN $800 for previous-month purchases and MXN $1,500 for the current retail-priced order.
  - [x] 2.2 Add configurable retail and wholesale pricelist fields and the mapping model for all four existing `customer_type` keys.
  - [x] 2.3 Add uniqueness and company-consistency constraints so one customer type cannot have ambiguous active mappings.
  - [x] 2.4 Reject activation when retail or wholesale pricelists are missing, use another currency unexpectedly, or are unavailable to the relevant POS configuration.
  - [x] 2.5 Warn administrators when any of the four customer types lacks a valid mapping, without changing the source selection field.
  - [x] 2.6 Add settings views with clear labels, default values, help text, validation feedback, and company-aware behavior.
  - [x] 2.7 Define separate administrator and manager groups, reusing standard Odoo groups through implied membership only where appropriate.
  - [x] 2.8 Add least-privilege ACLs and record rules for mappings and override audit records; cashiers may read an override indicator but may not edit or delete audit data.
  - [x] 2.9 Load all security and configuration views in dependency-safe manifest order.
- [x] 3.0 Implement the trusted eligibility service and optimized three-calendar-month customer sales aggregation
  - [x] 3.1 Convert current, previous, and two-months-prior local calendar boundaries from the configured business timezone into UTC search ranges, including daylight-saving transitions.
  - [x] 3.2 Aggregate only paid/completed qualifying transactions and exclude draft, cancelled, and unpaid records.
  - [x] 3.3 Include taxes and discounts through net completed totals and subtract qualifying returns according to the approved return-month policy.
  - [x] 3.4 Use grouped ORM queries over all three month ranges instead of loading individual orders into Python.
  - [x] 3.5 Apply the approved company scope explicitly and justify any narrow `sudo()` use that is required to aggregate across allowed companies.
  - [x] 3.6 Return separate month/year labels and amounts, marking the current month as month-to-date.
  - [x] 3.7 Compare the previous-month amount with the configured threshold using currency-aware precision and produce stable machine-readable reason codes.
  - [x] 3.8 Add a model RPC that accepts the selected customer and current order facts, validates access, and returns the complete eligibility response contract.
  - [x] 3.9 Return a fail-closed retail decision with a clear validation-error state when historical data cannot be obtained.
  - [x] 3.10 Ensure unidentified customers receive the retail pricelist and the `no_identified_customer` reason without running unnecessary history queries.
  - [x] 3.11 Measure the aggregation query and add indexes only if query analysis shows they are needed to meet the one-second requirement.
- [x] 4.0 Extend POS orders with pricing-decision snapshots, manager overrides, audit records, and server-side final validation
  - [x] 4.1 Add immutable snapshot fields for automatic decision, final decision, reason code/text, retail-calculated amount, previous-month amount, thresholds, business timezone, and applied pricelist.
  - [x] 4.2 Extend POS order JSON export and `_order_fields` so required decision metadata survives synchronization, while treating client values as audit inputs rather than trusted authorization.
  - [x] 4.3 Recalculate the retail-priced amount on the server from products, quantities, discounts, taxes, fiscal position, and the configured retail pricelist.
  - [x] 4.4 Recalculate customer history and the expected pricelist immediately before processing a non-draft order.
  - [x] 4.5 Reject payment completion when the submitted pricelist or decision does not match the trusted result, returning an actionable message to the POS.
  - [x] 4.6 Create the manager-override model with manager, cashier, customer, POS order, timestamp, automatic decision, overridden decision, reason, and relevant decision snapshot.
  - [x] 4.7 Require a non-empty reason and verify manager credentials and group membership on the server before issuing or accepting a transaction-scoped override.
  - [x] 4.8 Prevent overrides from changing the customer's classification, permanent pricelist, mappings, or future eligibility.
  - [x] 4.9 Make completed snapshots and override audit records non-editable and non-deletable through both ORM safeguards and access control.
  - [x] 4.10 Add backend views that let authorized users inspect the automatic decision, final outcome, and linked override without altering historical data.
  - [x] 4.11 Preserve idempotency when an offline order is retried so synchronization cannot create duplicate override audit records.
- [x] 5.0 Implement automatic POS customer eligibility evaluation, retail-total tracking, order repricing, and unauthorized-pricelist prevention
  - [x] 5.1 Load only the configuration, mappings, permissions, and existing `customer_type` field needed by the POS.
  - [x] 5.2 Extend each POS order with wholesale-control state, including request version, monthly totals, automatic decision, active reason, retail reference total, expected pricelist, override state, and validation errors.
  - [x] 5.3 On customer selection, change, or removal, invalidate stale data, fetch trusted eligibility, and ignore out-of-order RPC responses.
  - [x] 5.4 Build a retail reference calculation that keeps discounts and taxes but prices every product through the configured retail pricelist.
  - [x] 5.5 Reevaluate the current-order threshold after product, quantity, discount, tax, or customer changes.
  - [x] 5.6 Apply wholesale pricing to the entire order when the previous-month amount qualifies or the retail reference total reaches MXN $1,500.
  - [x] 5.7 Keep wholesale active when wholesale repricing lowers the payable total below MXN $1,500, provided the separate retail reference total still meets the threshold.
  - [x] 5.8 Restore retail pricing if the retail reference total falls below the threshold and previous-month eligibility does not apply.
  - [x] 5.9 Reprice every applicable order line when the decision changes, including lines that standard `set_pricelist` would skip as manually priced, according to the approved manual-price policy.
  - [x] 5.10 Prevent recursive reevaluation loops while repricing lines and keep the UI responsive during rapid edits.
  - [x] 5.11 Disable or intercept the standard pricelist selector so cashiers cannot apply or retain an unauthorized wholesale pricelist.
  - [x] 5.12 Clear an existing override whenever the customer changes and require fresh authorization for the new transaction context.
  - [x] 5.13 Serialize enough state for offline recovery and final audit while still requiring server validation before a wholesale-priced order completes.
- [x] 6.0 Build the POS interface for customer classification, pricing status, eligibility reasons, monthly totals, errors, and manager overrides
  - [x] 6.1 Add a persistent status panel that shows the selected customer, existing customer type, Retail/General Public or Wholesale status, active pricelist, and decision explanation.
  - [x] 6.2 Display current month-to-date and the two previous calendar months separately with localized month/year labels and MXN currency formatting.
  - [x] 6.3 Show an identification-required state instead of monthly totals when no customer is selected.
  - [x] 6.4 Show loading state during validation and a clear fail-closed retail error when historical information is unavailable.
  - [x] 6.5 Make retail, wholesale, error, and override states distinguishable with text and icons rather than color alone.
  - [x] 6.6 Refresh the panel immediately after customer changes and after successful completion of a sale or return affecting the customer.
  - [x] 6.7 Add a manager override action visible only in the appropriate context and require manager authorization plus a non-empty reason.
  - [x] 6.8 Keep an obvious override indicator and the automatic decision visible for the remainder of the current transaction.
  - [x] 6.9 Add plain-language blocking messages for missing configuration, unauthorized pricelists, failed backend validation, invalid manager authorization, and stale eligibility.
  - [x] 6.10 Extend the payment screen so final validation runs before order synchronization and returns the cashier to a correctable state when blocked.
  - [x] 6.11 Verify the panel and dialogs fit supported POS viewport sizes and remain keyboard accessible.
- [x] 7.0 Add backend and POS tests covering thresholds, returns, timezones, customer changes, access control, validation failures, and auditability
  - [x] 7.1 Build reusable fixtures for the four customer types, multiple companies, MXN pricelists, taxes, products, users, sessions, completed sales, and returns.
  - [x] 7.2 Test previous-month boundaries at MXN $799.99 and $800.00 and current retail-order boundaries at MXN $1,499.99 and $1,500.00.
  - [x] 7.3 Test that discounts, included/excluded taxes, and returns produce the approved net qualifying amount.
  - [x] 7.4 Test local month boundaries and UTC conversion around midnight and daylight-saving changes in the configured timezone.
  - [x] 7.5 Test exclusion of draft, cancelled, unpaid, and incomplete POS and Sales transactions.
  - [x] 7.6 Test no-customer retail behavior and replacement of a customer's preassigned but unauthorized wholesale pricelist.
  - [x] 7.7 Test customer changes, item removal, quantity reduction, and discount changes cause complete and reversible repricing.
  - [x] 7.8 Test that a wholesale-repriced total below MXN $1,500 remains eligible while its independent retail reference total stays at or above MXN $1,500.
  - [x] 7.9 Test that current-order qualification applies only to that transaction and does not modify future customer eligibility.
  - [x] 7.10 Test cashier attempts to select wholesale pricing manually are blocked in the UI and rejected by the server if the client is tampered with.
  - [x] 7.11 Test authorized overrides, mandatory reasons, unauthorized attempts, transaction scope, complete audit contents, and audit immutability.
  - [x] 7.12 Test historical-data or RPC failure produces retail pricing and permits only the approved audited override path.
  - [x] 7.13 Test stale asynchronous customer responses cannot overwrite the state of a newly selected customer.
  - [x] 7.14 Test all twelve PRD acceptance scenarios end to end.
  - [x] 7.15 Verify every completed POS order records a decision reason and every wholesale order has either a qualifying rule or valid override.
- [x] 8.0 Complete linting, performance verification, acceptance testing, and deployment documentation
  - [x] 8.1 Run `pylint-odoo` and Ruff inside the project virtual environment and resolve approved findings.
  - [x] 8.2 Run the module's Python and JavaScript tests in the project virtual environment against a disposable Odoo test database.
  - [x] 8.3 Measure partner selection, line-edit reevaluation, and final validation with representative production-scale data and confirm normal completion within one second.
  - [x] 8.4 Perform manual POS acceptance testing for all PRD scenarios, including visible states, manager flow, and error recovery.
  - [x] 8.5 Verify installation and upgrade on each allowed company without changing existing `alta_mayoristas` records or completed POS orders.
  - [x] 8.6 Update the manifest version and module description, then record configuration prerequisites and the required stop–upgrade–start deployment sequence in the release handoff.

## Local Caja 2 screen test — October 29, 2026

Local replica only. The live server was not touched and the live deployment sequence was not run. No order was charged or validated. **Activar control de mayoreo** stayed on for Factor Fiesta | Tijuana Insurgentes and off for the other companies. Caja 2 session `SS-INS-04787` was left open. The unpaid draft is still 6 units of GL12 Sensacional Lila C/100 for JORGE ARTURO FRAGOSO BONILLA, public list, total MXN $1,331.25.

Chrome **Allow JavaScript from Apple Events** was not turned on. The preference `AllowJavaScriptFromAppleEvents` is absent, which is Chrome's off default, and it was not changed, so there was nothing to restore. Remote debugging was not enabled. The screen checks used the POS window only.

### What the screen showed

1. **No customer.** The panel asks to identify a customer and does not show monthly totals. Visual pass.
2. **Identified customer.** TERESA MEZA NAVARRO showed the customer, type, Retail, the reason, and August, September, and October. September was MXN $0.00. Visual pass.
3. **Six and seven units of GL12 Sensacional Lila C/100.** The retail reference is the public-list total, independent of the payable wholesale total.
   - Six units: retail reference MXN $1,331.25, decision retail, reason `below_threshold`. The screen showed that same total at MXN $221.88 per unit, taxes MXN $98.61, panel “Wholesale control — retail”, and Lista de precios a Publico en General. The reason said neither the previous month nor this order reaches the wholesale minimum.
   - Seven units: retail reference MXN $1,553.13, decision wholesale, reason `current_order`. That MXN $1,553.13 figure is the server retail-total calculation. The screen did not show it as the order total. The screen showed the wholesale payable total MXN $1,040.56 at MXN $148.65 per unit, taxes MXN $77.08, which is below MXN $1,500, panel “Wholesale control — wholesale”, and Lista de precios de Mayorista. The reason said the current order, at retail, reaches the wholesale minimum.
   - Visual change: raising the quantity from 6 to 7 switched the panel and the pricelist button to wholesale while the payable total fell below MXN $1,500.
   - Visual return: setting the quantity back to 6 restored the public list, the unit price MXN $221.88, the total MXN $1,331.25, and the retail panel.
4. **Manual pricelist.** The pricelist button showed “Lista de precios bloqueada” and “Esta caja elige la lista de precios. No se puede cambiar manualmente.” After Ok, the list and the unit price were still public. Confirmed again on October 29. Visual pass.
5. **Manager override.** A blank reason and a wrong PIN were rejected. A valid PIN plus a reason applied wholesale for that ticket only, and the panel still showed the automatic retail decision. Changing the customer cleared the override on screen. Visual pass. The PIN was not printed or changed.
6. **Wrong list at payment.** Not a visual pass. The normal buttons cannot keep a list other than the one the register chooses, and the payment screen has no pricelist control. Back was used. Validate was not pressed, and no payment method was selected, so the sentence “No se puede cobrar con la lista seleccionada” was not reached on the payment screen. An earlier appearance of that popup came from setting the list outside the normal buttons and is not a visual pass.

### Payment-screen fix

`PaymentScreen.js` used to replace a mismatched list and then continue into payment. A mismatch now returns “No se puede cobrar con la lista seleccionada” and `validateOrder` returns to the product screen before `super.validateOrder`. The payment screen no longer calls `_wholesaleUsePricelist`.

`node --check` passed on that file. A source check confirmed both mismatch branches return that sentence and that a blocking message returns before `super.validateOrder`. That source check is not a screen pass.

The normal asset bundle cached before the edit still corrected the list. Rebuilding it without `debug=assets` replaced that file. The only remaining bundle is `/web/content/324904-e9f9e70/point_of_sale.assets.js` (attachment 324904, written 2026-10-29 19:59:45 UTC). Its `pos_wholesale_control.PaymentScreen` section contains the sentence twice, returns it on both mismatch checks, and does not call `_wholesaleUsePricelist`.

### Server-only check of the same block

Not a visual pass. For customer 33478, six units, retail reference MXN $1,331.25, decision retail / `below_threshold`, the expected list is the public list. Submitting the wholesale list raised “No se puede cobrar con la lista seleccionada” and named the public list. Submitting the public list was accepted by the preparation check. The call was `_wholesale_prepare_payment` only. The transaction was rolled back. The POS order count did not change. Validate was not pressed.

## Release handoff

Recorded October 29, 2026. Module version `14.0.1.1.0`. The live server was not upgraded. The local replica was upgraded later the same day; see the Caja 2 screen-test note above.

### Configuration prerequisites

Do this per company, in Point of Sale settings, before turning on **Activar control de mayoreo**. The upgrade leaves that switch off.

- Retail list: `Public Pricelist`, company currency (MXN), available on every register of that company.
- Wholesale list: `Club Mayorista`, same currency, available on every register.
- Mappings: `mayorista`, `publico_general`, and `mayorista_dormido` use `Club Mayorista`. `distribuidores` uses `Super Precios a Distribuidores`. That distributor list must also be on the register.
- Thresholds: MXN $800 previous calendar month, MXN $1,500 current retail-priced order.
- Timezone: `America/Tijuana`.
- The register must use `pos_hr` employees. The manager's user must be in Point of Sale / Manager and the employee must have a PIN.
- Monthly totals include every company. Pricelist choice stays on the current register.

### Deployment

The change adds stored fields, models, views, and security, so the live update is stop, pull, upgrade, start. Do not use a pull-and-restart only. After `-u`, do not also upgrade from the Apps screen.

```bash
cd /odoo14/custom/odoo14-repo
sudo git pull origin main
sudo chown -R odoo14:odoo14 /odoo14/custom/odoo14-repo
sudo find /odoo14/custom/odoo14-repo -type d -exec chmod 755 {} \;
sudo find /odoo14/custom/odoo14-repo -type f -exec chmod 644 {} \;
sudo systemctl stop odoo14.service
sudo -u odoo14 python3 /odoo14/odoo14-server/odoo-bin \
  -c /etc/odoo14-server.conf \
  -d produccion \
  -u pos_wholesale_control \
  --stop-after-init
sudo systemctl start odoo14.service
sudo systemctl status odoo14.service
```

Push `main` from this machine before the pull. Hard-refresh the POS browser after the service is back.

### Upgrade check on the disposable copy

`-u pos_wholesale_control` on `pos_wholesale_perf` finished with exit 0 on October 29, 2026. All six companies stayed inactive. `alta_mayoristas` stayed at `14.0.1.9.0`. Customer-type counts and completed POS order counts, totals, pricelists, and write dates were unchanged.
