"""Begrenzter Bildabruf; Verbindung an eine gepruefte oeffentliche IP binden."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit


def abrufen(adresse, typen, maximum=2 * 1024 * 1024, timeout=8):
    if not isinstance(adresse, str) or len(adresse) > 8192 or any(ord(c) < 32 for c in adresse):
        raise ValueError('Ungueltige Bildadresse')
    u = urlsplit(adresse)
    if u.scheme not in ('https', 'http') or not u.hostname or u.username is not None or u.password is not None:
        raise ValueError('Nur oeffentliche HTTP-Bilder ohne Zugangsdaten')
    port = 443 if u.scheme == 'https' else 80
    if u.port not in (None, port):
        raise ValueError('Unzulaessiger Port')
    host = u.hostname.encode('idna').decode('ascii')
    adressen = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not adressen:
        raise ValueError('Keine Bildadresse gefunden')
    for _, _, _, _, ziel in adressen:
        ip = ipaddress.ip_address(ziel[0])
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or (ip.version == 6 and ip.ipv4_mapped is not None):
            raise ValueError('Lokale und besondere Netze sind gesperrt')
    familie, typ, protokoll, _, ziel = adressen[0]
    verbindung = http.client.HTTPConnection(host, port, timeout=timeout)
    sock = socket.socket(familie, typ, protokoll)
    try:
        sock.settimeout(timeout)
        sock.connect(ziel)  # Keine zweite Namensaufloesung, kein Proxy.
        if u.scheme == 'https':
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        verbindung.sock = sock
        pfad = (u.path or '/') + ('?' + u.query if u.query else '')
        verbindung.request('GET', pfad, headers={'User-Agent': 'JACK/1.0', 'Accept': 'image/*', 'Connection': 'close'})
        antwort = verbindung.getresponse()
        bildtyp = (antwort.getheader('Content-Type') or '').split(';')[0].strip().lower()
        if antwort.status != 200 or bildtyp not in typen:
            raise ValueError('Kein Bild; Weiterleitungen werden nicht verfolgt')
        laenge = antwort.getheader('Content-Length')
        if laenge is not None and (int(laenge) < 0 or int(laenge) > maximum):
            raise ValueError('Bild zu gross')
        daten = antwort.read(maximum + 1)
        if not daten or len(daten) > maximum:
            raise ValueError('Bild leer oder zu gross')
        return bildtyp, daten
    finally:
        verbindung.close()
        sock.close()
