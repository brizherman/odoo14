## Deploying `custom_purchase_flow` to Live (Odoo 14)

This document explains how to package, upload, and deploy the `custom_purchase_flow` module from your local machine (Mac) to the live server.

Assumptions:
- Local project path: `/Users/gab/Cursor Projects/Odoo14`
- Live server SSH: `fortezo@137.184.32.193`
- Live addons path: `/odoo14/custom/addons`
- Odoo service name: `odoo14`
- Odoo system user: `odoo14`

> Run all commands **exactly in this order**.

---

### 1. On your Mac – go to the project

```bash
cd "/Users/gab/Cursor Projects/Odoo14"
```

### 2. On your Mac – create a clean tar of the module

```bash
tar czf custom_purchase_flow.tar.gz \
  --exclude='.DS_Store' \
  --exclude='._*' \
  custom_purchase_flow
```

### 3. On your Mac – upload tar to your home on the live server

```bash
scp custom_purchase_flow.tar.gz fortezo@137.184.32.193:~
```

---

### 4. On the live server – SSH in

```bash
ssh fortezo@137.184.32.193
```

### 5. On the live server – extract the tar in your home

```bash
cd ~
tar xzf custom_purchase_flow.tar.gz
```

This creates a `~/custom_purchase_flow` directory with the module contents.

### 6. On the live server – replace the module in the Odoo addons path

```bash
sudo rm -rf /odoo14/custom/addons/custom_purchase_flow
sudo cp -a ~/custom_purchase_flow /odoo14/custom/addons/
```

---

### 7. On the live server – set correct permissions on the module

Set owner to the Odoo system user:

```bash
sudo chown -R odoo14:odoo14 /odoo14/custom/addons/custom_purchase_flow
```

Set directory and file permissions:

```bash
sudo find /odoo14/custom/addons/custom_purchase_flow -type d -exec chmod 755 {} \;
sudo find /odoo14/custom/addons/custom_purchase_flow -type f -exec chmod 644 {} \;
```

---

### 8. On the live server – restart Odoo 14

```bash
sudo systemctl restart odoo14
```

---

### 9. In the browser – upgrade the module

1. Open `http://137.184.32.193/` in your browser.
2. Go to **Apps**.
3. Search for `custom_purchase_flow`.
4. Click **Upgrade**.

