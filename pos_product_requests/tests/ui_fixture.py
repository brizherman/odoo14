"""Seed an isolated host-browser test database from the Odoo shell."""
import json

from odoo.tests.common import new_test_user


def create_ui_fixture(env):
    if not (env.cr.dbname == "odoo_test" or env.cr.dbname.startswith("odoo_test_")):
        raise ValueError("UI fixtures require an odoo_test database")

    env["base.language.install"].create({"lang": "es_MX"}).lang_install()

    def account(code, name, account_type, reconcile=False):
        return env["account.account"].create({
            "code": code,
            "name": name,
            "user_type_id": env.ref("account.data_account_type_" + account_type).id,
            "reconcile": reconcile,
            "company_id": env.company.id,
        })

    receivable = account("REQ01", "Requests UI receivable", "receivable", True)
    income = account("REQ02", "Requests UI sales", "revenue")
    cash = account("REQ03", "Requests UI cash", "liquidity")
    env.company.account_default_pos_receivable_account_id = receivable
    env["ir.property"]._set_default(
        "property_account_receivable_id", "res.partner", receivable, env.company,
    )
    journal = env["account.journal"].create({
        "name": "Requests UI sales", "code": "REQ", "type": "sale",
        "default_account_id": income.id,
    })
    cash_journal = env["account.journal"].create({
        "name": "Requests UI cash", "code": "REQC", "type": "cash",
        "default_account_id": cash.id,
        "profit_account_id": income.id,
        "loss_account_id": income.id,
    })
    payment = env["pos.payment.method"].create({
        "name": "Efectivo de prueba", "is_cash_count": True,
        "cash_journal_id": cash_journal.id,
        "receivable_account_id": receivable.id,
    })
    user = new_test_user(
        env, login="requests_ui", password="requests-ui-test",
        groups="base.group_user,point_of_sale.group_pos_manager",
        lang="es_MX", tz="America/Tijuana",
    )

    def create_config(name, manage_orders):
        config = env["pos.config"].create({
            "name": name,
            "manage_orders": manage_orders,
            "journal_id": journal.id,
            "invoice_journal_id": journal.id,
            "payment_method_ids": [(6, 0, payment.ids)],
            "cash_control": False,
            "iface_print_auto": False,
            "iface_print_skip_screen": False,
        })
        env["pos.session"].create({"config_id": config.id, "user_id": user.id})
        return config

    first = create_config("Faltantes UI con lupa", True)
    second = create_config("Faltantes UI sin lupa", False)
    product = env["product.product"].create({
        "name": "Producto de prueba POS", "available_in_pos": True, "list_price": 10,
        "barcode": "1234567890128",
        "taxes_id": [(5, 0, 0)], "property_account_income_id": income.id,
    })
    return {
        "database": env.cr.dbname, "login": user.login,
        "first_config": first.id, "second_config": second.id, "product": product.id,
    }


fixture = create_ui_fixture(env)
env.cr.commit()
print(json.dumps(fixture))
