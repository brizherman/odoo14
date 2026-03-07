# Git – Commit & Push (Local → GitHub → Live Server)

> Simple flow. No branches. Always work on `main`.

---

### Daily flow – Local (Mac)

**1. Check what changed**
```bash
cd "/Users/gab/Cursor Projects/Odoo14"
git status
```

**2. Stage tracked changes only**
```bash
git add -u
```

**3. Commit**
```bash
git commit -m "fix: description (2026-03-06)"
```

Common commit types:
- `feat:` — new feature
- `fix:` — bug fix
- `perf:` — performance improvement
- `refactor:` — code restructure, no behavior change
- `chore:` — maintenance (gitignore, config, etc.)

**4. Push to GitHub**
```bash
git push origin main
```

---

### Live server – pull & deploy

```bash
ssh fortezo@137.184.32.193
cd /odoo14/custom/odoo14-repo
sudo git pull origin main
sudo chown -R odoo14:odoo14 /odoo14/custom/odoo14-repo
sudo find /odoo14/custom/odoo14-repo -type d -exec chmod 755 {} \;
sudo find /odoo14/custom/odoo14-repo -type f -exec chmod 644 {} \;
sudo systemctl restart odoo14
```

Then in browser → **Apps** → search `custom_purchase_flow` → **Upgrade**.

---

### If git pull fails on live server (conflict with .pyc files)

```bash
sudo git checkout -- .
sudo git pull origin main
```

> This won't happen again now that `.gitignore` excludes `__pycache__` and `.pyc` files.

---

### Useful extras

Check what branch you're on:
```bash
git branch
```

Check recent commits:
```bash
git log --oneline -5
```

Check what is tracked by git:
```bash
git ls-files
```

Undo last commit (keeps your file changes):
```bash
git reset --soft HEAD~1
```
