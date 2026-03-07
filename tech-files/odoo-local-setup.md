# Odoo 14 Local Development Setup (macOS)

**Date:** Feb 27, 2026  
**Production Server:** 137.184.32.193  
**Production User:** fortezo  
**Local Folders:**
- Source: `/Users/gab/Cursor Projects/Odoo14/odoo-src/odoo14-server`
- Custom Modules: `/Users/gab/Cursor Projects/Odoo14/odoo-src/custom`

---

## Step 1 — Fix PostgreSQL PATH

PostgreSQL 16 is already installed and running. Add it to your PATH:

```bash
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Verify it works:

```bash
psql --version
```

---

## Step 2 — Create the Odoo PostgreSQL user

```bash
createuser -s odoo14
```

---

## Step 3 — Download Odoo source files from production server

Compressing on the server first and downloading as a single file is much faster than rsync (thousands of individual files).

### 3a — SSH into the server and compress

```bash
ssh fortezo@137.184.32.193
```

Run on the server:

```bash
tar -czf /tmp/odoo14-server.tar.gz /odoo14/odoo14-server/
tar -czf /tmp/odoo14-custom.tar.gz /odoo14/custom/
```

### 3b — Exit the server and download both files

```bash
exit
```

```bash
scp fortezo@137.184.32.193:/tmp/odoo14-server.tar.gz "/Users/gab/Cursor Projects/Odoo14/"
scp fortezo@137.184.32.193:/tmp/odoo14-custom.tar.gz "/Users/gab/Cursor Projects/Odoo14/"
```

### 3c — Extract locally

```bash
tar -xzf "/Users/gab/Cursor Projects/Odoo14/odoo14-server.tar.gz" -C "/Users/gab/Cursor Projects/Odoo14/odoo-src/odoo14-server/" --strip-components=2

tar -xzf "/Users/gab/Cursor Projects/Odoo14/odoo14-custom.tar.gz" -C "/Users/gab/Cursor Projects/Odoo14/odoo-src/custom/" --strip-components=2
```

---

## Step 4 — Install system dependencies

```bash
brew install libxml2 libxslt libjpeg openssl libffi
```

---

## Step 5 — Install Python 3.8 (required for Odoo 14)

Odoo 14 officially supports Python 3.6 to 3.8. Your system has Python 3.11 which is too new for the original dependencies. Use pyenv to install Python 3.8:

```bash
pyenv install 3.8.18
```

Set Python 3.8 as the local version for this project:

```bash
cd "/Users/gab/Cursor Projects/Odoo14"
pyenv local 3.8.18
python --version
```

It should show `Python 3.8.18`.

---

## Step 6 — Create the virtual environment with Python 3.8

### 6a — Deactivate any existing venv first

⚠️ You MUST deactivate before deleting. If `(venv)` appears in your terminal prompt, run:

```bash
deactivate
```

Your prompt should no longer show `(venv)`.

### 6b — Delete the old venv and recreate with Python 3.8

```bash
cd "/Users/gab/Cursor Projects/Odoo14"
rm -rf venv
python -m venv venv
source venv/bin/activate
python --version
```

It should show `Python 3.8.18` inside the venv.

---

## Step 7 — Install Python dependencies

⚠️ The `requirements.txt` has been updated to fix macOS compatibility issues (gevent, reportlab, Pillow versions). Make sure venv is activated before running.

```bash
cd "/Users/gab/Cursor Projects/Odoo14/odoo-src/odoo14-server"
pip install wheel setuptools "Cython<3.0"
pip install gevent==20.9.0 --no-build-isolation
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Step 8 — Create local config file

```bash
cat > "/Users/gab/Cursor Projects/Odoo14/odoo-src/odoo14-local.conf" << 'EOF'
[options]
admin_passwd = f0rt3zyn0z
http_port = 8069
db_host = localhost
db_port = 5432
db_user = odoo14
db_password = False
addons_path = /Users/gab/Cursor Projects/Odoo14/odoo-src/odoo14-server/addons,/Users/gab/Cursor Projects/Odoo14/odoo-src/custom/addons
logfile = False
workers = 0
limit_memory_hard = 0
limit_memory_soft = 0
EOF
```

⚠️ `limit_memory_hard = 0` and `limit_memory_soft = 0` are required on macOS to avoid a startup crash.

---

## Step 9 — Run Odoo locally

Use the start script (do Step 10 first to have the production database, or create a fresh DB from the browser):

```bash
cd "/Users/gab/Cursor Projects/Odoo14"
chmod +x start-odoo14.sh
./start-odoo14.sh
```

Open your browser at: **http://localhost:8069**

---

## Step 10 — Restore production database

⚠️ Do NOT use the Odoo web UI backup — it crashes on large databases. Use `pg_dump` directly.

The production database name is: **`produccion`**

### 10a — SSH into the server

```bash
ssh fortezo@137.184.32.193
```

### 10b — Dump the database on the server

⚠️ Must run as `odoo14` system user — peer authentication required:

```bash
sudo -u odoo14 pg_dump -Fc produccion > /tmp/odoo14_produccion.dump
```

Wait for the prompt to return before continuing.

### 10c — Compress the filestore

```bash
sudo -u odoo14 tar -czf /tmp/odoo14_filestore.tar.gz /odoo14/.local/share/Odoo/filestore/produccion/
```

### 10d — Exit the server

```bash
exit
```

### 10e — Download both files to your Mac

```bash
scp fortezo@137.184.32.193:/tmp/odoo14_produccion.dump "/Users/gab/Cursor Projects/Odoo14/"
scp fortezo@137.184.32.193:/tmp/odoo14_filestore.tar.gz "/Users/gab/Cursor Projects/Odoo14/"
```

### 10f — Create local database and restore

```bash
createdb -U odoo14 produccion
pg_restore -U odoo14 -d produccion "/Users/gab/Cursor Projects/Odoo14/odoo14_produccion.dump"
```

### 10g — Restore the filestore (external drive, no local storage used)

The filestore lives entirely on `mkt-biz`. Nothing is stored on the Mac.

**Step 1 — Extract to external drive:**

Make sure `mkt-biz` is plugged in, then run:

```bash
mkdir -p "/Volumes/mkt-biz/filestore/produccion/"
tar -xzf "/Volumes/mkt-biz/filestore_backup.tar.gz" -C "/Volumes/mkt-biz/filestore/" --strip-components=5
```

**Step 2 — Symlink so Odoo finds it:**

```bash
mkdir -p "$HOME/Library/Application Support/Odoo/filestore/"
ln -s "/Volumes/mkt-biz/filestore/produccion" "$HOME/Library/Application Support/Odoo/filestore/produccion"
```

Now Odoo reads/writes directly from `mkt-biz`. Keep the drive plugged in whenever running Odoo.

⚠️ If you unplug the drive and restart Odoo, it will not find the filestore. Always plug in `mkt-biz` before starting Odoo.

⚠️ The filestore is 14GB+ and the tar compression takes 30-60 min on the server. For developing modules that don't involve images/attachments, you can skip 10c, 10e (filestore only) and 10g entirely.


### 10h — Update the start script to use the production database

The `start-odoo14.sh` script already uses `-d produccion`. Verify it is set correctly.
### 10i — Start Odoo and verify

```bash
./start-odoo14.sh
```

Open **http://localhost:8069** — you should see your production data.

---

## Daily Development Workflow

To start Odoo locally each day:

```bash
./start-odoo14.sh
```

To update a specific module after changes:

```bash
cd "/Users/gab/Cursor Projects/Odoo14"
source venv/bin/activate
python odoo-src/odoo14-server/odoo-bin -c odoo-src/odoo14-local.conf -u your_module_name -d produccion
```

---

## Server Info Summary

| Setting | Value |
|---|---|
| Production IP | 137.184.32.193 |
| Odoo Port | 8069 |
| Admin Password | f0rt3zyn0z |
| Odoo Source | /odoo14/odoo14-server |
| Custom Modules | /odoo14/custom/addons |
| Log File | /var/log/odoo14/odoo14-server.log |
| DB User | odoo14 |
| Workers | 0 |
