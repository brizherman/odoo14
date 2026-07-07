# PO Vendor Purchases & Sales Tab

Odoo 14 module — informational **Compras vs Ventas** tab on Purchase Orders.

## Python dependencies

Declared in `__manifest__.py` under `external_dependencies`:

- `google-api-python-client`
- `google-auth`

### Local development

Install in the project virtualenv before enabling the module:

```bash
cd "/Users/gab/Cursor Projects/Odoo14"
source venv/bin/activate
pip install google-api-python-client google-auth
```

### Live server (one-time, before first install/upgrade)

Production (`137.184.32.193`) runs Odoo as user `odoo14` with **system `python3`** (no venv). Install the packages once on the server:

```bash
ssh fortezo@137.184.32.193
sudo -u odoo14 python3 -m pip install google-api-python-client google-auth
sudo -u odoo14 python3 -c "import googleapiclient; import google.auth; print('OK')"
```

Then deploy and restart Odoo, and upgrade the module in **Apps**:

```bash
# On server (or use bash deploy-live.sh from your Mac)
cd /odoo14/custom/odoo14-repo
sudo git pull origin main
sudo chown -R odoo14:odoo14 /odoo14/custom/odoo14-repo
sudo systemctl restart odoo14
```

Browser → **Apps** → `PO Vendor Purchases & Sales Tab` → **Upgrade**.

Without the pip step, Odoo will block install/upgrade because of `external_dependencies`.

See also `reqs/po_vendor_sales_purchases_tab.md` §11.1 for full production deploy notes.

## Payment block parser (standalone CLI)

Parser code lives inside this module at `scripts/` (not a separate repo-root folder).

```bash
cd "/Users/gab/Cursor Projects/Odoo14"
source venv/bin/activate
python po_vendor_sales_purchases_tab/scripts/payment_block_parser_standalone.py \
  po_vendor_sales_purchases_tab/scripts/fixtures/pagos_proveedores_junio_2026.csv
```
