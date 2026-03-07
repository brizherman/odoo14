# Odoo 14 — Test & Lint Command Guide

Use these from the project root. **Always activate `venv` first.**

---

## 1. Activate environment

```bash
cd "/Users/gab/Cursor Projects/Odoo14"
source venv/bin/activate
```

---

## 2. Run Odoo tests (module)

Runs the test suite for a module and stops Odoo when done (no server left running).

```bash
python odoo-src/odoo14-server/odoo-bin -c odoo-src/odoo14-local.conf \
  -d produccion \
  --test-enable \
  --stop-after-init \
  -u custom_purchase_flow
```

| Flag | Purpose |
|------|--------|
| `-c odoo-src/odoo14-local.conf` | Config file |
| `-d produccion` | Database name (change if yours is different) |
| `--test-enable` | Run tests after update |
| `--stop-after-init` | Exit after init/tests (no long-running server) |
| `-u custom_purchase_flow` | Module to update and test |

**Run only specific test tags (optional):**

```bash
python odoo-src/odoo14-server/odoo-bin -c odoo-src/odoo14-local.conf \
  -d produccion \
  --test-enable \
  --stop-after-init \
  --test-tags custom_purchase_flow \
  -u custom_purchase_flow
```

---

## 3. Lint Python (custom module only)

**Option A — Python syntax check (no extra install):**

```bash
for f in custom_purchase_flow/models/*.py custom_purchase_flow/wizard/*.py custom_purchase_flow/tests/*.py custom_purchase_flow/hooks.py; do python -m py_compile "$f" 2>&1; done
```

**Option B — flake8 (install in venv first: `pip install flake8`):**

```bash
flake8 custom_purchase_flow --max-line-length=120 --extend-ignore=E501,W503
```

**Option C — Ruff (install in venv first: `pip install ruff`):**

```bash
ruff check custom_purchase_flow --line-length 120
```

---

## 4. Paste results back

- Copy the **full terminal output** of the test and/or lint command.
- Paste it in chat so any failures or lint issues can be fixed.

---

## 5. Last run (for reference)

- **Odoo tests** (custom_purchase_flow): **24 tests, 0 failed, 0 errors.**
- **Python syntax**: all `custom_purchase_flow` `.py` files compile.
- **IDE linter**: no issues in `custom_purchase_flow` (run **Read Lints** in Cursor if needed).

*Project: Odoo14 — Last updated: 2026-03-04*
