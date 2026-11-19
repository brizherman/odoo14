"""Self-contained test data; only call on an isolated odoo_test database."""
from odoo.tests.common import new_test_user


def create_ui_fixture(env, open_session=True):
    if not (env.cr.dbname == "odoo_test" or env.cr.dbname.startswith("odoo_test_")):
        raise ValueError("UI fixtures require an odoo_test database")

    def account(code, name, account_type, reconcile=False):
        return env["account.account"].create({
            "code": code, "name": name, "reconcile": reconcile,
            "user_type_id": env.ref("account." + account_type).id,
            "company_id": env.company.id,
        })

    receivable = account("CUI01", "UI receivable", "data_account_type_receivable", True)
    payable = account("CUI02", "UI payable", "data_account_type_payable", True)
    income = account("CUI03", "UI sales", "data_account_type_revenue")
    cash = account("CUI04", "UI cash", "data_account_type_liquidity")
    env.company.account_default_pos_receivable_account_id = receivable
    for field, value in (("property_account_receivable_id", receivable),
                         ("property_account_payable_id", payable)):
        env["ir.property"]._set_default(field, "res.partner", value, env.company)
    journal = env["account.journal"].create({
        "name": "UI sales", "code": "CUI", "type": "sale",
        "default_account_id": income.id,
    })
    cash_journal = env["account.journal"].create({
        "name": "UI cash", "code": "CUIC", "type": "cash",
        "default_account_id": cash.id,
        "profit_account_id": income.id, "loss_account_id": income.id,
    })
    payment = env["pos.payment.method"].create({
        "name": "Review Cash", "is_cash_count": True,
        "cash_journal_id": cash_journal.id,
        "receivable_account_id": receivable.id,
    })
    prices = env["product.pricelist"]
    for name in ("Lista de precios a Publico en General", "Lista de precios de Mayorista",
                 "Super Precios a Distribuidores"):
        prices |= prices.create({"name": name, "company_id": env.company.id,
                                 "currency_id": env.company.currency_id.id})
    config = env["pos.config"].create({
        "customer_data_review_enabled": True,
        "name": "Customer review UI", "journal_id": journal.id,
        "invoice_journal_id": journal.id, "pricelist_id": prices[0].id,
        "available_pricelist_ids": [(6, 0, prices.ids)], "use_pricelist": True,
        "payment_method_ids": [(6, 0, payment.ids)], "cash_control": False,
        "iface_print_auto": False, "iface_print_skip_screen": False,
    })
    product = env["product.product"].create({
        "name": "Review product", "available_in_pos": True, "list_price": 10,
        "taxes_id": [(5, 0, 0)], "property_account_income_id": income.id,
    })
    user = new_test_user(
        env, login="customer_review_ui", password="customer-review-ui-test",
        groups="base.group_user,base.group_partner_manager,point_of_sale.group_pos_manager",
        tz="America/Tijuana",
    )
    partner = env["res.partner"].create({
        "name": "Review UI customer", "mobile": "6640000000",
        "customer_type": "publico_general",
        "property_product_pricelist": prices[0].id,
    })
    historical = partner.copy({
        "name": "Review historical customer",
        "property_product_pricelist": prices[0].id,
    })
    historical.flush()
    env.cr.execute("""UPDATE res_partner SET pos_name_updated_at = NULL,
        pos_mobile_updated_at = '2021-01-01 12:00:00',
        pos_customer_type_updated_at = NULL WHERE id = %s""", [historical.id])
    historical.invalidate_cache()
    if open_session:
        config.with_user(user).open_session_cb()
    return {"config_id": config.id, "product_id": product.id,
            "partner_id": partner.id, "historical_id": historical.id,
            "payment_id": payment.id, "pricelist_ids": prices.ids,
            "login": user.login}


def create_combo_ui_fixture(env):
    """Enable existing commercial controls only in a synthetic test company."""
    fixture = create_ui_fixture(env, open_session=False)
    company = env.company
    config = env["pos.config"].browse(fixture["config_id"])
    employee = env["hr.employee"].create({"name": "Review test salesperson"})
    config.pos_salesperson_ids = employee
    fixture["salesperson_id"] = employee.id
    retail, wholesale, distributor = env["product.pricelist"].browse(fixture["pricelist_ids"])
    for price, amount in ((wholesale, 6), (distributor, 5)):
        env["product.pricelist.item"].create({
            "pricelist_id": price.id, "applied_on": "3_global",
            "compute_price": "fixed", "fixed_price": amount,
        })
    company._pos_configs().write({
        "use_pricelist": True,
        "available_pricelist_ids": [(6, 0, fixture["pricelist_ids"])],
        "pricelist_id": retail.id,
    })
    mappings = env["pos.wholesale.pricelist.mapping"]
    for customer_type in ("publico_general", "mayorista", "mayorista_dormido", "distribuidores"):
        values = {"customer_type": customer_type, "company_id": company.id,
                  "pricelist_id": (distributor if customer_type == "distribuidores" else wholesale).id}
        existing = mappings.with_context(active_test=False).search([
            ("company_id", "=", company.id), ("customer_type", "=", customer_type),
        ])
        if existing:
            existing.write(dict(values, active=True))
        else:
            mappings.create(values)
    company.write({
        "wholesale_retail_pricelist_id": retail.id,
        "wholesale_pricelist_id": wholesale.id,
        "wholesale_control_active": True,
    })
    user = env["res.users"].search([("login", "=", fixture["login"])])
    config.with_user(user).open_session_cb()
    return fixture
