# Configuration Guide — PO Vendor Purchases & Sales Tab

**Module:** `po_vendor_sales_purchases_tab`  
**Odoo version:** 14.0  
**Last updated:** 2026-07-08

This guide walks through everything needed before the **Compras vs Ventas** tab on Purchase Orders shows useful data.

---

## 1. Overview

The module compares, for each PO vendor and branch (company):

| Panel | Source | What it shows |
|-------|--------|---------------|
| **Left — Sales** | Odoo SO + POS | Tax-inclusive totals by month × `classification_department` (current month day 1→today + previous 3 full months) |
| **Right — Purchases** | Google Sheets (`Pagos Proveedores`) | Vendor invoices with paid/unpaid status (same window) |

Data is loaded with two manual sync actions on the PO tab:

| Button | Scope | What it updates |
|--------|-------|-----------------|
| **Sync Global** | All vendors and branches | Google Sheets → purchase staging (`vendor.sheet.invoice`) |
| **Sync PO** | Open PO vendor + branch only | Sales snapshot + filtered purchase panel for this PO |

**Menu location:** Purchase → Configuration → **Vendor Sheets**

| Menu item | Who can access |
|-----------|----------------|
| Settings | Administrator only |
| Sucursal Mappings | Direction, Purchase Dept, Administrator |
| Proveedor Mappings | Direction, Purchase Dept, Administrator |
| Sync Log | Direction, Purchase Dept, Administrator |

---

## 2. Prerequisites

### 2.1 Module dependencies

The module depends on:

- `purchase`
- `custom_purchase_flow`
- `product_classifications`
- `sale`
- `point_of_sale`

### 2.2 Python packages

Required on the Odoo server (declared in `__manifest__.py`):

- `google-api-python-client`
- `google-auth`

**Local development:**

```bash
cd "/Users/gab/Cursor Projects/Odoo14"
source venv/bin/activate
pip install google-api-python-client google-auth
```

**Production server (one-time, user `odoo14`):**

```bash
ssh fortezo@137.184.32.193
sudo -u odoo14 python3 -m pip install google-api-python-client google-auth
sudo -u odoo14 python3 -c "import googleapiclient; import google.auth; print('OK')"
```

Then upgrade the module in **Apps** after deploy.

---

## 3. Google Cloud setup

### 3.1 Create a service account

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Select or create a project for Odoo sheet access.
3. Enable the **Google Sheets API** (and **Google Drive API** if you browse files by ID).
4. Go to **IAM & Admin → Service Accounts → Create service account**.
5. Create a key: **Keys → Add key → JSON**.
6. Save the JSON file securely — you will paste its contents into Odoo.

Use a **service account** (application credentials), not OAuth user login.

### 3.2 Share spreadsheets with the service account

From the JSON key, copy `client_email` (e.g. `odoo-sheets@project.iam.gserviceaccount.com`).

For **each monthly workbook** in Google Drive:

1. Open the spreadsheet.
2. **Share** → add `client_email` as **Viewer** (read-only is enough).

Without this step, sync will fail with permission errors.

### 3.3 Spreadsheet ID

From the Google Sheets URL:

```
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID_HERE/edit
```

Copy the ID between `/d/` and `/edit`. You will enter one ID per calendar month in Odoo.

### 3.4 Expected sheet structure

| Item | Value |
|------|-------|
| Workbook | One file per month, e.g. `2026 Flujo de Efectivo Julio` |
| Tab name | Always **`Pagos Proveedores`** |
| Key columns | Proveedor, Sucursal, No. Factura, Fecha, Vence, Total de Factura, Total de pago, Fecha de pago |

Payment rows use **blocks**: several invoice rows may have empty payment fields; one row at the end of the block carries the block total. The module parses these blocks automatically.

---

## 4. Odoo configuration (step by step)

### Step 1 — Google credentials

**Purchase → Configuration → Vendor Sheets → Settings** (Administrator only)

1. Open **Settings**.
2. Paste the full **Google Service Account JSON** into the text field.
3. Save.

### Step 2 — Monthly workbooks

On the same Settings form, tab **Monthly Workbooks**:

| Field | Example | Notes |
|-------|---------|-------|
| **Month** | `2026-07` | Format `YYYY-MM` |
| **Spreadsheet ID** | `1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms` | From the sheet URL |

Add every month in the analysis window: **current month + the previous 3 full calendar months**. Example on 2026-07-08: include `2026-04`, `2026-05`, `2026-06`, `2026-07`.

| Sync behavior | |
|---------------|--|
| **Closed months** | Read **once**, then marked **Synced Once** — never re-fetched from Google |
| **Current month** | Re-read on **every** Sync click |

When a new month starts, add a new row with the new spreadsheet ID. Unpaid invoices carried manually to the new sheet are updated via upsert on `(sucursal, no_factura)`.

### Step 3 — Sucursal mappings

**Purchase → Configuration → Vendor Sheets → Sucursal Mappings**

Map the exact **Sucursal** text from Google Sheets to an Odoo **Company**:

| Sheet Sucursal | Odoo Company |
|----------------|--------------|
| RIO | Tijuana Rio |
| INSURGENTES | Tijuana Insurgentes |
| ENSENADA | Ensenada Centro |

Rules:

- Use the **exact** string from the sheet (case-sensitive in Odoo).
- Map only real branches — do **not** map labels like `NOTA DE CREDITO`.
- Unmapped sucursal values produce **warnings** and those rows are skipped.

### Step 4 — Proveedor mappings

**Purchase → Configuration → Vendor Sheets → Proveedor Mappings**

Link sheet **Proveedor** names to Odoo **Vendor** (`res.partner`).

| Field | Required | Description |
|-------|----------|-------------|
| Sheet Proveedor | Yes | Exact name as it appears in the sheet |
| Vendor | Yes | Odoo supplier partner |
| Classification Vendor | No | Optional link to `product.classification.vendor` for sales matching |

#### Auto fuzzy-match (no mapping row needed)

If there is no manual row, Odoo compares the sheet **Proveedor** name against all active suppliers using fuzzy matching (ignores case, accents, legal suffixes like S.A. de C.V.).

- **Auto-matches** when one supplier is clearly the best match (e.g. `VM FIESTA` → `VM Fiesta S.A de C.V`)
- **Warning + no auto-match** when several suppliers score similarly (e.g. multiple `Fabricas Selectas...`) — add a manual mapping for those cases

#### Bulk import from CSV

Pre-built import files ship with the module:

| File | Purpose |
|------|---------|
| `data/vendor_sheet_mapping_import.csv` | Ready to import — 34 high-confidence matches |
| `data/vendor_sheet_mapping_import_full.csv` | Full list with amounts and review columns |

**Import steps:**

1. Go to **Proveedor Mappings**.
2. **Favorites → Import records**.
3. Upload `vendor_sheet_mapping_import.csv`.
4. Map columns:
   - `sheet_proveedor` → **Sheet Proveedor**
   - `partner_id` → **Vendor** (match by name)
   - `classification_vendor_id` → **Classification Vendor** (optional)
5. Run a test import, then import.

Review `vendor_sheet_mapping_import_full.csv` for vendors still marked `needs_manual` (e.g. KONTEMPO) and add rows after creating or locating the partner in Odoo.

#### Sales panel (left side)

Sales use products where `product.template.classification_vendor` matches the PO vendor. If sales totals look wrong:

1. Confirm product classifications are set on templates.
2. Optionally set **Classification Vendor** on the proveedor mapping row.

---

## 5. First sync and daily use

### Run sync

1. Open any **Purchase Order**.
2. Go to tab **Compras vs Ventas**.
3. Click **Sync Global** to load purchase invoices from Google Sheets for all branches.
4. Click **Sync PO** to refresh sales and purchases for this PO’s vendor and branch.

**Sync Global** will:

1. Fetch closed months not yet synced (bootstrap).
2. Re-fetch the **current month** workbook.
3. Parse payment blocks and upsert staging invoices.

It does **not** recalculate sales snapshots.

**Sync PO** will:

1. Recompute the sales snapshot for this PO vendor and company only.
2. Refresh the purchase panel from existing staging data (no Google API call).

A notification shows the result of each action.

### Read the tab

**Header:** vendor name, last global sync, last PO sync, and warning banners when needed.

If PO data may be stale (no PO sync yet, PO sync older than the last global sync, or older than 24 hours), a banner prompts you to click **Sync PO**.

**Left panel:** matrix — rows = departments, columns = months in the analysis window (current + previous 3) + **TOTAL**. Shows cached snapshot data after **Sync PO**; empty until then.

**Right panel:** invoice list filtered to PO vendor + PO company. Updated after **Sync Global** (new staging data) and re-filtered on **Sync PO**. Use the column menu (⋮) to show/hide optional columns (Sucursal, Monto pago grupo, etc.).

### Sync log

**Purchase → Configuration → Vendor Sheets → Sync Log**

Review past sync runs (`global` or `po`), warning counts, linked PO (for PO syncs), and who triggered each sync.

---

## 6. Operational notes (Google Sheets)

### Month rollover

```
End of July:
  - July workbook is frozen
  - Last July sync stores final paid + unpaid state

Start of August:
  - New workbook: 2026 Flujo de Efectivo Agosto
  - July rows are NOT auto-copied to August
  - Unpaid invoices are MANUALLY copied to August as unpaid
  - Paid July invoices stay on July sheet + Odoo staging from last July sync
```

### Upsert key

Invoices are unique by **`(sucursal, no_factura)`**. If invoice AGD-200 is copied from July to August unpaid, a later August sync updates the same Odoo row when it is paid.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Module won't install/upgrade | Missing Python packages | Install `google-api-python-client` and `google-auth` on server |
| Sync fails immediately | Invalid or empty JSON | Re-paste service account JSON in Settings |
| Permission denied on sheet | Folder/sheet not shared | Share workbook with service account `client_email` as Viewer |
| No purchase rows for a branch | Sucursal not mapped | Add row in Sucursal Mappings |
| No purchase rows for a vendor | Proveedor not mapped | Add row in Proveedor Mappings (except Convergram auto-match) |
| Sales matrix empty | No classification on products | Set `classification_vendor` on product templates |
| Payment block warnings | Sheet block total ≠ sum of invoices | Fix the sheet or review Sync Log / row warnings |
| Old month data missing | Month not in analysis window or no spreadsheet ID | Add month row in Settings with correct ID before month ages out |
| Closed month wrong forever | Synced Once = true | Closed months are not re-read; fix data in Odoo staging only or adjust business process for future months |

---

## 8. Access control summary

| Action | Direction | Purchase Dept | Administrator |
|--------|-----------|---------------|---------------|
| View PO tab | Yes | Yes | Yes |
| Click Sync Global on PO | Yes | Yes | Yes |
| Click Sync PO on PO | Yes | Yes | Yes |
| Edit sucursal / proveedor mappings | Yes | Yes | Yes |
| Edit Google JSON + monthly workbooks | No | No | Yes |
| View sync log | Yes | Yes | Yes |

---

## 9. Related files

| Path | Description |
|------|-------------|
| `README.md` | Module overview and pip install quick reference |
| `data/vendor_sheet_mapping_import.csv` | Bulk proveedor mapping import |
| `data/vendor_sheet_mapping_import_full.csv` | Mapping import with review metadata |
| `scripts/fixtures/` | Sample `Pagos Proveedores` CSV exports for testing |
| `reqs/po_vendor_sales_purchases_tab.md` | Full requirements specification (repo root) |
