#!/bin/bash
# Odoo 14 Local Development Startup Script
# Feb 27, 2026

cd "/Users/gab/Cursor Projects/Odoo14"

source venv/bin/activate

export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"

#python odoo-src/odoo14-server/odoo-bin -c odoo-src/odoo14-local.conf -d produccion --log-level=debug --dev=all
python odoo-src/odoo14-server/odoo-bin -c odoo-src/odoo14-local.conf --log-level=debug --dev=all