#!/bin/bash
# Abnahme fuer Playbook "Hook_Playbook" (Auftrag 45.1, Aufgabe 9a). Aufruf: pruefen.sh <entwurf.md>
# 0 = ok, 1 = mindestens ein Befund (Text auf stderr)
set -u
DATEI="${1:-}"
[ -z "$DATEI" ] && { echo "Aufruf: pruefen.sh <entwurf.md>" >&2; exit 1; }
[ -f "$DATEI" ] || { echo "BEFUND: Datei nicht gefunden: $DATEI" >&2; exit 1; }

BEFUNDE=0

# 1. Mindestens 3 nummerierte Varianten
ANZAHL=$(grep -cE "^[0-9]+\. " "$DATEI")
if [ "$ANZAHL" -lt 3 ]; then
  echo "BEFUND: nur $ANZAHL Variante(n) gefunden, mindestens 3 noetig" >&2
  BEFUNDE=1
fi

# 2. Begruendete Empfehlung
if ! grep -qiE "^## Empfehlung" "$DATEI"; then
  echo "BEFUND: kein Abschnitt 'Empfehlung' gefunden" >&2
  BEFUNDE=1
else
  EMPF=$(awk '/^## Empfehlung/{f=1;next} /^## /{f=0} f' "$DATEI")
  WOERTER=$(echo "$EMPF" | tr -cs 'A-Za-zÄÖÜäöüß' '\n' | grep -c .)
  if [ "$WOERTER" -lt 6 ]; then
    echo "BEFUND: Empfehlung ist nicht begruendet (zu kurz: $WOERTER Woerter)" >&2
    BEFUNDE=1
  fi
fi

# 3. Kein Kommentar-Koeder
if grep -iE "schreib(e)? [\"'a-zäöü0-9]+ in die kommentare|kommentiere [\"'a-zäöü0-9]+ (fuer|für)|dm (mir|uns) [\"'a-zäöü]+ (fuer|für)" "$DATEI" >/dev/null; then
  echo "BEFUND: Kommentar-Koeder gefunden (Aufforderung, ein Wort zu kommentieren/zu DMen, um an Inhalt zu gelangen)" >&2
  BEFUNDE=1
fi

# 4. Keine erfundene Verknappung/Dringlichkeit
if grep -iE "nur (noch )?heute|nur [0-9]+ (plaetze|plätze|stueck|stück)|letzte chance|jetzt sofort zugreifen" "$DATEI" >/dev/null; then
  echo "BEFUND: erfundene Verknappung/Dringlichkeit gefunden" >&2
  BEFUNDE=1
fi

# 5. Kein Wirkungs-/Verdienstversprechen ohne erkennbaren Beleg-Hinweis
if grep -iE "garantiert|risikolos|verdiene[n]? sie [0-9]|passives einkommen garantiert" "$DATEI" >/dev/null; then
  echo "BEFUND: unbelegtes Wirkungs-/Verdienstversprechen gefunden" >&2
  BEFUNDE=1
fi

# 6. Laenge je Variante <= 220 Zeichen
while IFS= read -r ZEILE; do
  TEXT=$(echo "$ZEILE" | sed -E 's/^[0-9]+\. //')
  LAENGE=${#TEXT}
  if [ "$LAENGE" -gt 220 ]; then
    echo "BEFUND: Variante laenger als 220 Zeichen ($LAENGE): ${TEXT:0:40}..." >&2
    BEFUNDE=1
  fi
done < <(grep -E "^[0-9]+\. " "$DATEI")

[ "$BEFUNDE" -ne 0 ] && exit 1
echo "Hook_Playbook: alle Pflichtpruefungen bestaetigt ($ANZAHL Varianten, Empfehlung begruendet, kein Koeder/Verknappung/Versprechen)."
exit 0
