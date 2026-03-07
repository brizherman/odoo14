# PO Surtiendo → Hecho bulk migration

**Purpose**: One-time data cleanup — set Purchase Orders in state **PO Surtiendo** (`purchase`) to **Hecho** (`hecho`), for POs confirmed on or before **December 31, 2025**. Stock pickings are **not** modified (inventory not managed in this DB).

**Tested**: 2026-03-06 on local DB `produccion` — 3,156 POs updated successfully.

**Server**: `fortezo@137.184.32.193`
**Service**: `odoo14.service` (systemd)
**Config**: `/etc/odoo14-server.conf`
**DB**: `produccion`
**Python**: system `python3` (no venv)

---

## 1. Stop Odoo

```bash
sudo systemctl stop odoo14.service
sudo systemctl status odoo14.service
```

---

## 2. Open Odoo shell

```bash
sudo -u odoo14 python3 /odoo14/odoo14-server/odoo-bin shell -c /etc/odoo14-server.conf -d produccion
```

Wait for the `>>>` prompt.

---

## 3. Dry run (read-only)

Paste in shell:

```python
from datetime import datetime
cutoff = datetime(2025, 12, 31, 23, 59, 59)

pos = env['purchase.order'].search([
    ('state', '=', 'purchase'),
    ('date_approve', '<=', cutoff),
])
print(f"POs to update: {len(pos)}")
for po in pos[:15]:
    print(f"  {po.name} | confirmed: {po.date_approve} | vendor: {po.partner_id.name}")
```

- Check the count and sample rows.
- `date_approve` = confirmation date (when PO was set to PO Surtiendo).

---

## 4. Execute update

**Must run Step 3 first in the same shell session** — `pos` is defined by the dry-run search. If you run only this block, you get `NameError: name 'pos' is not defined`.

If the dry run looks correct, paste:

```python
pos.write({'state': 'hecho'})
env.cr.commit()
print(f"Done. {len(pos)} POs updated to 'hecho'.")
```

- If you get stuck on `...`, type `pass` and Enter until you see `>>>`, then paste again (one block at a time if needed).

---

## 5. Exit shell and restart Odoo

```python
exit()
```

```bash
sudo systemctl start odoo14.service
sudo systemctl status odoo14.service
```

---

## 6. Production checklist

- [ ] **Backup the database** before running.
- [ ] **Stop Odoo** (no other process writing to the same POs).
- [ ] Run **dry run** first and confirm count (~3,156).
- [ ] Run **execute** block, then **start Odoo** again.
- Downtime is typically under 2 minutes.

---

## 7. Filter reference

| Criterion         | Domain / value |
|-------------------|----------------|
| State             | `'purchase'` (PO Surtiendo) |
| Confirmation date | `date_approve <= datetime(2025, 12, 31, 23, 59, 59)` |
| Companies         | All (no company filter). UI count may differ if filtered by company. |

---

*Last updated: 2026-03-06*
