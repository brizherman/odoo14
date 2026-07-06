# POS Cash Reallocation Wizard — Configuration & User Manual

**Module:** `pos_cash_reallocation_wizard`  
**Odoo version:** 14.0 Community Edition  
**Document date:** 2026-07-05

---

## 1. Overview

This module lets authorized users **proportionally reallocate** a chosen amount of cash from paid POS orders into an internal payment method called **Monedero Electrónico** (electronic wallet).

Key characteristics:

- Only affects **paid**, **cash-only**, **customer-less** orders in **open POS sessions** by default.
- **Phase 2 (optional):** can reallocate from **posted (done)** orders on **closed sessions** with compensating journal entries.
- The order total (`amount_total`) **never changes** — only the payment-method mix is adjusted.
- **Monedero Electrónico** is **hidden from the POS register**; cashiers cannot select it manually.
- Every run is **audited** and can be **undone** while affected sessions remain open.

### Business purpose

Convert a portion of recorded cash on eligible POS orders into Monedero Electrónico for accounting and reporting, without changing what the customer was charged.

---

## 2. Installation

### 2.1 Prerequisites

| Requirement | Details |
|-------------|---------|
| Odoo version | 14.0 |
| Dependencies | `point_of_sale`, `account`, `mail` |
| Addons path | Module must be in a folder listed in `addons_path` (e.g. `odoo-src/custom/addons`) |
| Cash payment method | A POS payment method named exactly **Efectivo** with **Is Cash Count** enabled |
| POS sessions | Reallocation only works while the POS session is still **open** |

### 2.2 Install the module

1. Activate your virtual environment.
2. Restart Odoo with the module path available.
3. Go to **Apps**, remove the *Apps* filter, search for **POS Cash Reallocation Wizard**.
4. Click **Install**.

On install, a `post_init_hook` runs automatically and provisions Monedero Electrónico infrastructure for **every existing company** (GL account, journal, payment method).

### 2.3 Upgrade after code changes

```bash
source venv/bin/activate
python odoo-src/odoo14-server/odoo-bin \
  -c odoo-src/odoo14-local.conf \
  -d YOUR_DATABASE \
  -u pos_cash_reallocation_wizard
```

> **Note:** The first upgrade on a database with many existing POS orders may trigger a one-time recompute of the `has_wallet_payment` field on all orders. This is expected.

---

## 3. Configuration

### 3.1 Security group — Cash Reallocation Manager

Access to the wizard and history is restricted to the **Cash Reallocation Manager** group.

| Setting | Value |
|---------|-------|
| Group name | Cash Reallocation Manager |
| Technical ID | `pos_cash_reallocation_wizard.group_pos_cash_reallocation_manager` |
| Category | Point of Sale |
| Group | Cash Reallocation Manager |
| Implied groups | POS Manager, **Billing** (`account.group_account_invoice`) |
| Closed-session posting | Billing access is required to create/post reversal journal entries |

**To assign the group to a user:**

1. Go to **Settings → Users & Companies → Users**.
2. Open the user record.
3. Under **Point of Sale**, enable **Cash Reallocation Manager**.
4. Save.

Users without this group will not see the menu item and cannot run the wizard or view logs.

### 3.2 Per-company Monedero Electrónico infrastructure

The module creates the following automatically per company (on install or on first wizard use):

| Object | Name / Code | Notes |
|--------|-------------|-------|
| GL account | **Monedero Electrónico** | Receivable-type account; code derived from the company's POS receivable account prefix |
| Journal | **Monedero Electrónico** (code `MEWLT`) | General journal |
| Payment method | **Monedero Electrónico** | `is_cash_count = False` |

**Important:** Monedero Electrónico is **never** added to any `pos.config` payment methods. It will not appear on the cashier-facing POS screen.

#### Verify infrastructure (optional)

1. **Accounting → Configuration → Payment Methods** (or POS payment methods): confirm **Monedero Electrónico** exists for the company.
2. **Point of Sale → Configuration → Point of Sale**: open each POS config and confirm **Monedero Electrónico is NOT** in the payment methods list.

### 3.3 Cash payment method requirement

Eligible orders must use a single payment method that meets **all** of these conditions:

- Name is exactly **Efectivo**
- **Is Cash Count** is checked (`is_cash_count = True`)

If your POS uses a different name for cash (e.g. "Cash"), rename it to **Efectivo** or adjust your business process — the module matches by exact name.

### 3.4 Multi-company

- Each company gets its own Monedero account, journal, and payment method.
- The wizard runs for **one company at a time** (defaults to the current user's company).
- Orders from different companies are never mixed in a single reallocation run.

---

## 4. Eligible orders — business rules

An order is included in the reallocation pool only when **all** conditions below are met:

| Rule | Requirement |
|------|-------------|
| Order state | `Paid` only |
| Customer | No customer assigned (`partner_id` empty) |
| Payment methods | Exactly **one** method: **Efectivo** with Is Cash Count |
| Net cash | Greater than zero (sum of all cash-count payment lines, including change) |
| POS session | Session must still be **open** at confirm time |
| Prior reallocation | Order must not already have a Monedero Electrónico payment line |

### Automatically excluded

| Condition | Reason |
|-----------|--------|
| Draft, cancelled, posted, or invoiced orders | Wrong state or already closed to accounting |
| Orders with a customer | Business rule |
| Mixed payment methods (cash + card, etc.) | Not cash-only |
| Zero or negative net cash | Nothing to reallocate |
| Session already closed | Payments cannot be modified |
| Already reallocated in a previous run | Idempotency — prevents double allocation |

Skipped orders appear on the **Skipped Orders** tab with a reason.

---

## 5. User guide — running a reallocation

### 5.1 Open the wizard

1. Log in as a user with **Cash Reallocation Manager**.
2. Go to **Point of Sale → Cash Reallocation**.

### 5.2 Step 1 — Set filters and search

| Field | Description |
|-------|-------------|
| **Company** | Company for this run (visible in multi-company setups) |
| **Date From / Date To** | Order date range (`date_order`). Default: from 7:00 AM today (user timezone) to now |
| **Is Cash Count** | Display-only; filter always requires cash-count methods |
| **Matched Orders** | Filled after Preview — count of eligible orders |
| **Total Net Cash** | Filled after Preview — sum of net cash on eligible orders |
| **Amount to Reallocate** | Amount you want to move from cash into Monedero (must be ≤ Total Net Cash) |

Default date range logic:

- **Date From:** 7:00 AM in the user's timezone (or previous day 7:00 AM if current time is before 7:00 AM).
- **Date To:** Current date/time.

### 5.3 Step 2 — Preview

1. Enter **Amount to Reallocate** (must be greater than zero for a real reallocation).
2. Click **Preview**.

The wizard:

- Computes matched order count and total net cash.
- Builds a per-order breakdown table.
- Lists ineligible orders on **Skipped Orders**.

**Preview table columns:**

| Column | Meaning |
|--------|---------|
| Order | POS order reference |
| Original Cash | Net cash before reallocation |
| New Cash | Cash amount after reallocation |
| E-Wallet Amount | Amount assigned to Monedero Electrónico |

**Proportional split formula:**

```
share per order = (order net cash ÷ total net cash of batch) × amount entered
```

Rounding remainder is assigned to the **last order** in the batch so shares sum exactly to the entered amount.

**Example:**

| Input | Value |
|-------|-------|
| Total net cash (30 orders) | $10,000 |
| Amount to reallocate | $5,000 |
| Effective ratio | 50% of each order's net cash |

For an order with $260.90 net cash:

- New cash: $130.45
- Monedero Electrónico: $130.45
- Order total: unchanged at $260.90

### 5.4 Step 3 — Confirm

1. Review the **Preview** tab.
2. Click **Confirm**.
3. Confirm the dialog: *Apply cash reallocation to the previewed orders?*

On confirm, for each eligible order the system:

1. Reduces the cash `pos.payment` amount by the order's share.
2. Creates a new `pos.payment` for **Monedero Electrónico**.
3. Recalculates `amount_paid` (order total stays the same).
4. Appends an audit note on the order's **Internal Note** field.

A **reallocation log** is created with reference number, user, date range, totals, and per-order lines.

#### Warning during confirm

If a session closes between Preview and Confirm, affected orders are **skipped** and their share is **redistributed** among remaining orders. A warning notification lists the skipped order names.

### 5.5 Wizard status bar

| State | Meaning |
|-------|---------|
| Draft | Initial; set filters and click Preview |
| Preview | Breakdown ready; click Confirm to apply |
| Done | Reallocation applied |

After completion, use the **History** tab in the wizard or open log records for audit and undo.

---

## 6. Posted / Closed Session Reallocation (Phase 2)

Use this path when you need to reallocate cash **after** the POS session has already been closed and orders are in **Posted** (`done`) state.

### 6.1 When to use

| Scenario | Use open session (default) | Use closed session (Phase 2) |
|----------|---------------------------|------------------------------|
| Session still open, orders `Paid` | Yes | No |
| Session closed, orders `Posted` | No | Yes |
| Accounting already posted at session close | No | Yes — posts a compensating entry |

### 6.2 Enable closed-session mode

1. Open **Point of Sale → Cash Reallocation** as a **Cash Reallocation Manager**.
2. Check **Include Closed Sessions**.
3. Read the amber banner: *Posts journal entries. Cannot modify bank statements.*

This checkbox is **not** available to users without the Cash Reallocation Manager group.

### 6.3 Eligible orders (closed-session path)

All open-session rules apply, plus:

| Rule | Requirement |
|------|-------------|
| Order state | `Posted` (`done`) |
| POS session | `Closed` with a **posted** session journal entry |
| Fiscal period | Session date must **not** fall in a locked period |
| Invoiced orders | Excluded |

Closed mode searches **only** posted orders on closed sessions — it does not mix open- and closed-session orders in one run.

### 6.4 Preview and confirm

1. Set date range and **Amount to Reallocate**.
2. Click **Preview** — the preview table shows a **POS Session** column.
3. If any matched session falls in a **locked fiscal period**, a warning appears and **Confirm is blocked**.
4. Click **Confirm** and approve: *Apply cash reallocation and post compensating journal entries?*

On confirm the system:

1. Rewrites `pos.payment` lines on each order (cash reduced, Lealtad line created).
2. Creates **one compensating journal entry per POS session** on the **Lealtad journal** (`MEWLT`):
   - **Debit** Lealtad receivable
   - **Credit** Efectivo receivable
3. Creates an audit log with `Reallocation Mode = Closed Session`, linked sessions, and journal entries.

**Order totals are never changed.** Bank statement lines are **not** modified in MVP.

### 6.5 Undo (closed-session runs)

1. Open the log (mode **Closed Session**).
2. Click **Undo** and confirm the journal-reversal warning.
3. The system reverses linked journal entries, restores cash payments, and removes Lealtad lines.

**Undo is blocked when:**

- The log was already reverted.
- The fiscal period for the reversal date is locked.
- Any linked journal entry is reconciled or otherwise non-reversible.

### 6.6 Cash-count operational note (post-close)

Physical cash was collected as Efectivo at sale time. Post-close reallocation changes **ledger receivable** and payment lines only — not bank statements or physical counts already performed at session close.

Whoever performs the next cash count should treat any drawer vs. ledger variance after post-close reallocation as an **expected operational difference** and reconcile manually.

---

## 7. History and undo

### 7.1 View history

Access history from the wizard:

1. Go to **Point of Sale → Cash Reallocation**.
2. Open the **History** tab — shows the last 100 reallocation logs for the selected company.
3. Click a log row to open the full form (per-order lines, chatter, Undo button).

The log list action (`pos.cash.reallocation.log`) is also available for administrators who add it to a custom menu or favorites.

Each log record shows:

| Field | Description |
|-------|-------------|
| Reference | Sequence number (e.g. PCR/2026/00001) |
| User | Who ran the reallocation |
| Company | Company scope |
| Date From / Date To | Wizard date filter used |
| Total Reallocated | Sum actually applied |
| Order Count | Number of orders modified |
| Reallocation Mode | Open Session or Closed Session |
| Status | Done or Reverted |

Closed-session logs also show linked **POS Sessions**, **Journal Entries** (smart button), and adjustment move tags.

**Order Lines** tab: per-order before/after amounts, skip flag, and skip reason.

### 7.2 Undo a reallocation

#### Open-session runs

1. Open a log with status **Done** and mode **Open Session**.
2. Click **Undo**.
3. Confirm: *Restore original cash amounts and remove wallet payment lines?*

#### Closed-session runs

See **§6.5** — undo reverses journal entries first, then restores payments.

Undo will:

- Restore original cash payment amounts.
- Delete Lealtad payment lines created by that run.
- Set log status to **Reverted**.
- Post a message on the log chatter (closed-session undo includes reversal move names).

**Open-session undo is blocked when:**

- The log was already reverted.
- Any affected order's POS session has since **closed**.

> For open-session runs, undo must be performed **before** closing the POS session.

---

## 8. POS orders — finding reallocated orders

The module extends the standard POS order list:

| Feature | Location |
|---------|----------|
| Column **Has Monedero Payment** | POS orders tree (optional column, hidden by default) |
| Filter **Has Monedero Payment** | POS orders search |
| Group by **Has Monedero Payment** | POS orders search |

Open **Point of Sale → Orders**, enable the optional column or apply the filter to see which orders carry a Monedero payment.

Each reallocated order also has a line in **Internal Note** documenting who reallocated, when, and the amounts.

---

## 9. Session close — cash count impact

Because customers paid physical cash, reallocation lowers the **recorded** cash total without changing physical cash in the drawer.

At session close, the expected closing cash count will be **lower than the physical cash** by exactly the total reallocated amount for that session.

| What | Impact |
|------|--------|
| Physical cash in drawer | Unchanged |
| Recorded cash payments | Reduced by reallocated amount |
| Expected cash at close | Lower than physical cash |

**Operational recommendation:** Communicate reallocation totals to whoever performs the cash count at session close. Document the reallocated amount before closing the session.

---

## 10. Reports and accounting

| Area | Impact |
|------|--------|
| Order totals and taxes | No change — `amount_total` is never modified |
| Payment method reports | Show Monedero Electrónico for reallocated portions |
| Session journal entry | Created at session close using payment lines at close time |
| Closed-session reallocation | Posts separate compensating entries on Lealtad journal (`MEWLT`) |
| Stock / inventory | No impact |

Open-session reallocation needs no immediate accounting entry because the session move is created at close.

Closed-session reallocation posts compensating entries because the session move already exists.

---

## 11. Troubleshooting

| Problem | Likely cause | Action |
|---------|--------------|--------|
| Menu **Cash Reallocation** not visible | User lacks **Cash Reallocation Manager** group | Assign the group in user settings |
| No eligible orders found | No paid, customer-less, Efectivo-only orders in range | Widen date range; check order states and payment methods |
| Orders appear under Skipped Orders | See skip reason column | Common: session closed, mixed payments, already reallocated, zero cash |
| Amount exceeds total net cash | Entered amount too high | Enter a value ≤ Total Net Cash |
| Cannot undo (open session) | Session closed on affected orders | Undo only while sessions remain open |
| Cannot undo (closed session) | Fiscal period locked or journal reconciled | Unlock period or unreconcile; see §6.5 |
| Confirm blocked (closed session) | Fiscal period locked on matched sessions | Choose orders in an open period or adjust lock dates |
| Monedero on POS register | Misconfiguration | Remove Monedero Electrónico from all POS configs — it must stay hidden |
| Payment method not Efectivo | Cash method has different name | Rename to **Efectivo** or align business process |

### Validation errors

| Message | Meaning |
|---------|---------|
| *Please preview the reallocation before confirming* | Click Preview before Confirm |
| *Amount to reallocate cannot exceed total net cash* | Reduce the entered amount |
| *Monedero Electrónico payment method is not configured* | Run module install/upgrade; hook creates infrastructure per company |
| *POS session is closed* (on undo) | Session was closed; undo no longer possible |

---

## 12. For developers and integrators

### Public API on `pos.order`

```python
# Resolve the per-company wallet payment method
wallet_method = env['pos.order']._get_wallet_payment_method(company)

# Find orders with Monedero payments (optional extra domain)
orders = env['pos.order'].search_wallet_reallocated_orders(company, domain)
```

- Source of truth: the `pos.payment` line with Monedero Electrónico.
- `has_wallet_payment` is a stored convenience index for list/search; do not duplicate payment-method lookups in downstream modules.

### Running unit tests

```bash
source venv/bin/activate
python odoo-src/odoo14-server/odoo-bin \
  -c odoo-src/odoo14-local.conf \
  -d YOUR_DATABASE \
  --test-enable \
  --stop-after-init \
  -u pos_cash_reallocation_wizard
```

---

## 12. Quick reference — workflow

```
Point of Sale → Cash Reallocation
        │
        ▼
Set Company, Date From, Date To, Amount to Reallocate
        │
        ▼
Preview  ──►  Review Preview + Skipped Orders tabs
        │
        ▼
Confirm  ──►  Payments updated, log created
        │
        ├──►  (optional) Undo from log while session open
        │
        └──►  Close POS session (accounting uses final payment mix)
```

---

## 13. Related documents

| Document | Location |
|----------|----------|
| Requirements & research | `reqs/monedero_electronico.md` |
| Implementation task list | `tasks/tasks-pos-reallocations-monedero.md` |

---

*POS Cash Reallocation Wizard — proportional cash to Monedero Electrónico for Odoo 14.*
