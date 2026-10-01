"""Isolierter Docling-Aufruf: Bytes hinein, Text/Tabellen hinaus; keine URLs."""
import base64
from io import BytesIO
import json
import sys
import socket
import zipfile
import warnings
from PIL import Image
from docling.backend.html_backend import HTMLDocumentBackend
from docling.backend.msword_backend import MsWordDocumentBackend
from docling.datamodel.document import InputDocument
from docling.datamodel.base_models import InputFormat
from docling.datamodel.backend_options import HTMLBackendOptions, MsWordBackendOptions


def main():
    request = json.loads(sys.stdin.buffer.read(7_000_001))
    if set(request) != {'name', 'base64'}:
        raise ValueError('Ungültiger Auftrag')
    name = request['name']
    if not isinstance(name, str) or '/' in name or '\\' in name:
        raise ValueError('Ungültiger Name')
    raw = base64.b64decode(request['base64'], validate=True)
    if not 1 <= len(raw) <= 5_000_000:
        raise ValueError('Dokumentgröße unzulässig')
    Image.MAX_IMAGE_PIXELS = 8_000_000
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    if name.lower().endswith('.docx'):
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            files = archive.infolist()
            if len(files) > 2000 or sum(f.file_size for f in files) > 30_000_000:
                raise ValueError('Word-Dokument ist ausgepackt zu groß')
            for item in files:
                if '..' in item.filename.split('/') or item.filename.startswith('/') or item.flag_bits & 1:
                    raise ValueError('Ungültiger Archivinhalt')
                if any(x in item.filename.lower() for x in ('vbaproject', '/embeddings/')):
                    raise ValueError('Aktive eingebettete Inhalte nicht unterstützt')
                if item.filename.startswith('word/media/') and not item.is_dir():
                    if item.file_size > 2_000_000:
                        raise ValueError('Eingebettetes Bild zu groß')
                    with Image.open(BytesIO(archive.read(item))) as im:
                        if im.width * im.height > 8_000_000:
                            raise ValueError('Eingebettetes Bild zu groß')
        fmt, backend = InputFormat.DOCX, MsWordDocumentBackend
        options = MsWordBackendOptions(enable_remote_fetch=False, enable_local_fetch=False, render_chart_images=False)
    elif name.lower().endswith(('.html', '.htm')):
        fmt, backend = InputFormat.HTML, HTMLDocumentBackend
        options = HTMLBackendOptions(enable_remote_fetch=False, enable_local_fetch=False, fetch_images=False,
                                     render_page=False, max_image_data_base64_bytes=1_000_000)
    else:
        raise ValueError('Nur HTML und DOCX unterstützt')
    def deny(*args, **kwargs):
        raise ValueError('Netzwerkzugriff ist für die Dokumentumwandlung ausgeschaltet')
    socket.create_connection = deny
    socket.socket.connect = deny
    document = InputDocument(BytesIO(raw), format=fmt, backend=backend, backend_options=options, filename=name)
    if not document.valid:
        raise ValueError('Dokument ist nicht lesbar')
    try:
        converted = document._backend.convert()
        markdown = converted.export_to_markdown(escape_html=True)
        if not markdown.strip() or len(markdown.encode()) > 500_000:
            raise ValueError('Kein begrenztes Text-Ergebnis verfügbar')
        result = {'version': 'docling-slim 2.127.0', 'markdown': markdown,
                  'tabellen': [t.data.model_dump(mode='json') for t in converted.tables],
                  'textbloecke': len(converted.texts), 'netzwerk': False, 'modellaufrufe': 0}
        output = json.dumps(result, ensure_ascii=False)
        if len(output.encode()) > 1_000_000:
            raise ValueError('Struktur-Ergebnis zu groß')
        print(output)
    finally:
        document._backend.unload()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Dokumentumwandlung fehlgeschlagen; Original unverändert.', file=sys.stderr)
        sys.exit(2)
