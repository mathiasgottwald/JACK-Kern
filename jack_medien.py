"""Lokale technische Videopruefung. Kein Upload, keine Erzeugung, kein Modell.

Metadaten UND ein vollstaendiger Dekodierlauf werden geprueft. Aussagegrenze:
Tonspur vorhanden ist nicht gleich guter Ton; Kreativitaet, Fakten, Rechte
und eingebrannte Untertitel brauchen weiterhin eine gesonderte Abnahme.
"""
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import uuid

FFPROBE = Path('/opt/homebrew/bin/ffprobe')
FFMPEG = Path('/opt/homebrew/bin/ffmpeg')
MAX_BYTES = 2 * 1024 * 1024 * 1024
SUFFIXES = {'.mp4', '.mov', '.mkv', '.webm', '.m4v'}


def quelle(root, raw):
    vault = Path(root).resolve().parent.parent
    if not isinstance(raw, str) or not raw or len(raw)>1500 or any(ord(c)<32 for c in raw):
        raise ValueError('Ein lokaler Videopfad ist erforderlich')
    p = Path(raw)
    if p.is_absolute() or '..' in p.parts or ':' in raw or '\\' in raw or p.suffix.lower() not in SUFFIXES:
        raise ValueError('Lokale MP4-, MOV-, MKV-, WEBM- oder M4V-Datei relativ zur Holding erforderlich')
    target = vault/p
    if any(x.is_symlink() for x in [target,*target.parents] if x!=vault and vault in x.parents):
        raise ValueError('Videopfad darf keinen Verweis enthalten')
    target = target.resolve()
    if vault not in target.parents or not target.is_file() or not 0<target.stat().st_size<=MAX_BYTES:
        raise ValueError('Video fehlt, ist leer oder groesser als 2 GiB')
    forbidden={'.git','.claude','.codex','secrets','node_modules'}
    if any(p.casefold() in forbidden or p.casefold().startswith('.env') or p.casefold().endswith('.nosync') for p in target.relative_to(vault).parts):
        raise ValueError('Geschuetzter Pfad ist kein Medienauftrag')
    return target


def fingerprint(path):
    before=path.stat();h=hashlib.sha256();total=0
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            total+=len(chunk)
            if total>MAX_BYTES:raise ValueError('Video ueberschreitet die Groessengrenze')
            h.update(chunk)
    after=path.stat()
    sig=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    if sig(before)!=sig(after):raise ValueError('Video hat sich waehrend der Pruefung veraendert')
    return {'sha256':h.hexdigest(),'bytes':total}


def _zahl(value, name, minimum, maximum):
    if isinstance(value,bool):raise ValueError(name+' ist keine gueltige Zahl')
    try:value=float(value)
    except (TypeError,ValueError):raise ValueError(name+' ist keine gueltige Zahl')
    if not math.isfinite(value) or not minimum<=value<=maximum:raise ValueError(name+' ausserhalb des erlaubten Bereichs')
    return value


def pruefen(root, pfad, min_breite=1, min_hoehe=1, max_dauer_sekunden=None, ton_noetig=True):
    root=Path(root).resolve();video=quelle(root,pfad)
    if not FFPROBE.is_file() or not FFMPEG.is_file():raise ValueError('Die lokale Medienpruefung ist nicht installiert')
    breite=int(_zahl(min_breite,'Mindestbreite',1,8192));hoehe=int(_zahl(min_hoehe,'Mindesthoehe',1,8192))
    maxdauer=_zahl(max_dauer_sekunden,'Maximale Dauer',0.1,7200) if max_dauer_sekunden is not None else None
    if not isinstance(ton_noetig,bool):raise ValueError('Tonvorgabe muss ja oder nein sein')
    initial=fingerprint(video)
    env={'PATH':'/usr/bin:/bin','LANG':'C'}
    args=[str(FFPROBE),'-v','error','-max_alloc','268435456','-protocol_whitelist','file,pipe',
          '-show_entries','format=duration,format_name:stream=codec_type,codec_name,width,height:stream_side_data=rotation',
          '-of','json',str(video)]
    try:
        response=subprocess.run(args,capture_output=True,text=True,timeout=20,env=env)
    except subprocess.TimeoutExpired:raise ValueError('Metadatenpruefung nach 20 Sekunden beendet')
    if response.returncode or len(response.stdout)>1_000_000:raise ValueError('Videoformat nicht gueltig lesbar')
    try:data=json.loads(response.stdout)
    except ValueError:raise ValueError('Keine gueltigen Videometadaten')
    if not isinstance(data,dict) or not isinstance(data.get('streams'),list) or any(not isinstance(s,dict) for s in data['streams']):
        raise ValueError('Ungueltige Videometadaten')
    streams=data['streams']
    picture=next((s for s in streams if s.get('codec_type')=='video'),None)
    if not picture:raise ValueError('Datei hat keine Videospur')
    duration=_zahl(data.get('format',{}).get('duration'),'Videodauer',0.001,7200)
    width=int(picture.get('width') or 0);height=int(picture.get('height') or 0)
    rotation=next((float(s['rotation']) for s in picture.get('side_data_list',[]) if 'rotation' in s),0)
    if abs(rotation)%180==90:width,height=height,width
    audio=any(s.get('codec_type')=='audio' for s in streams)
    checks=[{'kennung':'abmessungen','bestanden':width>=breite and height>=hoehe,'wert':f'{width} × {height}'},
            {'kennung':'dauer','bestanden':maxdauer is None or duration<=maxdauer,'wert':round(duration,3)},
            {'kennung':'tonspur','bestanden':audio or not ton_noetig,'wert':audio}]
    decode=[str(FFMPEG),'-nostdin','-v','error','-xerror','-max_alloc','268435456','-threads','2',
            '-protocol_whitelist','file,pipe','-i',str(video),'-map','0:v:0','-map','0:a?',
            '-f','null','-']
    try:
        run=subprocess.run(decode,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=90,env=env)
        decoded=run.returncode==0
        decode_note='Vollstaendiger Dekodierlauf bestanden' if decoded else 'Dekodierfehler; kein bestandener Export'
    except subprocess.TimeoutExpired:
        decoded=False;decode_note='Nach 90 Sekunden beendet; vollstaendige Dekodierung nicht belegt'
    checks.append({'kennung':'dekodierung','bestanden':decoded,'wert':decode_note})
    if fingerprint(video)!=initial:raise ValueError('Video nach Pruefbeginn veraendert; keine Abnahme')
    record={'schema':1,'art':'jack_medienpruefung','zeit':dt.datetime.now().astimezone().isoformat(),
            'quelle':{'pfad':str(video.relative_to(root.parent.parent)),**initial},
            'vorgaben':{'min_breite':breite,'min_hoehe':hoehe,'max_dauer_sekunden':maxdauer,'ton_noetig':ton_noetig},
            'pruefungen':checks,'technik_bestanden':all(p['bestanden'] for p in checks),
            'kreative_abnahme':'offen','hinweis':'Keine Bewertung von Aussage, Gestaltung, Tonqualitaet, Untertiteln oder Nutzungsrechten.',
            'werkzeuge':[str(FFPROBE),str(FFMPEG)],'modellaufrufe':0}
    folder=root/'betrieb/medienpruefungen';folder.mkdir(parents=True,exist_ok=True)
    dest=folder/(dt.datetime.now().strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:12]+'.json')
    with dest.open('x',encoding='utf-8') as f:
        f.write(json.dumps(record,ensure_ascii=False,indent=2)+'\n');f.flush();os.fsync(f.fileno())
    return {**record,'nachweis':str(dest.relative_to(root.parent.parent))}


CLEANUP_KATEGORIEN = ('personen', 'kennzeichen', 'adressen', 'fremde_marken')
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}


def cleanup_pruefliste(befunde):
    """Erzwingt die Pflichtpruefung aus Auftrag 9.1 (Schritt in 7.1/8.1), technisch,
    nicht nur als Anweisung: fehlt eine der vier Kategorien oder eine Fundstelle
    bei einem positiven Fund, wird abgelehnt und nichts geht in die Bearbeitung."""
    if not isinstance(befunde, dict):
        raise ValueError('Cleanup-Pruefliste fehlt')
    kategorien = {}
    for name in CLEANUP_KATEGORIEN:
        eintrag = befunde.get(name)
        if not isinstance(eintrag, dict) or not isinstance(eintrag.get('gefunden'), bool):
            raise ValueError(f'Cleanup-Pruefliste: Kategorie "{name}" fehlt oder ist unvollstaendig')
        fundstellen = eintrag.get('fundstellen', [])
        if (not isinstance(fundstellen, list) or len(fundstellen) > 20
                or any(not isinstance(f, str) or not f.strip() or len(f) > 200 for f in fundstellen)):
            raise ValueError(f'Cleanup-Pruefliste: Fundstellen zu "{name}" sind ungueltig')
        if eintrag['gefunden'] and not fundstellen:
            raise ValueError(f'Cleanup-Pruefliste: "{name}" als gefunden markiert, aber keine Fundstelle angegeben')
        kategorien[name] = {'gefunden': eintrag['gefunden'], 'fundstellen': fundstellen}
    return {'schema': 1, 'art': 'jack_cleanup_pruefliste',
            'zeit': dt.datetime.now().astimezone().isoformat(),
            'kategorien': kategorien, 'freigabe_patron': 'offen',
            'hinweis': 'Nur die Pflichtpruefung aus 9.1; ersetzt keine Rechtspruefung und keine Drehgenehmigung.'}


def _ersatzflaeche_pruefen(root, raw, breite, hoehe):
    vault = root.parent.parent
    if not isinstance(raw, str) or not raw or len(raw) > 1500 or any(ord(c) < 32 for c in raw):
        raise ValueError('Ein lokaler Ersatzflaechen-Pfad ist erforderlich')
    p = Path(raw)
    erlaubt = SUFFIXES | IMAGE_SUFFIXES
    if p.is_absolute() or '..' in p.parts or ':' in raw or '\\' in raw or p.suffix.lower() not in erlaubt:
        raise ValueError('Ersatzflaeche muss eine lokale Bild- oder Videodatei relativ zur Holding sein')
    target = vault / p
    if any(x.is_symlink() for x in [target, *target.parents] if x != vault and vault in x.parents):
        raise ValueError('Ersatzflaechenpfad darf keinen Verweis enthalten')
    target = target.resolve()
    if vault not in target.parents or not target.is_file() or not 0 < target.stat().st_size <= MAX_BYTES:
        raise ValueError('Ersatzflaeche fehlt, ist leer oder zu gross')
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}
    args = [str(FFPROBE), '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'json', str(target)]
    try:
        response = subprocess.run(args, capture_output=True, text=True, timeout=20, env=env)
    except subprocess.TimeoutExpired:
        raise ValueError('Pruefung der Ersatzflaeche nach 20 Sekunden beendet')
    if response.returncode or len(response.stdout) > 1_000_000:
        raise ValueError('Ersatzflaeche ist nicht als Bild oder Video lesbar')
    try:
        info = json.loads(response.stdout)
        stream = info['streams'][0]
        breite_ist, hoehe_ist = int(stream['width']), int(stream['height'])
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError('Abmessungen der Ersatzflaeche nicht lesbar')
    if (breite_ist, hoehe_ist) != (breite, hoehe):
        raise ValueError(f'Ersatzflaeche muss exakt {breite}x{hoehe} Pixel gross sein, ist aber {breite_ist}x{hoehe_ist}')
    return target


def cleanup_maske_anwenden(root, quellpfad, ersatzflaeche_pfad, x, y, breite, hoehe, zielpfad):
    """Setzt eine bereitgestellte Ersatzflaeche NUR in einem exakt begrenzten
    Rechteck ueber das Original (Auftrag 9.1). Technische Begrenzung, nicht nur
    Anweisung: ffmpeg 'overlay' zeichnet ausschliesslich innerhalb des Rechtecks;
    die Ersatzflaeche muss exakt dessen Groesse haben, sonst wird abgelehnt.

    GRENZE (im Code UND hier dokumentiert): Dies ist Schnitt/Maskierung eines
    vom Aufrufer gelieferten Ersatzbilds/-clips - KEIN Beweis oder Verfahren
    zur Rekonstruktion verdeckter Bildbereiche."""
    root = Path(root).resolve()
    quelle_video = quelle(root, quellpfad)
    if not FFPROBE.is_file() or not FFMPEG.is_file():
        raise ValueError('Die lokale Medienbearbeitung ist nicht installiert')
    x = int(_zahl(x, 'x-Position', 0, 7680))
    y = int(_zahl(y, 'y-Position', 0, 7680))
    breite = int(_zahl(breite, 'Maskenbreite', 1, 7680))
    hoehe = int(_zahl(hoehe, 'Maskenhoehe', 1, 7680))
    ersatz = _ersatzflaeche_pruefen(root, ersatzflaeche_pfad, breite, hoehe)
    if not isinstance(zielpfad, str) or not zielpfad or len(zielpfad) > 1500:
        raise ValueError('Zielpfad fehlt')
    ziel_p = Path(zielpfad)
    if ziel_p.is_absolute() or '..' in ziel_p.parts or ':' in zielpfad or '\\' in zielpfad or ziel_p.suffix.lower() not in SUFFIXES:
        raise ValueError('Zielpfad muss eine lokale Videodatei relativ zur Holding sein')
    ziel = root.parent.parent / ziel_p
    if ziel.parent.resolve() != quelle_video.parent or ziel.is_symlink() or ziel.exists():
        raise ValueError('Ergebnis muss neu und im selben Medienordner wie das Original liegen')
    initial = fingerprint(quelle_video)
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}
    ist_bild = ersatz.suffix.lower() in IMAGE_SUFFIXES
    eingabe_ersatz = (['-loop', '1'] if ist_bild else []) + ['-i', str(ersatz)]
    filter_graph = '[0:v][1:v]overlay=%d:%d[out]' % (x, y)
    args = [str(FFMPEG), '-nostdin', '-v', 'error', '-xerror', '-max_alloc', '268435456',
            '-protocol_whitelist', 'file,pipe', '-i', str(quelle_video), *eingabe_ersatz,
            '-filter_complex', filter_graph, '-map', '[out]', '-map', '0:a?',
            '-c:a', 'copy', '-shortest', str(ziel)]
    try:
        run = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             text=True, timeout=90, env=env)
    except subprocess.TimeoutExpired:
        raise ValueError('Maskierung nach 90 Sekunden beendet')
    if run.returncode != 0 or not ziel.is_file():
        raise ValueError('Maskierung fehlgeschlagen: ' + run.stderr[-1500:])
    if fingerprint(quelle_video) != initial:
        raise ValueError('Original hat sich waehrend der Bearbeitung veraendert; Ergebnis verworfen')
    return {'schema': 1, 'art': 'jack_cleanup_maskierung',
            'zeit': dt.datetime.now().astimezone().isoformat(),
            'original': str(quelle_video.relative_to(root.parent.parent)),
            'ergebnis': str(ziel.relative_to(root.parent.parent)),
            'rechteck': {'x': x, 'y': y, 'breite': breite, 'hoehe': hoehe},
            'grenze': 'Nur Schnitt/Maskierung im angegebenen Rechteck. Kein Beweis einer '
                      'Rekonstruktion verdeckter Bildbereiche.'}


def _logo_pruefen(root, raw):
    """Logo fuer die CI-Nachbearbeitung (A6c): lokale PNG/WEBP relativ zur Holding, MIT Alphakanal.
    Ein Logo ohne Transparenz wuerde als Kasten im Bild landen; SVG kann ffmpeg hier nicht
    zeichnen und wird abgelehnt (vorher als PNG exportieren, nie vom Modell erzeugen lassen)."""
    vault = root.parent.parent
    if not isinstance(raw, str) or not raw or len(raw) > 1500 or any(ord(c) < 32 for c in raw):
        raise ValueError('Ein lokaler Logo-Pfad ist erforderlich')
    p = Path(raw)
    if p.is_absolute() or '..' in p.parts or ':' in raw or '\\' in raw or p.suffix.lower() not in {'.png', '.webp'}:
        raise ValueError('Logo muss eine lokale PNG- oder WEBP-Datei relativ zur Holding sein (SVG nicht unterstuetzt)')
    target = vault / p
    if any(x.is_symlink() for x in [target, *target.parents] if x != vault and vault in x.parents):
        raise ValueError('Logopfad darf keinen Verweis enthalten')
    target = target.resolve()
    if vault not in target.parents or not target.is_file() or not 0 < target.stat().st_size <= 200 * 1024 * 1024:
        raise ValueError('Logo fehlt, ist leer oder zu gross')
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}
    args = [str(FFPROBE), '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,pix_fmt', '-of', 'json', str(target)]
    try:
        response = subprocess.run(args, capture_output=True, text=True, timeout=20, env=env)
        stream = json.loads(response.stdout)['streams'][0]
        breite, hoehe, pix = int(stream['width']), int(stream['height']), str(stream['pix_fmt'])
    except (subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError):
        raise ValueError('Logo ist nicht als Bild lesbar')
    if response.returncode or not (pix.startswith(('rgba', 'bgra', 'argb', 'abgr', 'ya', 'yuva', 'gbrap')) or pix == 'pal8'):
        raise ValueError('Logo hat keinen Alphakanal (Transparenz): ' + pix)
    return target, breite, hoehe


LOGO_DARSTELLUNG_STANDARD = {
    'gestapelt_min_hoehe_zu_breite': 0.4, 'quadratisch_von': 0.9, 'quadratisch_bis': 1.1,
    'hoehe_anteil': {'gestapelt': 0.14, 'quer': 0.09, 'quadratisch': 0.08},
    'max_breite_anteil': 0.30, 'rand_anteil': 0.03, 'deckkraft': 0.95,
    'schatten': {'aktiv': True, 'unschaerfe_anteil': 0.02, 'deckkraft': 0.55},
    'quer_max_breite': 0.40, 'quer_min_hoehe': 0.05,
    'helligkeit_schwelle': 0.55, 'helligkeit_proben': 5}   # F-27: Fassung nach Helligkeit der Logo-Ecke


def _logo_darstellung(root):
    """Parameter aus betrieb/videoproduktion.json -> ci_pflicht.logo_darstellung (je Aufruf neu gelesen).
    Fehlt der Block oder ist er unlesbar, gelten die Standardwerte (Strang A-3)."""
    d = json.loads(json.dumps(LOGO_DARSTELLUNG_STANDARD))
    try:
        cfg = json.loads((Path(root) / 'betrieb' / 'videoproduktion.json').read_text(encoding='utf-8'))
        ist = cfg['ci_pflicht']['logo_darstellung']
    except (OSError, ValueError, KeyError, TypeError):
        return d
    if isinstance(ist, dict):
        for k, v in ist.items():
            if k in d and isinstance(d[k], dict) and isinstance(v, dict):
                d[k].update(v)
            elif k in d:
                d[k] = v
    return d


def _logo_zuschnitt(logo):
    """Sichtbarer Bereich des Logos (ohne transparenten Leerrand) als (b, h, x, y); None = ganzes Bild."""
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}
    try:
        r = subprocess.run([str(FFMPEG), '-nostdin', '-loop', '1', '-t', '0.4', '-i', str(logo),
                            '-vf', 'alphaextract,format=gray,cropdetect=limit=5:round=2:reset=1', '-f', 'null', '-'],
                           capture_output=True, text=True, timeout=30, env=env)
        treffer = [ln for ln in r.stderr.splitlines() if 'crop=' in ln]
        b, h, x, y = [int(v) for v in treffer[-1].rsplit('crop=', 1)[1].split()[0].split(':')]
        return (b, h, x, y) if b > 0 and h > 0 else None
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def _ecke_helligkeit(video, box_b, box_h, rand, dauer, proben):
    """F-27: mittlere Helligkeit (0..1) der Flaeche unten rechts, die das Logo einnehmen wird, gemittelt ueber
    'proben' Standbilder gleichmaessig ueber die Laufzeit. Nur lokal (ffmpeg), nichts wird geschrieben."""
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}
    werte = []
    for i in range(proben):
        t = max(0.0, dauer * (i + 0.5) / proben)
        r = subprocess.run([str(FFMPEG), '-nostdin', '-v', 'error', '-ss', '%.3f' % t, '-i', str(video),
                            '-frames:v', '1', '-vf', 'crop=%d:%d:iw-%d-%d:ih-%d-%d,format=gray,scale=1:1:flags=area'
                            % (box_b, box_h, box_b, rand, box_h, rand), '-f', 'rawvideo', '-'],
                           capture_output=True, timeout=30, env=env)
        if r.returncode == 0 and len(r.stdout) >= 1:
            werte.append(r.stdout[0] / 255.0)
    if not werte:
        raise ValueError('Helligkeit der Logo-Ecke nicht messbar')
    return round(sum(werte) / len(werte), 4), [round(w, 4) for w in werte]


def logo_einblenden(root, quellpfad, logo_pfad, zielpfad, hoehe_anteil=None, rand_anteil=None,
                    deckkraft=None, nur_letzte_sekunden=None, max_breite_anteil=None, fassungen=None):
    """CI-Nachbearbeitung (A6c): das ECHTE Markenlogo unten rechts ins Video setzen.
    Das Logo wird NIE vom Erzeugungsmodell gerendert, nur hier eingefuegt.

    Alle Darstellungsparameter stehen in betrieb/videoproduktion.json -> ci_pflicht.logo_darstellung (A-3):
      Form wird am zugeschnittenen Logo (ohne transparenten Leerrand) bestimmt:
      quadratisch (Hoehe/Breite 0,9-1,1) 8 %, gestapelt (Hoehe/Breite >= 0,4) 14 %, quer 9 % der Videohoehe;
      nie breiter als max_breite_anteil (30 %) der Videobreite. Rand 3 % der Videohoehe (rechts UND unten),
      Deckkraft 95 %, dahinter weicher dunkler Schatten (Unschaerfe 2 % der Videohoehe, Deckkraft 40 %),
      damit die Marke auf hellem und dunklem Grund lesbar bleibt.
    Ausdruecklich uebergebene Parameter (hoehe_anteil, rand_anteil, deckkraft, max_breite_anteil) haben Vorrang.
    fassungen (F-27): {'heller_grund': <Logo fuer hellen Grund>, 'dunkler_grund': <Logo fuer dunklen Grund>}. Dann wird
      die Helligkeit der Logo-Ecke gemessen (helligkeit_proben Standbilder) und ueber helligkeit_schwelle die Fassung
      fuer hellen, sonst die fuer dunklen Grund gesetzt. Fehlt die noetige Fassung, bleibt logo_pfad. Wahl und Messwert
      stehen im Beleg (.logo.json).
    nur_letzte_sekunden: None = Logo im ganzen Video; Zahl (z. B. 1.5) = Logo blendet erst in den
      letzten n Sekunden ein (0,3 s Einblendung) und bleibt bis zum Ende.
    Das Original wird nur gelesen; das Ergebnis muss neu sein und im selben Ordner liegen."""
    root = Path(root).resolve()
    quelle_video = quelle(root, quellpfad)
    if not FFPROBE.is_file() or not FFMPEG.is_file():
        raise ValueError('Die lokale Medienbearbeitung ist nicht installiert')
    cfg = _logo_darstellung(root)
    if hoehe_anteil is not None:
        hoehe_anteil = _zahl(hoehe_anteil, 'Logohoehe-Anteil', 0.01, 0.5)
    breite_explizit = max_breite_anteil
    max_breite_anteil = _zahl(cfg['max_breite_anteil'] if max_breite_anteil is None else max_breite_anteil,
                              'Maximalbreite-Anteil', 0.05, 1.0)
    rand_anteil = _zahl(cfg['rand_anteil'] if rand_anteil is None else rand_anteil, 'Rand-Anteil', 0.0, 0.25)
    deckkraft = _zahl(cfg['deckkraft'] if deckkraft is None else deckkraft, 'Deckkraft', 0.05, 1.0)
    schatten = cfg['schatten']
    schatten_an = bool(schatten.get('aktiv'))
    schatten_unsch = _zahl(schatten.get('unschaerfe_anteil'), 'Schatten-Unschaerfe', 0.0, 0.1)
    schatten_deck = _zahl(schatten.get('deckkraft'), 'Schatten-Deckkraft', 0.0, 1.0)
    if nur_letzte_sekunden is not None:
        nur_letzte_sekunden = _zahl(nur_letzte_sekunden, 'Endeinblendung in Sekunden', 0.3, 60)
    logo, _lb, _lh = _logo_pruefen(root, logo_pfad)
    zuschnitt = _logo_zuschnitt(logo) or (_lb, _lh, 0, 0)
    zb, zh = zuschnitt[0], zuschnitt[1]
    verhaeltnis = zh / float(zb)
    if _zahl(cfg['quadratisch_von'], 'Quadrat-von', 0.5, 2.0) <= verhaeltnis <= _zahl(cfg['quadratisch_bis'], 'Quadrat-bis', 0.5, 2.0):
        form = 'quadratisch'
    elif verhaeltnis >= _zahl(cfg['gestapelt_min_hoehe_zu_breite'], 'Stapelgrenze', 0.1, 2.0):
        form = 'gestapelt'
    else:
        form = 'quer'
    quer = form == 'quer'
    if hoehe_anteil is None:
        hoehe_anteil = _zahl(cfg['hoehe_anteil'][form], 'Logohoehe-Anteil', 0.01, 0.5)
    if not isinstance(zielpfad, str) or not zielpfad or len(zielpfad) > 1500:
        raise ValueError('Zielpfad fehlt')
    ziel_p = Path(zielpfad)
    if ziel_p.is_absolute() or '..' in ziel_p.parts or ':' in zielpfad or '\\' in zielpfad or ziel_p.suffix.lower() not in SUFFIXES:
        raise ValueError('Zielpfad muss eine lokale Videodatei relativ zur Holding sein')
    ziel = root.parent.parent / ziel_p
    if ziel.parent.resolve() != quelle_video.parent or ziel.is_symlink() or ziel.exists():
        raise ValueError('Ergebnis muss neu und im selben Medienordner wie das Original liegen')
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}
    try:
        info = subprocess.run([str(FFPROBE), '-v', 'error', '-select_streams', 'v:0',
                               '-show_entries', 'stream=width,height,r_frame_rate:format=duration', '-of', 'json',
                               str(quelle_video)], capture_output=True, text=True, timeout=20, env=env)
        daten = json.loads(info.stdout)
        vb, vh = int(daten['streams'][0]['width']), int(daten['streams'][0]['height'])
        zaehler, nenner = daten['streams'][0]['r_frame_rate'].split('/')
        fps = float(zaehler) / float(nenner)
        dauer = float(daten['format']['duration'])
    except (subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
        raise ValueError('Abmessungen oder Dauer des Videos nicht lesbar')
    logo_h = max(2, int(round(vh * hoehe_anteil / 2.0)) * 2)
    if quer and breite_explizit is None:
        max_breite_anteil = _zahl(cfg['quer_max_breite'], 'Quer-Maximalbreite', 0.05, 1.0)   # A-4
    if logo_h * zb / zh > vb * max_breite_anteil:
        logo_h = max(2, int(vb * max_breite_anteil * zh / zb / 2.0) * 2)
    quer_min_px = int(round(vh * _zahl(cfg['quer_min_hoehe'], 'Quer-Mindesthoehe', 0.0, 0.5)))
    quer_min_erreicht = (not quer) or logo_h >= quer_min_px
    rand = int(round(vh * rand_anteil))
    fassung = None
    if fassungen:
        schwelle = _zahl(cfg.get('helligkeit_schwelle', 0.55), 'Helligkeitsschwelle', 0.0, 1.0)
        proben = int(_zahl(cfg.get('helligkeit_proben', 5), 'Helligkeitsproben', 1, 20))
        box_b = max(2, min(vb - rand, int(round(logo_h * zb / float(zh)))))
        mittel, einzel = _ecke_helligkeit(quelle_video, box_b, min(vh - rand, logo_h), rand, dauer, proben)
        seite = 'heller_grund' if mittel > schwelle else 'dunkler_grund'
        gewaehlt = fassungen.get(seite)
        fassung = {'gemessen': True, 'helligkeit_ecke': mittel, 'einzelwerte': einzel, 'schwelle': schwelle,
                   'proben': proben, 'ecke_px': [box_b, logo_h], 'seite': seite,
                   'gewaehlt': seite if gewaehlt else 'standard (Fassung %s fehlt)' % seite}
        if gewaehlt and gewaehlt != logo_pfad:
            neu, _nb, _nh = _logo_pruefen(root, gewaehlt)
            nz = _logo_zuschnitt(neu) or (_nb, _nh, 0, 0)
            # gleiche Hoehe wie berechnet; Breite folgt dem Seitenverhaeltnis der gewaehlten Fassung, Maximalbreite bleibt
            if logo_h * nz[0] / float(nz[1]) > vb * max_breite_anteil:
                logo_h = max(2, int(vb * max_breite_anteil * nz[1] / nz[0] / 2.0) * 2)
            logo, zuschnitt, zb, zh = neu, nz, nz[0], nz[1]
    sigma = max(0.1, vh * schatten_unsch / 2.0)          # Unschaerfe-Radius = 2 sigma
    pad = int(math.ceil(sigma * 3)) if schatten_an else 0
    kette = '[1:v]crop=%d:%d:%d:%d,scale=-2:%d,format=rgba' % (zb, zh, zuschnitt[2], zuschnitt[3], logo_h)
    if pad:
        kette += ',pad=iw+%d:ih+%d:%d:%d:color=black@0' % (2 * pad, 2 * pad, pad, pad)
    fade = ''
    if nur_letzte_sekunden is not None:
        start = max(0.0, dauer - min(nur_letzte_sekunden, dauer))
        fade = ',fade=t=in:st=%.3f:d=0.3:alpha=1' % start
    pos = 'W-w-%d:H-h-%d:format=auto:shortest=1' % (rand - pad, rand - pad)
    if schatten_an:
        filter_graph = (kette + ',split[a][b];'
                        '[a]colorchannelmixer=rr=0:gg=0:bb=0:aa=%.3f,gblur=sigma=%.2f%s[sh];'
                        '[b]colorchannelmixer=aa=%.3f%s[lg];'
                        '[0:v][sh]overlay=%s[t];[t][lg]overlay=%s[out]') % (
                            schatten_deck, sigma, fade, deckkraft, fade, pos, pos)
    else:
        filter_graph = (kette + ',colorchannelmixer=aa=%.3f%s[lg];[0:v][lg]overlay=%s[out]') % (
            deckkraft, fade, pos)
    initial = fingerprint(quelle_video)
    args = [str(FFMPEG), '-nostdin', '-v', 'error', '-xerror', '-max_alloc', '536870912',
            '-protocol_whitelist', 'file,pipe', '-i', str(quelle_video),
            '-loop', '1', '-framerate', '%.3f' % fps, '-i', str(logo),
            '-filter_complex', filter_graph, '-map', '[out]', '-map', '0:a?',
            '-c:v', 'libx264', '-crf', '16', '-preset', 'medium', '-pix_fmt', 'yuv420p',
            '-c:a', 'copy', '-shortest', str(ziel)]
    try:
        run = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        raise ValueError('Logo-Einblendung nach 300 Sekunden beendet')
    if run.returncode != 0 or not ziel.is_file():
        raise ValueError('Logo-Einblendung fehlgeschlagen: ' + run.stderr[-1500:])
    if fingerprint(quelle_video) != initial:
        raise ValueError('Original hat sich waehrend der Bearbeitung veraendert; Ergebnis verworfen')
    beleg = {'schema': 1, 'art': 'jack_ci_logo_einblendung',
            'zeit': dt.datetime.now().astimezone().isoformat(),
            'original': str(quelle_video.relative_to(root.parent.parent)),
            'original_sha256': initial['sha256'],
            'logo': str(logo.relative_to(root.parent.parent)),
            'ergebnis': str(ziel.relative_to(root.parent.parent)),
            'parameter': {'position': 'unten_rechts', 'logo_hoehe_px': logo_h, 'rand_px': rand, 'querformat': quer, 'form': form, 'zuschnitt': list(zuschnitt),
                          'schatten': {'aktiv': schatten_an, 'unschaerfe_px_sigma': round(sigma, 2), 'deckkraft': schatten_deck},
                          'max_breite_anteil': max_breite_anteil,
                          'quer_min_hoehe_erreicht': quer_min_erreicht,
                          'hoehe_anteil': hoehe_anteil, 'rand_anteil': rand_anteil, 'deckkraft': deckkraft,
                          'nur_letzte_sekunden': nur_letzte_sekunden},
            'fassung': fassung or {'gemessen': False, 'gewaehlt': 'standard'},
            'hinweis': 'Nur Nachbearbeitung (A6c); Logo stammt aus der echten Markenablage, nicht vom Erzeugungsmodell.'}
    # F-15 (P07): Beleg maschinenlesbar neben das Ergebnis, an dessen SHA-256 gebunden - die Veroeffentlichung prueft ihn.
    try:
        beleg['ergebnis_sha256'] = fingerprint(ziel)['sha256']
        seite = ziel.with_name(ziel.name + LOGO_BELEG_ENDUNG)
        if not seite.exists():
            seite.write_text(json.dumps(beleg, ensure_ascii=False, indent=1), encoding='utf-8')
    except (OSError, ValueError, KeyError):
        pass
    return beleg


LOGO_BELEG_ENDUNG = '.logo.json'


def logo_nachweis(root, medium_rel, akte=None):
    """F-15 (P07): (ok, grund). Belegt ist die Logo-Einblendung, wenn (a) neben dem Medium ein Beleg
    <medium>.logo.json liegt, dessen ergebnis dieses Medium ist und dessen ergebnis_sha256 dem heutigen Hash
    entspricht, oder (b) die Videoakte (Nachbearbeitung der Kette) dieses Medium als Logo-Ergebnis fuehrt.
    Sonst: nicht belegt -> keine Veroeffentlichung."""
    root = Path(root).resolve()
    vault = root.parent.parent
    medium = (vault / medium_rel).resolve()
    if not medium.is_file():
        return False, 'Medium fehlt: %s' % medium_rel
    seite = medium.with_name(medium.name + LOGO_BELEG_ENDUNG)
    if seite.is_file():
        try:
            b = json.loads(seite.read_text(encoding='utf-8'))
            if b.get('art') == 'jack_ci_logo_einblendung' and b.get('ergebnis') == medium_rel:
                if b.get('ergebnis_sha256') == fingerprint(medium)['sha256']:
                    return True, 'Logo-Beleg %s (Logo %s)' % (seite.name, b.get('logo'))
                return False, 'Logo-Beleg passt nicht zum heutigen Medium (Hash geaendert)'
        except (OSError, ValueError, KeyError):
            return False, 'Logo-Beleg nicht lesbar'
    logo = ((akte or {}).get('nachbearbeitung') or {}).get('logo') or {}
    if isinstance(logo, dict) and logo.get('ergebnis') == medium_rel and logo.get('logo'):
        return True, 'Videoakte: Nachbearbeitung mit Logo %s' % logo.get('logo')
    return False, 'Keine belegte Logo-Einblendung (Wort-Bild-Marke) fuer dieses Medium'


def nachweis_pruefen(root, path):
    """Ein technischer Bericht bleibt nur fuer genau die gepruefte Mediendatei gueltig."""
    path=Path(path);folder=Path(root).resolve()/'betrieb/medienpruefungen'
    if path.resolve().parent!=folder or path.is_symlink():raise ValueError('Mediennachweis muss vom lokalen Pruefdienst stammen')
    if path.stat().st_size>1000000:raise ValueError('Mediennachweis zu gross')
    data=json.loads(path.read_text())
    if not isinstance(data,dict) or not isinstance(data.get('quelle'),dict) or data.get('art')!='jack_medienpruefung' or data.get('technik_bestanden') is not True:
        raise ValueError('Technische Medienpruefung nicht bestanden')
    original=data['quelle'];video=quelle(root,original.get('pfad'))
    current=fingerprint(video)
    if any(current[k]!=original.get(k) for k in ('sha256','bytes')):
        raise ValueError('Video hat sich seit der technischen Pruefung veraendert')
    return original


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='pruefe':raise SystemExit('Erlaubt: pruefe <lokaler Videopfad>')
    try:print(json.dumps(pruefen(Path(__file__).resolve().parent,sys.argv[2]),ensure_ascii=False))
    except (OSError,ValueError) as error:raise SystemExit(str(error))
