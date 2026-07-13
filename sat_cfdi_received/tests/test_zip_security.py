# -*- coding: utf-8 -*-
import io
import zipfile

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.sat_cfdi_received.services.xml_parser import XmlParserError, parse_received_cfdi
from odoo.addons.sat_cfdi_received.services.zip_security import ZipSecurityError, extract_xmls_from_zip


SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Fecha="2026-07-05T10:30:00" Total="100.00" Moneda="MXN">
    <cfdi:Emisor Rfc="ABC010101ABC" Nombre="Test Supplier"/>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            UUID="ZIP-TEST-UUID-0001-0000-000000000001"/>
    </cfdi:Complemento>
</cfdi:Comprobante>
"""


def _build_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


@tagged('post_install', '-at_install', 'sat_cfdi_received')
class TestZipSecurity(TransactionCase):
    def test_extract_valid_xml_zip(self):
        zip_bytes = _build_zip([('cfdi.xml', SAMPLE_XML)])
        xml_list = extract_xmls_from_zip(zip_bytes)
        self.assertEqual(len(xml_list), 1)
        result = parse_received_cfdi(xml_list[0])
        self.assertEqual(result['uuid'], 'ZIP-TEST-UUID-0001-0000-000000000001')

    def test_reject_unsafe_zip_path(self):
        zip_bytes = _build_zip([('../evil.xml', SAMPLE_XML)])
        with self.assertRaises(ZipSecurityError):
            extract_xmls_from_zip(zip_bytes)

    def test_reject_malformed_zip(self):
        with self.assertRaises(ZipSecurityError):
            extract_xmls_from_zip(b'not-a-zip')

    def test_reject_oversized_xml(self):
        huge = b'<?xml version="1.0"?><root>' + (b'x' * (6 * 1024 * 1024)) + b'</root>'
        with self.assertRaises(XmlParserError):
            parse_received_cfdi(huge)

    def test_reject_malformed_xml(self):
        with self.assertRaises(XmlParserError):
            parse_received_cfdi(b'<not-valid-xml')

    def test_zip_ignores_non_xml_entries(self):
        zip_bytes = _build_zip([
            ('readme.txt', b'ignore me'),
            ('cfdi.xml', SAMPLE_XML),
        ])
        xml_list = extract_xmls_from_zip(zip_bytes)
        self.assertEqual(len(xml_list), 1)
