from psycopg2 import sql

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


REVISION_FIELD = "pos_customer_data_revision"
COMPANY_REVISION_FIELD = "pos_customer_pricing_revision"


def _invalidate_pricing_context(env, company_ids=None):
    """Invalidate technical evidence only; never change business permissions."""
    query = """
        UPDATE res_company SET pos_customer_pricing_revision =
            COALESCE(pos_customer_pricing_revision, 0) + 1
    """
    if company_ids:
        env.cr.execute(query + " WHERE id IN %s", [tuple(company_ids)])
    else:
        env.cr.execute(query)
    env["res.company"].invalidate_cache([COMPANY_REVISION_FIELD])


class PricingRevisionMixin(models.AbstractModel):
    _name = "pos.customer.data.revision.mixin"
    _description = "Internal revision for customer pricelist evidence"

    pos_customer_data_revision = fields.Integer(readonly=True, copy=False)

    def _pos_changes_pricing_context(self):
        if self._name != "ir.property":
            return True
        return any(
            p.name == "property_product_pricelist" and not p.res_id for p in self
        )

    def _pos_context_company_ids(self):
        if self._name in ("ir.property", "product.pricelist"):
            if all(p.company_id for p in self):
                return set(self.mapped("company_id").ids)
        return None

    @api.model_create_multi
    def create(self, vals_list):
        if (any(REVISION_FIELD in values for values in vals_list)
                or "default_%s" % REVISION_FIELD in self.env.context):
            raise AccessError(_("La revisión de tarifas es de solo lectura."))
        records = super().create(vals_list)
        if records._pos_changes_pricing_context():
            _invalidate_pricing_context(
                self.env, records._pos_context_company_ids(),
            )
        return records

    def write(self, vals):
        if REVISION_FIELD in vals:
            raise AccessError(_("La revisión de tarifas es de solo lectura."))
        context_changed = self._pos_changes_pricing_context()
        companies_before = self._pos_context_company_ids()
        result = super().write(vals)
        if self and vals:
            # Odoo datetimes have second precision. A monotonic revision detects
            # A -> B -> A even within one second and concurrent source writes.
            query = sql.SQL(
                "UPDATE {} SET {} = COALESCE({}, 0) + 1 WHERE id IN %s"
            ).format(
                sql.Identifier(self._table),
                sql.Identifier(REVISION_FIELD), sql.Identifier(REVISION_FIELD),
            )
            self.env.cr.execute(query, [tuple(self.ids)])
            self.invalidate_cache([REVISION_FIELD])
            if context_changed or self._pos_changes_pricing_context():
                companies_after = self._pos_context_company_ids()
                companies = (
                    companies_before | companies_after
                    if companies_before and companies_after else None
                )
                _invalidate_pricing_context(self.env, companies)
        return result

    def unlink(self):
        companies = self._pos_context_company_ids()
        context_changed = self._pos_changes_pricing_context() or (
            self._name == "ir.property" and any(
                p.name == "property_product_pricelist" for p in self
            )
        )
        result = super().unlink()
        if context_changed:
            _invalidate_pricing_context(self.env, companies)
        return result


class IrProperty(models.Model):
    _name = "ir.property"
    _inherit = ["ir.property", "pos.customer.data.revision.mixin"]


class ProductPricelist(models.Model):
    _name = "product.pricelist"
    _inherit = ["product.pricelist", "pos.customer.data.revision.mixin"]


class ResCountryGroup(models.Model):
    _name = "res.country.group"
    _inherit = ["res.country.group", "pos.customer.data.revision.mixin"]


class ResCountry(models.Model):
    _name = "res.country"
    _inherit = ["res.country", "pos.customer.data.revision.mixin"]


class ResCompany(models.Model):
    _inherit = "res.company"

    pos_customer_pricing_revision = fields.Integer(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if (any(COMPANY_REVISION_FIELD in values for values in vals_list)
                or "default_%s" % COMPANY_REVISION_FIELD in self.env.context):
            raise AccessError(_("La revisión de tarifas es de solo lectura."))
        return super().create(vals_list)

    def write(self, vals):
        if COMPANY_REVISION_FIELD in vals:
            raise AccessError(_("La revisión de tarifas es de solo lectura."))
        return super().write(vals)
