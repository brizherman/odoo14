from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database


class PosConfig(models.Model):
    _inherit = "pos.config"

    layaway_application_method_id = fields.Many2one(
        "pos.payment.method", check_company=True, ondelete="restrict",
        groups="account.group_account_manager", string="Método contable de liquidación de prueba",
    )


class ResCompany(models.Model):
    _inherit = "res.company"

    layaway_due_from_account_id = fields.Many2one(
        "account.account", check_company=True, ondelete="restrict",
        groups="account.group_account_manager", string="Por cobrar a otras tiendas de prueba",
    )
    layaway_due_to_account_id = fields.Many2one(
        "account.account", check_company=True, ondelete="restrict",
        groups="account.group_account_manager", string="Por pagar a otras tiendas de prueba",
    )


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    layaway_application = fields.Boolean(
        groups="account.group_account_manager", string="Aplicación contable de apartados de prueba",
    )


class PosPayment(models.Model):
    _inherit = "pos.payment"

    @api.constrains("payment_method_id", "pos_order_id", "amount")
    def _check_payment_method_id(self):
        applications = self.filtered(lambda pay: pay.payment_method_id.sudo().layaway_application)
        if (self - applications).pos_order_id.sudo().layaway_application_move_ids:
            raise AccessError(_("La aplicación de cobros conserva su registro original."))
        for payment in applications:
            if (
                not self.env.su or not layaway_test_database(self.env)
                or not payment.pos_order_id.layaway_ids
                or payment.pos_order_id.layaway_application_move_ids
                or payment.payment_method_id != payment.session_id.config_id.layaway_application_method_id
                or payment.currency_id.compare_amounts(payment.amount, payment.pos_order_id.amount_total)
            ):
                raise AccessError(_("El método de aplicación está reservado a liquidaciones de prueba."))
        return super(PosPayment, self - applications)._check_payment_method_id()

    def write(self, vals):
        if self.pos_order_id.sudo().layaway_application_move_ids:
            raise AccessError(_("La aplicación de cobros conserva su registro original."))
        return super().write(vals)

    def unlink(self):
        if self.pos_order_id.sudo().layaway_application_move_ids:
            raise AccessError(_("La aplicación de cobros conserva su registro original."))
        return super().unlink()


class PosSession(models.Model):
    _inherit = "pos.session"

    def _settle_layaway_if_paid(self, folio, operation, new_payments):
        """Apply the payment ledger once, inside the operation that covers the balance."""
        if folio.sale_id:
            return self._apply_layaway_adjustment_payments(folio, operation, new_payments)
        if not folio.currency_id.is_zero(folio.amount_due):
            return {}
        self._check_layaway_payment_test()
        if self.rescue or not self.currency_id == folio.currency_id == self.company_id.currency_id:
            raise UserError(_("La liquidación requiere una sesión ordinaria en la moneda del apartado."))
        session = self.sudo().with_context({}, allowed_company_ids=self.company_id.ids)
        folio = folio.with_env(session.env)
        folio._check_layaway_settlement_stock()
        sale = session._create_layaway_sale(folio, operation)
        payments = folio.payment_ids - new_payments
        previous = folio.currency_id.round(sum(payments.mapped("amount")))
        return {
            "sale_id": sale.id, "sale_name": sale.name,
            "settlement": {
                "amount_total": folio.amount_total, "amount_tax": sale.amount_tax,
                "amount_previous": previous,
                "previous_deposit": folio.currency_id.round(sum(
                    payments.filtered_domain([("kind", "=", "deposit")]).mapped("amount")
                )),
                "new_payment_ids": new_payments.ids, "previous_payment_ids": payments.ids,
                "ticket": operation._sale_ticket_snapshot(folio, new_payments),
                "pickup_state": folio.pickup_state,
                "lines": [{
                    "name": line.product_name, "store": line.warehouse_id.display_name,
                    "quantity": line.qty, "pending": line.qty_pending,
                    "price_unit": line.price_unit, "amount_tax": line.amount_tax,
                    "amount_total": line.amount_total,
                } for line in folio.line_ids],
            },
        }

    def _create_layaway_sale(self, folio, operation):
        company = self.company_id
        method = self.config_id.layaway_application_method_id
        bridge = method.receivable_account_id
        if (
            not method.active or not method.layaway_application or method.company_id != company
            or method.is_cash_count or method.use_payment_terminal or not method.split_transactions
            or method.config_ids or not bridge.reconcile or bridge.internal_type != "receivable"
            or not self._valid_layaway_application_account(bridge, company, "asset")
        ):
            raise UserError(_("Configura el método contable de liquidación de prueba de esta caja."))
        if not self.config_id.journal_id:
            raise UserError(_("Configura el diario de ventas de esta caja."))

        product_companies = folio.line_ids.product_id.company_id - company
        if product_companies or folio.partner_id.company_id - company:
            raise UserError(_("La venta de prueba requiere mercancía y cliente disponibles en su compañía."))
        position = self.env["account.fiscal.position"].get_fiscal_position(folio.partner_id.id)
        lines = [self._prepare_layaway_sale_line(line, position) for line in folio.line_ids]
        sale = self.env["pos.order"].create({
            "session_id": self.id, "user_id": operation.user_id.id,
            "date_order": operation.create_date, "partner_id": folio.partner_id.id,
            "fiscal_position_id": position.id, "pos_reference": folio.folio,
            "amount_total": folio.amount_total, "amount_return": 0, "amount_paid": 0,
            "amount_tax": folio.currency_id.round(sum(folio.line_ids.mapped("amount_tax"))),
            "lines": [(0, 0, values) for values in lines],
        })
        folio.write({"sale_id": sale.id})
        sale.add_payment({
            "pos_order_id": sale.id, "amount": folio.amount_total,
            "payment_method_id": method.id, "payment_date": operation.create_date,
        })
        sale.action_pos_order_paid()
        sale._create_order_picking()
        if folio.currency_id.compare_amounts(sum(folio.payment_ids.mapped("amount")), sale.amount_total):
            raise ValidationError(_("Los cobros confirmados deben coincidir con el total de la venta."))
        applied = self._apply_layaway_liabilities(
            folio, folio.payment_ids, bridge, local_date(operation.create_date, folio.timezone),
            "%s · %s" % (folio.folio, sale.name),
        )
        sale.write({"layaway_application_move_ids": [(6, 0, applied.ids)]})
        return sale

    def _prepare_layaway_sale_line(self, line, position):
        product = line.product_id
        taxes = product.taxes_id.filtered(lambda tax: tax.company_id == self.company_id)
        mapped = position.map_tax(taxes, product, line.layaway_id.partner_id)
        currency = line.currency_id
        subtotal = currency.round(line.amount_total - line.amount_tax)
        totals = mapped.compute_all(
            line.price_unit, currency, line.qty, product=product, partner=line.layaway_id.partner_id,
        )
        if (
            currency.compare_amounts(totals["total_included"], line.amount_total)
            or currency.compare_amounts(totals["total_excluded"], subtotal)
        ):
            raise UserError(_("Los impuestos en esta caja no reproducen el precio acordado de %s.")
                            % line.product_name)
        if not position.map_account(product._get_product_accounts()["income"]):
            raise UserError(_("Configura la cuenta de ingresos de %s en la compañía de la venta.")
                            % line.product_name)
        return {
            "product_id": product.id, "full_product_name": line.product_name,
            "qty": line.qty, "price_unit": line.price_unit, "price_subtotal": subtotal,
            "price_subtotal_incl": line.amount_total, "tax_ids": [(6, 0, taxes.ids)],
        }

    def _valid_layaway_application_account(self, account, company, group):
        return (
            account and account.company_id == company and account.internal_group == group
            and not account.deprecated
            and (not account.currency_id or account.currency_id == company.currency_id)
        )

    def _apply_layaway_liabilities(self, folio, payments, counterpart, date, ref):
        """Release each company's tender liabilities without creating any cash movement."""
        balances = defaultdict(lambda: defaultdict(float))
        company = self.company_id
        for payment in payments:
            move = payment.move_id
            external_reversals = move.reversal_move_id - payment.correction_ids.move_id
            if (
                move.state != "posted" and not (payment.statement_line_id and move.state == "draft")
                or any(reversal.state != "cancel" for reversal in external_reversals)
            ):
                raise ValidationError(_("El apartado contiene un cobro sin respaldo vigente."))
            original = payment.corrects_payment_id if payment.amount < 0 else payment
            liability = original._layaway_liability()
            if not self._valid_layaway_application_account(liability, payment.company_id, "liability"):
                raise UserError(_("La cuenta de pasivo de un cobro ya no está disponible."))
            balances[payment.company_id][liability] += payment.amount

        currency = folio.currency_id
        seller = [(account, amount, False) for account, amount in balances.pop(company, {}).items()]
        moves = self.env["account.move"]
        for receiver, group in balances.items():
            net = currency.round(sum(group.values()))
            lines = [(account, amount, False) for account, amount in group.items()]
            if net:
                due_from = company.layaway_due_from_account_id
                due_to = receiver.layaway_due_to_account_id
                if (
                    not self._valid_layaway_application_account(due_from, company, "asset")
                    or not self._valid_layaway_application_account(due_to, receiver, "liability")
                    or due_from == counterpart or due_to in group
                ):
                    raise UserError(_("Configura las cuentas de aplicación de prueba entre compañías."))
                seller.append((due_from, net, receiver.partner_id.id))
                lines.append((due_to, -net, company.partner_id.id))
            receiving_config = payments.filtered(
                lambda payment: payment.company_id == receiver
            )[0].config_id
            moves |= self._post_layaway_application(
                receiving_config.layaway_card_journal_id, lines, date, ref, receiver,
            )
        seller.append((counterpart, -sum(payments.mapped("amount")), folio.partner_id.commercial_partner_id.id))
        return moves | self._post_layaway_application(
            self.config_id.layaway_card_journal_id, seller, date, ref, company,
        )

    def _post_layaway_application(self, journal, lines, date, ref, company):
        if journal.company_id != company or journal.type != "general":
            raise UserError(_("Configura un diario general de prueba para aplicar los cobros."))
        currency = company.currency_id
        commands = []
        for account, amount, partner_id in lines:
            amount = currency.round(amount)
            if amount:
                commands.append((0, 0, {
                    "name": ref, "account_id": account.id, "partner_id": partner_id,
                    "debit": max(amount, 0), "credit": max(-amount, 0),
                }))
        if not commands:
            return self.env["account.move"]
        move = self.env["account.move"].with_context(allowed_company_ids=company.ids).create({
            "journal_id": journal.id, "move_type": "entry", "ref": ref, "date": date,
            "line_ids": commands,
        })
        move.action_post()
        return move


class PosLayaway(models.Model):
    _inherit = "pos.layaway"

    def _check_layaway_settlement_stock(self):
        self.ensure_one()
        lines = self.line_ids.filtered("qty_pending")
        if not lines or not self.sale_id and self.pickup_state != "pending":
            raise UserError(_("La liquidación requiere mercancía pendiente de recogida."))
        moves = self.env["stock.move"].search([
            ("layaway_line_id", "in", lines.ids), ("state", "not in", ("done", "cancel")),
        ])
        # Lock the reservation itself as stock operations can change it outside the POS.
        for table, ids in (
            ("stock_picking", moves.picking_id.ids), ("stock_move", moves.ids),
            ("stock_move_line", moves.move_line_ids.ids),
        ):
            if ids:
                self.env.cr.execute(
                    "SELECT id FROM %s WHERE id IN %%s ORDER BY id FOR UPDATE" % table, (tuple(ids),),
                )
        by_line = defaultdict(lambda: self.env["stock.move"])
        for move in moves:
            by_line[move.layaway_line_id.id] |= move
        for line in lines:
            move = by_line[line.id]
            if (
                len(move) != 1 or move.picking_id.layaway_id != self
                or move.state != "assigned" or move.picking_id.state != "assigned"
                or move.product_id != line.product_id or move.location_id != line.location_id
                or move.company_id != line.warehouse_id.company_id
                or move.product_uom != line.product_id.uom_id
                or float_compare(move.reserved_availability, line.qty_pending,
                                 precision_rounding=line.product_id.uom_id.rounding)
                or any(move.move_line_ids.mapped("qty_done"))
            ):
                raise UserError(_("La reserva de %s en %s debe estar completa antes de liquidar.")
                                % (line.product_name, line.warehouse_id.display_name))
