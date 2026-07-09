# PO Vendor Purchases & Sales Tab

Odoo 14 module — informational **Compras vs Ventas** tab on Purchase Orders.

## Configuration

Step-by-step setup (Google account, monthly workbooks, mappings, first sync): **[doc/configuration-guide.md](doc/configuration-guide.md)**

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

Production (`137.184.32.193`) runs Odoo as user `odoo14` with **system `python3`** (no venv) on **Ubuntu 20.04 / Python 3.8**.

**Important:** use **pinned versions**. An unpinned `pip install google-api-python-client google-auth` can pull `cryptography` 47+, which breaks system `pyOpenSSL` and prevents Odoo from starting.

Confirm Odoo is healthy before installing:

```bash
ssh fortezo@137.184.32.193
sudo systemctl status odoo14 --no-pager
sudo -u odoo14 python3 /odoo14/odoo14-server/odoo-bin --version
```

Install the packages once on the server (pins keep `cryptography` / `pyOpenSSL` compatible with Python 3.8):

```bash
sudo -u odoo14 python3 -m pip install --user \
  'cryptography==41.0.7' \
  'pyOpenSSL==23.2.0' \
  'google-api-python-client==2.111.0' \
  'google-auth==2.27.0' \
  'google-auth-httplib2==0.2.0'

sudo -u odoo14 python3 -c "import googleapiclient; import google.auth; print('OK')"
sudo systemctl restart odoo14
sudo systemctl status odoo14 --no-pager
```

If `import OpenSSL` fails after install, align system packages as root, then re-run the verify step:

```bash
sudo python3 -m pip install --force-reinstall \
  'cryptography==41.0.7' \
  'pyOpenSSL==23.2.0'
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
