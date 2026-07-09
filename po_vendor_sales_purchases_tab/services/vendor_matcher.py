# -*- coding: utf-8 -*-


class VendorMatcher:
    """Resolve sheet proveedor strings to Odoo partners and classification vendors."""

    def __init__(self, env):
        self.env = env
        self.Partner = env['res.partner']
        self.Mapping = env['vendor.sheet.mapping']
        self.ClassificationVendor = env['product.classification.vendor']

    def resolve_partner(self, sheet_proveedor):
        """Return (partner, warning_message). Partner is empty when unmatched."""
        sheet_name = (sheet_proveedor or '').strip()
        if not sheet_name:
            return self.Partner.browse(), 'Falta el valor de proveedor en la hoja.'

        mapping = self.Mapping.search([('sheet_proveedor', '=', sheet_name)], limit=1)
        if mapping:
            if mapping.partner_id:
                return mapping.partner_id, None
            return self.Partner.browse(), (
                'Proveedor en hoja "%s" pendiente de asignación en Mapeos de proveedor.'
                % sheet_name
            )

        return self.Partner.browse(), (
            'Proveedor sin mapear "%s". Agregue un mapeo manual.' % sheet_name
        )

    def resolve_classification_vendor(self, partner):
        """Return (classification_vendor, warning_message)."""
        if not partner:
            return self.ClassificationVendor.browse(), (
                'No hay contacto para resolver el proveedor de clasificación.'
            )

        mapping = self.Mapping.search([
            ('partner_id', '=', partner.id),
            ('classification_vendor_id', '!=', False),
        ], limit=1)
        if mapping:
            return mapping.classification_vendor_id, None

        return self.ClassificationVendor.browse(), (
            'No hay coincidencia de proveedor de clasificación para el contacto "%s".'
            % partner.name
        )
