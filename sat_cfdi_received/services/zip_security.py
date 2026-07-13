# -*- coding: utf-8 -*-
"""Safe extraction of XML files from SAT download ZIP packages."""
import io
import zipfile

from odoo import _

MAX_ZIP_ENTRIES = 1000
MAX_ENTRY_SIZE = 10 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


class ZipSecurityError(Exception):
    """Unsafe or malformed ZIP archive."""


def _is_safe_zip_path(name):
    if not name or name.startswith('/') or '..' in name.replace('\\', '/').split('/'):
        return False
    return True


def _entry_uncompressed_size(info):
    return info.file_size or 0


def extract_xmls_from_zip(zip_bytes):
    """Extract XML file contents from a SAT download ZIP with safety limits."""
    if not zip_bytes:
        raise ZipSecurityError(_('Se recibió un paquete ZIP vacío del SAT.'))

    xml_files = []
    total_uncompressed = 0

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ZipSecurityError(_('Paquete ZIP malformado del SAT.')) from exc

    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ZipSecurityError(_(
                'El paquete ZIP excede el número máximo permitido de entradas (%s).'
            ) % MAX_ZIP_ENTRIES)

        for info in entries:
            if info.is_dir():
                continue
            if not _is_safe_zip_path(info.filename):
                raise ZipSecurityError(_('Ruta insegura en el paquete ZIP: %s') % info.filename)
            if not info.filename.lower().endswith('.xml'):
                continue

            uncompressed = _entry_uncompressed_size(info)
            if uncompressed > MAX_ENTRY_SIZE:
                raise ZipSecurityError(_(
                    'La entrada XML excede el tamaño máximo permitido: %s'
                ) % info.filename)

            compressed = info.compress_size or 0
            if compressed and uncompressed / compressed > MAX_COMPRESSION_RATIO:
                raise ZipSecurityError(_(
                    'Relación de compresión sospechosa en la entrada ZIP: %s'
                ) % info.filename)

            total_uncompressed += uncompressed
            if total_uncompressed > MAX_TOTAL_UNCOMPRESSED:
                raise ZipSecurityError(_(
                    'El paquete ZIP excede el tamaño total descomprimido máximo permitido.'
                ))

            xml_files.append(archive.read(info.filename))

    return xml_files
