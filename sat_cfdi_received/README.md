# SAT Received CFDI Download

Odoo 14 module for downloading received CFDIs from SAT using FIEL (Descarga Masiva v1.5).

## Python dependency

Uses **cfdiclient 1.6.2** directly in the Odoo venv (Python 3.8.18). Install with:

```bash
source venv/bin/activate
pip install -r sat_cfdi_received/requirements.txt
```

## Setup

1. Install module: `-i sat_cfdi_received --stop-after-init`
2. Assign users to **SAT / User** or **SAT / Manager**
3. **SAT → Configuration** → upload FIEL (.cer, .key, password) → **Test Connection**
4. **SAT → Download Received CFDIs** → choose date range → **Request**

## Notes

- Independent of `cdfi_invoice` (no CSD or PAC credentials)
- No scheduled cron in phase 1 — manual download only
- SAT has no sandbox; connection tests require a real FIEL
