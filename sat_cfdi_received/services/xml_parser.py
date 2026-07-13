# -*- coding: utf-8 -*-
"""Extract key fields from received CFDI XML (versions 3.3 and 4.0)."""
from datetime import datetime

from lxml import etree

from odoo import _

CFDI_NAMESPACES = (
    'http://www.sat.gob.mx/cfd/4',
    'http://www.sat.gob.mx/cfd/3',
)
TFD_NAMESPACE = 'http://www.sat.gob.mx/TimbreFiscalDigital'
MAX_XML_BYTES = 5 * 1024 * 1024

SAFE_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    load_dtd=False,
    no_network=True,
    huge_tree=False,
)


class XmlParserError(Exception):
    """CFDI XML parsing failed."""


def _local_name(tag):
    if '}' in tag:
        return tag.rsplit('}', 1)[1]
    return tag


def _find_comprobante(root):
    if _local_name(root.tag) == 'Comprobante':
        return root
    for ns in CFDI_NAMESPACES:
        comprobante = root.find('{%s}Comprobante' % ns)
        if comprobante is not None:
            return comprobante
    comprobante = root.find('.//{*}Comprobante')
    return comprobante


def _find_emisor(comprobante):
    for ns in CFDI_NAMESPACES:
        emisor = comprobante.find('{%s}Emisor' % ns)
        if emisor is not None:
            return emisor
    return comprobante.find('.//{*}Emisor')


def _find_timbre(comprobante):
    complemento = comprobante.find('.//{*}Complemento')
    if complemento is None:
        return None
    timbre = complemento.find('{%s}TimbreFiscalDigital' % TFD_NAMESPACE)
    if timbre is None:
        timbre = complemento.find('.//{*}TimbreFiscalDigital')
    return timbre


def _parse_invoice_date(fecha_str):
    if not fecha_str:
        return False
    normalized = fecha_str.strip()
    if 'T' in normalized:
        normalized = normalized.split('T')[0]
    try:
        return datetime.strptime(normalized, '%Y-%m-%d').date()
    except ValueError:
        return False


def parse_received_cfdi(xml_bytes):
    """Parse a received CFDI XML and return extracted fields as a dict."""
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode('utf-8')

    if not xml_bytes:
        raise XmlParserError(_('Entrada XML vacía.'))
    if len(xml_bytes) > MAX_XML_BYTES:
        raise XmlParserError(_('El XML excede el tamaño máximo permitido (%s bytes).') % MAX_XML_BYTES)

    try:
        root = etree.fromstring(xml_bytes, parser=SAFE_XML_PARSER)
    except etree.XMLSyntaxError as exc:
        raise XmlParserError(_('XML inválido.')) from exc

    comprobante = _find_comprobante(root)
    if comprobante is None:
        raise XmlParserError(_('No se encontró el elemento Comprobante.'))

    emisor = _find_emisor(comprobante)
    timbre = _find_timbre(comprobante)

    uuid = timbre.get('UUID') if timbre is not None else None
    if not uuid:
        raise XmlParserError(_('No se encontró el UUID de TimbreFiscalDigital.'))

    invoice_date = _parse_invoice_date(comprobante.get('Fecha'))
    total_str = comprobante.get('Total') or '0'
    try:
        total = float(total_str)
    except (TypeError, ValueError):
        total = 0.0

    return {
        'invoice_date': invoice_date,
        'supplier_name': (emisor.get('Nombre') if emisor is not None else '') or '',
        'total': total,
        'uuid': uuid.upper(),
        'supplier_rfc': (emisor.get('Rfc') if emisor is not None else '') or '',
        'currency': comprobante.get('Moneda') or '',
    }
