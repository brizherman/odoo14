#!/bin/bash
# Odoo 14 Local Update Script (single run with stop-after-init)
# Mar 05, 2026

cd "/Users/gab/Cursor Projects/Odoo14"

source venv/bin/activate

export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"

python odoo-src/odoo14-server/odoo-bin \
  -c odoo-src/odoo14-local.conf \
  -u custom_purchase_flow,company_archive,header_modules \
  -d produccion \
  --stop-after-init \
  --log-level=debug