# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

from odoo.addons.sat_cfdi_received.services.xml_parser import parse_received_cfdi


CFDI_33_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/3"
    Fecha="2026-07-05T10:30:00" Total="15432.50" Moneda="MXN">
    <cfdi:Emisor Rfc="ABC010101ABC" Nombre="Proveedor ABC SA de CV"/>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            UUID="A1B2C3D4-E5F6-7890-ABCD-EF1234567890"/>
    </cfdi:Complemento>
</cfdi:Comprobante>
"""

CFDI_40_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Fecha="2026-07-08T14:00:00" Total="8200.00" Moneda="MXN">
    <cfdi:Emisor Rfc="XYZ990101XYZ" Nombre="Suministros XYZ"/>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            UUID="B2C3D4E5-F6A7-8901-BCDE-F12345678901"/>
    </cfdi:Complemento>
</cfdi:Comprobante>
"""


class TestXmlParser(TransactionCase):
    def test_parse_cfdi_33(self):
        result = parse_received_cfdi(CFDI_33_XML)
        self.assertEqual(str(result['invoice_date']), '2026-07-05')
        self.assertEqual(result['supplier_name'], 'Proveedor ABC SA de CV')
        self.assertEqual(result['total'], 15432.50)
        self.assertEqual(result['uuid'], 'A1B2C3D4-E5F6-7890-ABCD-EF1234567890')
        self.assertEqual(result['supplier_rfc'], 'ABC010101ABC')
        self.assertEqual(result['currency'], 'MXN')

    def test_parse_cfdi_40(self):
        result = parse_received_cfdi(CFDI_40_XML)
        self.assertEqual(str(result['invoice_date']), '2026-07-08')
        self.assertEqual(result['supplier_name'], 'Suministros XYZ')
        self.assertEqual(result['total'], 8200.00)
        self.assertEqual(result['uuid'], 'B2C3D4E5-F6A7-8901-BCDE-F12345678901')
