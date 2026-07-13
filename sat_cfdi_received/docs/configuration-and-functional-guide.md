# SAT Received CFDI Download — Configuration & Functional Guide

| Field | Value |
|-------|--------|
| Module | `sat_cfdi_received` |
| Odoo version | 14 |
| Document version | 1.0 |
| Last updated | 2026-07-10 |

---

## 1. Overview

This module lets you **manually** download **received** CFDIs (supplier invoices) from the SAT using **FIEL** and the official **Descarga Masiva v1.5** web service. It extracts key fields from each XML, stores them as Odoo records, and lets users browse and export selected rows to CSV.

**What it does**

- Authenticates with SAT using FIEL
- Requests a date-range download of received CFDIs
- Polls SAT until packages are ready
- Downloads ZIP packages, parses XMLs, and creates records
- Deduplicates by UUID (folio fiscal)

**What it does not do (phase 1)**

- Stamp or cancel outbound invoices (that is `cdfi_invoice` + PAC/CSD)
- Create vendor bills automatically
- Run on a schedule (no cron — manual only)
- Import XML/ZIP/CSV files manually

**Relation to `cdfi_invoice`**

This module is **independent**. It does not use CSD or PAC credentials from `cdfi_invoice`. Both modules can coexist without sharing credentials or APIs.

---

## 2. Prerequisites

### 2.1 Odoo module dependencies

- `base`
- `account`

### 2.2 Python dependencies (Odoo venv)

Install in the same virtual environment Odoo uses (Python **3.8.18** for Odoo 14):

```bash
source venv/bin/activate
pip install -r sat_cfdi_received/requirements.txt
```

| Package | Required? | Notes |
|---------|-----------|-------|
| `cfdiclient==1.6.2` | **Yes — new** | SAT Descarga Masiva client; not used by `cdfi_invoice` |
| `lxml` | Already in Odoo | Also used by `cdfi_invoice` |
| `requests` | Already in Odoo | Also used by `cdfi_invoice` |
| `pyOpenSSL`, `pycryptodome`, `cryptography` | Auto-installed | Pulled in by `cfdiclient`; `cryptography` also encrypts the FIEL password |

### 2.3 SAT credentials

You need a valid **FIEL** for the legal entity:

- `.cer` file (certificate)
- `.key` file (private key)
- FIEL password

The FIEL RFC must match the company **VAT** field in Odoo (with or without `MX` prefix).

### 2.4 Network

The Odoo server must reach SAT web services over HTTPS. There is **no SAT sandbox** — connection tests use the live SAT environment.

---

## 3. Installation

1. Ensure the module path is in `addons_path` (repo root or `odoo-src/custom/addons`).
2. Install Python dependencies (see §2.2).
3. Install or upgrade the module:

```bash
python odoo-bin -c odoo14-local.conf -d YOUR_DB -i sat_cfdi_received --stop-after-init
```

For upgrades after code changes:

```bash
python odoo-bin -c odoo14-local.conf -d YOUR_DB -u sat_cfdi_received --stop-after-init
```

4. Assign user groups (see §4.2).

---

## 4. Configuration Guide

### 4.1 Company VAT (RFC)

Before configuring FIEL, set the company **VAT** to the legal entity RFC, e.g.:

- `GMA121221Q79` or
- `MXGMA121221Q79`

The module normalizes the `MX` prefix automatically when talking to SAT.

### 4.2 User groups and access

Two security groups control access:

| Group | Can do |
|-------|--------|
| **SAT / User** | View received CFDIs, view download requests (read-only), export CSV |
| **SAT / Manager** | Everything a User can do, plus configure FIEL, run downloads, submit/check/process SAT requests |

Assign groups under **Settings → Users & Companies → Users → Access Rights** (Accounting category).

**Important:** Only **SAT / Manager** can:

- Upload FIEL credentials
- Run **Test Connection**
- Open **Download Received CFDIs** wizard
- Click **Submit to SAT**, **Sync from SAT**, or **Process Packages**

Administrators (`base.user_admin`) are added to **SAT / Manager** by default on module install.

### 4.3 FIEL configuration

Path: **SAT → Configuration** (opens company form) → tab **SAT / FIEL**

| Field | Description |
|-------|-------------|
| FIEL Certificate (.cer) | Upload the `.cer` file |
| FIEL Private Key (.key) | Upload the `.key` file |
| FIEL Password | Enter the FIEL password (stored encrypted; not shown after save) |
| FIEL Configured | Read-only indicator — all three inputs present |
| RFC from Certificate | Read-only RFC extracted from the certificate |
| RFC Mismatch | Warning if certificate RFC ≠ company VAT |

Steps:

1. Open **SAT → Configuration**.
2. Select the company (if multi-company).
3. Go to the **SAT / FIEL** tab.
4. Upload `.cer`, `.key`, and enter the password.
5. Confirm **FIEL Configured** is checked and **RFC Mismatch** is not shown.
6. Click **Test Connection**.

A successful test shows: *"FIEL authentication successful. SAT token obtained."*

### 4.4 FIEL password storage

The FIEL password is **not stored in plaintext**. It is encrypted with Fernet using a key derived from the Odoo `database.secret` system parameter. After saving, the password field appears empty in the UI (expected behavior).

### 4.5 Multi-company

Each company can have its own FIEL. Record rules restrict users to records belonging to companies they are allowed to access.

---

## 5. Functional Guide

### 5.1 Menu structure

| Menu | Access | Purpose |
|------|--------|---------|
| **SAT → Received CFDIs** | SAT / User | Browse downloaded invoice records |
| **SAT → Download Requests** | SAT / User (read), Manager (actions) | Monitor SAT download jobs |
| **SAT → Download Received CFDIs** | SAT / Manager | Start a new download (wizard) |
| **SAT → Configuration** | SAT / Manager | FIEL setup on company form |

### 5.2 Typical workflow (manual)

```
Configure FIEL  →  Request download  →  Sync from SAT (manual, retry as needed)  →  Export CSV
```

There is **no automatic cron polling**. You control when SAT is checked.

**Step 1 — Request a download (Manager)**

1. Go to **SAT → Download Received CFDIs**.
2. Set **From** and **To** dates.
   - Default: first day of current month → today
   - SAT requires at least **2 seconds** between start and end
3. Select **Company** (if multi-company).
4. Click **Request**.

This creates a download request, submits it to SAT, and runs an **initial status check**.

**Step 2 — Monitor the request**

You are redirected to the download request form. Status progresses through:

| Status | Meaning |
|--------|---------|
| **Draft** | Created locally, not yet sent to SAT |
| **Requested** | Sent to SAT; waiting for processing |
| **Processing** | SAT is preparing packages, or packages are being downloaded |
| **Done** | Packages processed; CFDI records created |
| **No CFDIs Found** | SAT returned no CFDIs for the date range (code 5004) |
| **Error** | Something failed — see the status message on the form |

**Step 3 — Sync from SAT (manual, repeat as needed)**

If packages are not ready yet (or SAT timed out):

1. Wait **2–5 minutes**.
2. Open the request under **SAT → Download Requests**.
3. Click **Sync from SAT**.

This polls SAT and automatically imports received CFDIs when ready. A network timeout does **not** cancel the request — click again later.

| Button | When to use |
|--------|-------------|
| **Sync from SAT** | Normal action — poll SAT and build the received CFDI list |
| **Process Packages** | Only when package IDs are already listed but import did not finish |
| **Reset** | Start over (clears SAT request ID; use before a new submit) |
| **Submit to SAT** | Only for new requests (hidden once a SAT ID exists) |

**Step 4 — Review records**

1. Go to **SAT → Received CFDIs**.
2. Use search filters (supplier name, date range, group by month/supplier).
3. Open a record to see invoice date, supplier, total, UUID, RFC, and currency.

Records are **read-only** in the UI. They can only be created from SAT download packages (no manual import).

**Step 5 — Export to CSV (User or Manager)**

1. In **SAT → Received CFDIs**, select one or more rows.
2. **Action → Export CSV**.
3. Download the file (`sat_received_cfdi_YYYY-MM-DD.csv`).

CSV format:

```csv
invoice_date,supplier_name,total
2026-07-05,"Proveedor ABC SA de CV",15432.50
```

- UTF-8 with BOM (Excel-friendly)
- Dates: `YYYY-MM-DD`
- Decimals: `.`

### 5.3 Data stored per received CFDI

| Field | Source |
|-------|--------|
| Invoice Date | CFDI `Fecha` (generation date) |
| Supplier | Emisor `Nombre` |
| Total | Comprobante `Total` |
| UUID | TimbreFiscalDigital `UUID` |
| Supplier RFC | Emisor `Rfc` |
| Currency | Comprobante `Moneda` |
| Company | Linked to the company that downloaded |
| Download Request | Linked to the SAT job that created the record |

Raw XML is stored internally as an attachment for audit purposes. It is not exposed in the main UI.

### 5.4 Deduplication

Each UUID is unique per company. If the same CFDI appears in multiple packages or downloads, duplicates are skipped silently — the request continues processing other XMLs.

### 5.5 Date range tips

- Download **month by month** for large volumes (SAT may reject very wide ranges).
- Default wizard range (1st of month → today) is a good starting point.
- If you get a lifetime-limit error from SAT, use a shorter date range.

---

## 6. Security Summary

| Aspect | Measure |
|--------|---------|
| FIEL files | Visible only to SAT / Manager and System |
| FIEL password | Encrypted at rest; empty in UI after save |
| SAT fetching | Manager only (ACL + Python enforcement) |
| Record creation | Only from SAT package processing (no manual import) |
| Logs | No passwords, keys, or tokens in log output |
| Multi-company | Record rules filter by allowed companies |

---

## 7. Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| "Python package cfdiclient is not installed" | Missing pip dependency | Run `pip install -r sat_cfdi_received/requirements.txt` in Odoo venv |
| "Configure FIEL on company…" | FIEL not uploaded | Complete §4.3 |
| "RFC from certificate does not match company VAT" | Wrong `.cer` or wrong company VAT | Fix VAT or upload correct FIEL |
| "SAT authentication failed" | Wrong password, expired FIEL, or network issue | Verify credentials; check server HTTPS access to SAT |
| "SAT requires a date range of at least 2 seconds" | From ≥ To or range too narrow | Adjust dates |
| Status **No CFDIs Found** | No received CFDIs in that range | Normal — try a different period |
| Status **Error** with "duplicate" | Same range already requested recently | Wait or use a slightly different range |
| Status **Error** with "lifetime limit" | Date range too large for SAT | Shorten the range (e.g. one month) |
| Status stays **Requested** / **Processing** with "did not respond in time" | SAT or network timeout | Wait 2–5 minutes and click **Sync from SAT** again |
| User cannot see download wizard | Not in SAT / Manager group | Assign **SAT / Manager** |
| User cannot export CSV | Not in SAT / User group | Assign **SAT / User** (minimum) |

---

## 8. Quick Reference — Roles vs. Actions

| Action | SAT / User | SAT / Manager |
|--------|:----------:|:-------------:|
| View received CFDIs | ✓ | ✓ |
| Export CSV | ✓ | ✓ |
| View download requests | ✓ (read) | ✓ |
| Configure FIEL | — | ✓ |
| Test connection | — | ✓ |
| Request download | — | ✓ |
| Submit / Sync from SAT / Reset | — | ✓ |

---

## 9. Related Files

| Path | Purpose |
|------|---------|
| `sat_cfdi_received/requirements.txt` | Python pip dependencies |
| `reqs/sat_cfdi_received_module_spec.md` | Full module specification |
| `tasks/tasks-sat-cfdi-received.md` | Implementation task checklist |
