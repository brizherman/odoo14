# -*- coding: utf-8 -*-


class SucursalMatcher:
    """Resolve sheet sucursal strings to Odoo companies."""

    def __init__(self, env):
        self.env = env
        self.Mapping = env['vendor.sucursal.mapping']
        self.Company = env['res.company']

    def resolve_company(self, sucursal):
        """Return (company, warning_message). Company is empty when unmapped."""
        sucursal_name = (sucursal or '').strip()
        if not sucursal_name:
            return self.Company.browse(), 'Missing sheet sucursal value.'

        mapping = self.Mapping.search([('sucursal', '=', sucursal_name)], limit=1)
        if mapping:
            return mapping.company_id, None

        return self.Company.browse(), (
            'Unmapped sucursal "%s". Add a vendor sucursal mapping.' % sucursal_name
        )
