/* Reine Sprachfluss-Logik fuer Block 25b (Echo-Sperre, Doppel-Schutz,
 * Fuellsatz-Zeitgeber). Kein DOM-Zugriff, keine Uhr, kein globaler Zustand -
 * jede Funktion bekommt Zeit und Verlauf als Parameter. Deshalb ohne Browser
 * mit `node --check` pruefbar und mit `node test_jack_sprache.js` testbar
 * (Pruefpunkt P1).
 *
 * Zwillingsdatei server-seitig: jack_sprache.py - dieselben Regeln, gleiche
 * Namen. AENDERUNG HIER IMMER AUCH DORT NACHZIEHEN.
 *
 * Wird von index.html per <script src="/lib/jack_sprache.js"> geladen
 * (server.py, do_GET, Zweig /lib/) und haengt sich als window.JackSprache
 * ein; unter Node exportiert dieselbe Datei module.exports fuer die Tests.
 *
 * Stand 18.09.2026, Block 25b.
 */
(function (global) {
  "use strict";

  var SCHWELLE_AEHNLICHKEIT = 0.55;
  var SPRECHFENSTER_NACHLAUF_MS = 500;
  var DOPPEL_FENSTER_S = 8.0;
  var FUELLER_FRUEHESTENS_MS = 1500;
  var FUELLER_WIEDERHOL_SPERRE_MS = 10 * 60 * 1000;

  // A3: nur Anrede oder ausdrueckliches Haltewort am Satzanfang unterbricht,
  // waehrend JACK spricht.
  var ANREDE_ODER_HALTEWORT = /^(check|jack|dschaeck|dschack|tschack|jeck|stopp?|halt|warte|moment|nein)\b/i;

  var ZUSTIMMUNG_KURZ = {
    "ja": 1, "jo": 1, "joa": 1, "okay": 1, "ok": 1, "genau": 1, "gut": 1, "passt": 1,
    "mhm": 1, "weiter": 1, "alles klar": 1, "in ordnung": 1, "richtig": 1, "stimmt": 1
  };

  var EINER = {
    0: "null", 1: "eins", 2: "zwei", 3: "drei", 4: "vier", 5: "fuenf",
    6: "sechs", 7: "sieben", 8: "acht", 9: "neun", 10: "zehn", 11: "elf",
    12: "zwoelf", 13: "dreizehn", 14: "vierzehn", 15: "fuenfzehn",
    16: "sechzehn", 17: "siebzehn", 18: "achtzehn", 19: "neunzehn",
    20: "zwanzig", 30: "dreissig", 40: "vierzig", 50: "fuenfzig",
    60: "sechzig", 70: "siebzig", 80: "achtzig", 90: "neunzig"
  };

  function zahlZuWort(n) {
    n = parseInt(n, 10);
    if (isNaN(n) || n < 0 || n > 9999) return String(n);
    if (EINER.hasOwnProperty(n)) return EINER[n];
    if (n < 100) {
      var zehner = Math.floor(n / 10) * 10, einer = n % 10;
      if (einer === 0) return EINER.hasOwnProperty(zehner) ? EINER[zehner] : String(n);
      return (einer === 1 ? "ein" : EINER[einer]) + "und" + EINER[zehner];
    }
    if (n < 1000) {
      var hundert = Math.floor(n / 100), rest = n % 100;
      var kopf = (hundert === 1 ? "ein" : EINER[hundert]) + "hundert";
      return rest === 0 ? kopf : kopf + zahlZuWort(rest);
    }
    var tausend = Math.floor(n / 1000), restT = n % 1000;
    var kopfT = (tausend === 1 ? "ein" : zahlZuWort(tausend)) + "tausend";
    return restT === 0 ? kopfT : kopfT + zahlZuWort(restT);
  }

  function normalisiere(text) {
    var t = String(text || "").toLowerCase();
    t = t.replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss");
    t = t.replace(/[^a-z0-9\s]/g, " ");
    t = t.replace(/\d+/g, function (m) { return zahlZuWort(m); });
    return t.replace(/\s+/g, " ").trim();
  }

  function tokens(text) {
    var n = normalisiere(text);
    return n ? n.split(" ").filter(Boolean) : [];
  }

  function aehnlichkeit(a, b) {
    var ta = tokens(a), tb = tokens(b);
    if (!ta.length || !tb.length) return 0;
    var setB = {};
    for (var i = 0; i < tb.length; i++) setB[tb[i]] = 1;
    var setA = {};
    var schnitt = 0;
    for (i = 0; i < ta.length; i++) {
      if (!setA[ta[i]]) { setA[ta[i]] = 1; if (setB[ta[i]]) schnitt++; }
    }
    var kleinerN = Object.keys(setA).length, groesserN = Object.keys(setB).length;
    if (kleinerN > groesserN) { var tmp = kleinerN; kleinerN = groesserN; groesserN = tmp; }
    var ueberlappung = kleinerN ? schnitt / kleinerN : 0;
    // Nachbesserung nach der Opus-Pruefung (P7, ZURUECKWEISUNG 18.09.2026,
    // Fund 1): bei einer sehr kurzen Referenz (1-2 Woerter, z.B. "Weiter.")
    // reicht sonst EIN zufaellig gemeinsames Wort in einem viel laengeren,
    // unverwandten Patronsatz fuer 1,0. Nur zaehlen, wenn die Uebereinstimmung
    // AUCH gegenueber der laengeren Seite noch spuerbar ist - eine ECHTE
    // Mehrheit (> 50%, nicht nur genau die Haelfte, 2. Opus-Pruefung).
    if (kleinerN <= 2 && (!groesserN || (schnitt / groesserN) <= 0.5)) return 0;
    return ueberlappung;
  }

  // Nachbesserung nach der Opus-Pruefung (P7, Fund 1): kurze, haeufig
  // eigenstaendig gesprochene Steuer-/Zustimmungswoerter. Siehe
  // jack_sprache.py STEUERWORT_MENGE fuer die volle Begruendung.
  var STEUERWORT_MENGE = { "check": 1, "jack": 1, "dschaeck": 1, "dschack": 1,
    "tschack": 1, "jeck": 1, "stopp": 1, "stop": 1, "halt": 1, "warte": 1,
    "moment": 1, "nein": 1, "weiter": 1, "zurueck": 1, "genauer": 1,
    "vollansicht": 1 };
  for (var _sw in ZUSTIMMUNG_KURZ) { if (ZUSTIMMUNG_KURZ.hasOwnProperty(_sw)) STEUERWORT_MENGE[_sw] = 1; }

  function istReinesSteuerwort(text) {
    return !!STEUERWORT_MENGE[normalisiere(text)];
  }

  function istUnterbrechung(text) {
    var n = normalisiere(text);
    return !!n && ANREDE_ODER_HALTEWORT.test(n);
  }

  function istKurzeZustimmung(text) {
    return !!ZUSTIMMUNG_KURZ[normalisiere(text)];
  }

  function sprechfensterAktiv(jetztMs, sprichBeginnMs, sprichEndeMs, nachlaufMs) {
    nachlaufMs = nachlaufMs === undefined ? SPRECHFENSTER_NACHLAUF_MS : nachlaufMs;
    if (sprichBeginnMs === null || sprichBeginnMs === undefined) return false;
    if (sprichEndeMs === null || sprichEndeMs === undefined) return jetztMs >= sprichBeginnMs;
    return sprichBeginnMs <= jetztMs && jetztMs <= sprichEndeMs + nachlaufMs;
  }

  // Nachbesserung nach der ZWEITEN Opus-Pruefung (P7, 18.09.2026): die reine
  // Anrede/Haltewort-Ausnahme (Fund 2 der ERSTEN Pruefung) hatte eine neue
  // Luecke geoeffnet - jede JACK-Aeusserung, die selbst mit einem dieser
  // Woerter beginnt (der Fuellsatz "Moment." zum Beispiel), waere nie mehr
  // als Echo erkannt worden. Die Ausnahme tritt nur zurueck (= bleibt
  // moegliches Echo), wenn der Satz FAST EXAKT dem entspricht, was JACK
  // gerade sagt (Aehnlichkeit >= dieser Schwelle) UND das Sprechfenster noch
  // aktiv ist. Siehe jack_sprache.py fuer die volle Begruendung.
  var UNTERBRECHUNG_ECHO_SCHWELLE = 0.9;

  function istEcho(text, letzteSaetze, fuellsaetze, schwelle, zeit) {
    schwelle = schwelle === undefined ? SCHWELLE_AEHNLICHKEIT : schwelle;
    zeit = zeit || {};
    if (!String(text || "").trim()) return { echo: false, treffer: null, aehnlichkeit: 0 };
    var bester = null, wert = 0;
    var alle = [].concat(letzteSaetze || [], fuellsaetze || []);
    for (var i = 0; i < alle.length; i++) {
      var satz = alle[i];
      if (!satz) continue;
      var w = aehnlichkeit(text, satz);
      if (w > wert) { wert = w; bester = satz; }
    }
    var imFenster = zeit.jetztMs !== undefined
      && sprechfensterAktiv(zeit.jetztMs, zeit.sprichBeginnMs, zeit.sprichEndeMs, zeit.nachlaufMs);
    if (istUnterbrechung(text)) {
      // Nachbesserung (3. Opus-Pruefung, 18.09.2026): NUR gegen letzteSaetze
      // vergleichen (was JACK tatsaechlich gerade gesprochen hat), nicht
      // gegen die komplette, statische Fuellsatzliste - sonst haette
      // "Moment" IMMER Aehnlichkeit 1,0 gegen "Moment." bekommen, egal ob
      // JACK diesen Fuellsatz gerade sagt oder etwas ganz anderes.
      var wertGesprochen = 0;
      for (var j = 0; j < (letzteSaetze || []).length; j++) {
        var s2 = letzteSaetze[j];
        if (!s2) continue;
        var w2 = aehnlichkeit(text, s2);
        if (w2 > wertGesprochen) wertGesprochen = w2;
      }
      var istWohlEigenesEcho = imFenster && wertGesprochen >= UNTERBRECHUNG_ECHO_SCHWELLE;
      if (!istWohlEigenesEcho) return { echo: false, treffer: null, aehnlichkeit: 0 };
      // sonst: faellt durch zur normalen Bewertung unten.
    }
    // Ein reines Steuerwort ("weiter", "zurueck", ...) ist nur WAEHREND des
    // Sprechfensters ein moegliches Echo - danach ist es ein neuer,
    // bewusster Befehl (Block 25 E1). Ohne Zeitangaben (zeit.jetztMs fehlt)
    // bleibt die vorsichtigere alte Pruefung erhalten.
    if (istReinesSteuerwort(text) && zeit.jetztMs !== undefined && !imFenster) {
      return { echo: false, treffer: null, aehnlichkeit: 0 };
    }
    return { echo: wert >= schwelle, treffer: bester, aehnlichkeit: wert };
  }

  function entscheideEingang(text, opts) {
    opts = opts || {};
    var schwelle = opts.schwelle === undefined ? SCHWELLE_AEHNLICHKEIT : opts.schwelle;
    var nachlaufMs = opts.nachlaufMs === undefined ? SPRECHFENSTER_NACHLAUF_MS : opts.nachlaufMs;
    var e = istEcho(text, opts.letzteSaetze, opts.fuellsaetze, schwelle,
      { jetztMs: opts.jetztMs, sprichBeginnMs: opts.sprichBeginnMs, sprichEndeMs: opts.sprichEndeMs, nachlaufMs: nachlaufMs });
    if (e.echo) return { weg: "echo", grund: "aehnlich zu: " + e.treffer, aehnlichkeit: e.aehnlichkeit };
    var beginn = opts.sprichBeginnMs, ende = opts.sprichEndeMs, jetzt = opts.jetztMs;
    var jackSprichtNoch = (beginn !== null && beginn !== undefined) && (ende === null || ende === undefined);
    var imNachlauf = (ende !== null && ende !== undefined) && (beginn !== null && beginn !== undefined)
      && beginn <= jetzt && jetzt <= ende + nachlaufMs;
    if (jackSprichtNoch || imNachlauf) {
      if (istUnterbrechung(text)) return { weg: "unterbrechung", grund: "anrede_oder_haltewort", aehnlichkeit: e.aehnlichkeit };
      if (istKurzeZustimmung(text)) return { weg: "zustimmung", grund: "kurze_zustimmung", aehnlichkeit: e.aehnlichkeit };
      return { weg: "warten", grund: "kein_haltewort_waehrend_sprechen", aehnlichkeit: e.aehnlichkeit };
    }
    return { weg: "verarbeiten", grund: "", aehnlichkeit: e.aehnlichkeit };
  }

  function istDoppelt(aktion, ziel, parameterJson, verlauf, jetztS, fensterS) {
    fensterS = fensterS === undefined ? DOPPEL_FENSTER_S : fensterS;
    for (var i = 0; i < (verlauf || []).length; i++) {
      var e = verlauf[i];
      if (e.aktion === aktion && e.ziel === ziel && e.parameterJson === parameterJson) {
        var dt = jetztS - e.zeitS;
        if (dt >= 0 && dt <= fensterS) return true;
      }
    }
    return false;
  }

  function fuellsatzZeitpunktOk(dauerSeitFrageMs, fruehestensMs) {
    fruehestensMs = fruehestensMs === undefined ? FUELLER_FRUEHESTENS_MS : fruehestensMs;
    return dauerSeitFrageMs >= fruehestensMs;
  }

  function waehleFuellsatz(saetze, kuerzlichGesagt, jetztMs, wiederholSperreMs) {
    wiederholSperreMs = wiederholSperreMs === undefined ? FUELLER_WIEDERHOL_SPERRE_MS : wiederholSperreMs;
    kuerzlichGesagt = kuerzlichGesagt || {};
    for (var i = 0; i < (saetze || []).length; i++) {
      var satz = saetze[i];
      var letzte = kuerzlichGesagt[satz];
      if (letzte === undefined || letzte === null || jetztMs - letzte >= wiederholSperreMs) return satz;
    }
    return null;
  }

  function wendeWoerterbuchAn(text, woerterbuch) {
    var ergebnis = text || "";
    woerterbuch = woerterbuch || {};
    for (var falsch in woerterbuch) {
      if (!woerterbuch.hasOwnProperty(falsch) || !falsch) continue;
      var richtig = woerterbuch[falsch];
      var re = new RegExp("\\b" + falsch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "gi");
      ergebnis = ergebnis.replace(re, richtig);
    }
    return ergebnis;
  }

  // S-1 P3c (Zwilling zu jack_sprache.wende_kontext_woerterbuch_an): Verhoerer nur im passenden Zusammenhang.
  function wendeKontextWoerterbuchAn(text, regeln) {
    var ergebnis = text || "";
    var klein = ergebnis.toLowerCase();
    (regeln || []).forEach(function (regel) {
      var falsch = regel.falsch, richtig = regel.richtig, hinweise = regel.wenn_eines_von || [];
      if (!falsch || !richtig) return;
      var passt = hinweise.some(function (h) { return klein.indexOf(String(h).toLowerCase()) !== -1; });
      if (!passt) return;
      var re = new RegExp("\\b" + falsch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "gi");
      ergebnis = ergebnis.replace(re, richtig);
    });
    return ergebnis;
  }

  var JackSprache = {
    SCHWELLE_AEHNLICHKEIT: SCHWELLE_AEHNLICHKEIT,
    SPRECHFENSTER_NACHLAUF_MS: SPRECHFENSTER_NACHLAUF_MS,
    DOPPEL_FENSTER_S: DOPPEL_FENSTER_S,
    FUELLER_FRUEHESTENS_MS: FUELLER_FRUEHESTENS_MS,
    FUELLER_WIEDERHOL_SPERRE_MS: FUELLER_WIEDERHOL_SPERRE_MS,
    normalisiere: normalisiere,
    aehnlichkeit: aehnlichkeit,
    istEcho: istEcho,
    istUnterbrechung: istUnterbrechung,
    istKurzeZustimmung: istKurzeZustimmung,
    istReinesSteuerwort: istReinesSteuerwort,
    sprechfensterAktiv: sprechfensterAktiv,
    entscheideEingang: entscheideEingang,
    istDoppelt: istDoppelt,
    fuellsatzZeitpunktOk: fuellsatzZeitpunktOk,
    waehleFuellsatz: waehleFuellsatz,
    wendeWoerterbuchAn: wendeWoerterbuchAn,
    wendeKontextWoerterbuchAn: wendeKontextWoerterbuchAn,
    zahlZuWort: zahlZuWort
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = JackSprache;
  }
  if (typeof global !== "undefined") {
    global.JackSprache = JackSprache;
  }
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
