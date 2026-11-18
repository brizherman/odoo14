from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database


class AccountMove(models.Model):
    _inherit = "account.move"

    layaway_adjustment_id = fields.Many2one(
        "pos.layaway.operation", string="Ajuste de mercancía de apartado",
        index=True, ondelete="restrict", copy=False, readonly=True,
    )

    _sql_constraints = [
        ("layaway_adjustment_unique", "UNIQUE(layaway_adjustment_id)",
         "La operación ya tiene un documento de ajuste."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        if (self.env.context.get("default_layaway_adjustment_id")
                or any(vals.get("layaway_adjustment_id") for vals in vals_list)):
            if not self.env.su or not layaway_test_database(self.env):
                raise AccessError(_("El ajuste requiere una operación de prueba del servidor."))
        return super().create(vals_list)

    def write(self, vals):
        if "layaway_adjustment_id" in vals or (
            vals.get("state") in ("draft", "cancel") and self.sudo().layaway_adjustment_id
        ):
            raise AccessError(_("El documento conserva su ajuste original."))
        return super().write(vals)

    def _stock_account_prepare_anglo_saxon_out_lines_vals(self):
        # The reserved merchandise has no stock valuation to recognize yet.
        ordinary = self.filtered(lambda move: not move.layaway_adjustment_id)
        return super(AccountMove, ordinary)._stock_account_prepare_anglo_saxon_out_lines_vals()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        if self.sudo().layaway_adjustment_id:
            raise UserError(_("El ajuste de mercancía se corrige desde el apartado."))
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)


class PosLayaway(models.Model):
    _inherit = "pos.layaway"

    def _layaway_adjustable_sale(self):
        return bool(self.sale_id.layaway_application_move_ids)

    def _layaway_can_modify_products(self, now):
        return (
            self.pickup_state != "done"
            and local_date(now, self.timezone) <= self.addition_end
            and (not self.sale_id or self._layaway_adjustable_sale())
        )

    def _layaway_adjustment_moves(self):
        return self.env["account.move"].search([
            ("layaway_adjustment_id.layaway_id", "=", self.id),
        ], order="id")

    def _layaway_adjustment_history(self):
        if not self.sale_id:
            return []
        return [{
            "name": move.name,
            "reference": move.layaway_adjustment_id.reference,
            "amount": move.amount_total * (-1 if move.move_type == "out_refund" else 1),
        } for move in self._layaway_adjustment_moves()]


class PosSession(models.Model):
    _inherit = "pos.session"

    def _post_layaway_adjustment(self, folio, operation, added, removed=None):
        if not folio.sale_id:
            return {}
        self._check_layaway_payment_test()
        sale = folio.sale_id
        seller = sale.session_id.with_context({}, allowed_company_ids=sale.company_id.ids)
        sale = sale.with_env(seller.env)
        currency = sale.currency_id
        journal = sale.config_id.layaway_adjustment_journal_id
        if not journal or journal.company_id != sale.company_id or journal.type != "sale" or (
            "edi_format_ids" in journal._fields and journal.edi_format_ids
        ):
            raise UserError(_("El ajuste de prueba requiere un diario de ventas sin formatos electrónicos."))

        removed = removed if removed is not None else added.browse()
        delta = currency.round(sum(added.mapped("amount_total")) - sum(removed.mapped("amount_total")))
        tax = currency.round(sum(added.mapped("amount_tax")) - sum(removed.mapped("amount_tax")))
        direction = -1 if delta < 0 else 1
        commands = []
        for lines, sign in ((added, direction), (removed, -direction)):
            for line in lines.with_env(seller.env):
                if line.product_id.company_id and line.product_id.company_id != sale.company_id:
                    raise UserError(_("La mercancía del ajuste debe estar disponible en la compañía de la venta."))
                commands.append((0, 0, seller._prepare_layaway_adjustment_line(
                    line, sale.fiscal_position_id, sign,
                )))
        date = local_date(operation.create_date, folio.timezone)
        move = seller.env["account.move"].create({
            "layaway_adjustment_id": operation.id,
            "move_type": "out_refund" if delta < 0 else "out_invoice",
            "journal_id": journal.id,
            "ref": "%s · %s · %s" % (folio.folio, sale.name, operation.reference),
            "invoice_origin": sale.name,
            "invoice_date": date,
            "partner_id": sale.partner_id.id,
            "currency_id": currency.id,
            "fiscal_position_id": sale.fiscal_position_id.id,
            "invoice_line_ids": commands,
        })
        if (currency.compare_amounts(move.amount_total, delta * direction)
                or currency.compare_amounts(move.amount_tax, tax * direction)):
            raise ValidationError(_("El ajuste contable debe reproducir los importes acordados."))
        move.action_post()
        return {
            "sale_id": sale.id, "sale_name": sale.name,
            "sale_adjustment": {
                "id": move.id, "name": move.name, "amount": delta, "tax": tax,
            },
        }

    def _prepare_layaway_adjustment_line(self, line, position, sign):
        values = self._prepare_layaway_sale_line(line, position)
        product = line.product_id
        taxes = self.env["account.tax"].browse(values["tax_ids"][0][2])
        return {
            "product_id": product.id, "name": line.product_name, "quantity": line.qty * sign,
            "price_unit": line.price_unit,
            "account_id": position.map_account(product._get_product_accounts()["income"]).id,
            "tax_ids": [(6, 0, position.map_tax(taxes, product, line.layaway_id.partner_id).ids)],
        }

    def _apply_layaway_adjustment_payments(self, folio, operation, payments):
        self._check_layaway_payment_test()
        sale = folio.sale_id
        seller = sale.session_id.with_context({}, allowed_company_ids=sale.company_id.ids)
        folio = folio.with_env(seller.env)
        moves = folio._layaway_adjustment_moves()
        if not moves or any(move.state != "posted" for move in moves):
            raise ValidationError(_("El apartado requiere un ajuste contable vigente."))
        receivable = moves.line_ids.filtered(
            lambda line: line.account_id.internal_type == "receivable"
        )
        open_lines = receivable.filtered(lambda line: not line.reconciled and line.amount_residual)
        counterpart = open_lines.account_id
        if len(counterpart) > 1:
            raise ValidationError(_("Los ajustes deben conservar la misma cuenta por cobrar."))
        applied = seller.env["account.move"]
        applied_lines = seller.env["account.move.line"]
        if payments:
            if not counterpart:
                raise ValidationError(_("El cobro debe aplicarse a un ajuste pendiente."))
            applied = seller._apply_layaway_liabilities(
                folio, payments.with_env(seller.env), counterpart,
                local_date(operation.create_date, folio.timezone),
                "%s · %s · %s" % (folio.folio, sale.name, operation.reference),
            )
            applied_lines = applied.line_ids.filtered(lambda line: line.account_id == counterpart)
            open_lines |= applied_lines
        if any(line.amount_residual > 0 for line in open_lines) and any(
            line.amount_residual < 0 for line in open_lines
        ):
            open_lines.reconcile()
        if (folio.currency_id.compare_amounts(sum(receivable.mapped("amount_residual")), folio.amount_due)
                or any(applied_lines.mapped("amount_residual"))):
            raise ValidationError(_("El restante del folio debe coincidir con los ajustes contables."))
        if folio.currency_id.is_zero(folio.amount_due):
            folio._check_layaway_settlement_stock()
        return {
            "sale_id": sale.id, "sale_name": sale.name,
            "adjustment_payment": {
                "payment_ids": payments.ids,
                "adjustment_ids": applied_lines.matched_debit_ids.debit_move_id.move_id.ids,
                "application_move_ids": applied.ids,
            },
        } if payments else {}


class PosConfig(models.Model):
    _inherit = "pos.config"

    layaway_adjustment_journal_id = fields.Many2one(
        "account.journal", domain="[('type', '=', 'sale')]", check_company=True,
        ondelete="restrict", groups="account.group_account_manager",
        string="Diario de ajustes de apartados de prueba",
    )
