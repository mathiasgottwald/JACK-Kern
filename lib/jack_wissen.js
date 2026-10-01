/* Wissensuebersicht: lokale Ansicht, keine Aenderung an Quellen oder KI-Rechten. */
(function(host){
  'use strict';
  const KEY='jack.wissen.ansicht.v1', SEITE=40;
  const FARBEN={Marken:'#d9b969',Projekte:'#80c8c4',Agenten:'#c9afdd','Aufträge':'#94c8ac',Holding:'#d6d4c8'};
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const parent=p=>p.includes('/')?p.slice(0,p.lastIndexOf('/')):'';
  function modell(raw){
    if(!raw||!Array.isArray(raw.knoten)||!Array.isArray(raw.gruppen))throw new Error('Die Wissenskarte ist nicht lesbar.');
    const nodes=[],map=new Map(),groups=new Map();
    for(const k of raw.knoten){
      if(!Array.isArray(k)||typeof k[0]!=='string'||typeof k[5]!=='string'||map.has(k[5]))continue;
      const group=raw.gruppen[k[1]];if(typeof group!=='string')continue;
      const n={name:k[0],pfad:k[5],gruppe:group,ordner:k[2]===0,zweck:String(k[6]||''),suche:norm(k[0]+' '+k[5])};
      nodes.push(n);map.set(n.pfad,n);if(!groups.has(group))groups.set(group,[]);groups.get(group).push(n);
    }
    for(const items of groups.values())items.sort((a,b)=>Number(b.ordner)-Number(a.ordner)||a.name.localeCompare(b.name,'de'));
    return {nodes,map,groups,zeit:raw.zeit,ausgelassen:Number(raw.weggelassen_knoten)||0};
  }
  function einstellungen(raw,model){
    let data={};try{data=JSON.parse(raw||'{}')||{};}catch(_){}
    const list=v=>Array.isArray(v)?v.filter(x=>typeof x==='string').slice(0,2000):[];
    return {gruppen:new Set(list(data.gruppen).filter(g=>model.groups.has(g))),
            pfade:new Set(list(data.pfade).filter(p=>model.map.has(p)))};
  }
  function verborgen(n,state){
    if(state.gruppen.has(n.gruppe))return true;
    for(const p of state.pfade)if(n.pfad===p||n.pfad.startsWith(p+'/'))return true;
    return false;
  }
  function liste(model,state,{gruppe='',pfad=null,suche='',ausgeblendet=false}={}){
    if(ausgeblendet)return [...state.pfade].map(p=>model.map.get(p)).filter(Boolean);
    const q=norm(suche).trim(),base=gruppe?(model.groups.get(gruppe)||[]):model.nodes;
    return base.filter(n=>{
      if(verborgen(n,state))return false;
      if(q)return n.suche.includes(q);
      if(pfad!==null)return parent(n.pfad)===pfad;
      const p=model.map.get(parent(n.pfad));return !p||p.gruppe!==n.gruppe;
    }).sort((a,b)=>Number(b.ordner)-Number(a.ordner)||a.name.localeCompare(b.name,'de'));
  }
  // Nur fuer isolierte Fachpruefungen, keine Browser-/Netzabhaengigkeit.
  if(typeof module!=='undefined'&&module.exports)module.exports={modell,einstellungen,verborgen,liste,escape};
  if(!host||!host.document)return;
  let model=null,loading=null,mount=null,settings={gruppen:new Set(),pfade:new Set()};
  let state={gruppe:'',pfad:null,suche:'',ausgeblendet:false,seite:0,anpassen:false};
  let preview=0,lastFocus=null;
  const number=n=>n.toLocaleString('de-AT');
  function speichern(){
    try{host.localStorage.setItem(KEY,JSON.stringify({gruppen:[...settings.gruppen],pfade:[...settings.pfade]}));return true;}
    catch(_){meldung('Die Ansicht gilt für diese Sitzung; der Browser konnte sie nicht speichern.');return false;}
  }
  function meldung(text){const el=mount?.querySelector('[data-wstatus]');if(el)el.textContent=text;}
  function knopf(text,action,extra=''){return '<button type="button" class="kw-button" data-waktion="'+action+'" '+extra+'>'+text+'</button>';}
  async function laden(){
    if(model)return model;
    if(!loading)loading=fetch('/gehirn/karte',{cache:'no-store'}).then(async r=>{
      const d=await r.json();if(!r.ok||d.fehler)throw new Error(d.fehler||'Die Karte ist gerade nicht abrufbar.');
      model=modell(d);let saved='';try{saved=host.localStorage.getItem(KEY)||'';}catch(_){}
      settings=einstellungen(saved,model);return model;
    }).finally(()=>{loading=null;});
    return loading;
  }
  function optionen(){
    return '<div class="kw-optionen" '+(state.anpassen?'':'hidden')+'><h3>Was möchtest du sehen?</h3>'+
      '<p>Blende Bereiche oder einzelne Einträge aus. Die Quellen bleiben erhalten und für JACK unverändert verfügbar.</p>'+
      '<div class="kw-checks">'+[...model.groups.keys()].map(g=>'<label><input type="checkbox" data-wgruppe="'+escape(g)+'" '+(settings.gruppen.has(g)?'':'checked')+'><span>'+escape(g)+'</span></label>').join('')+'</div>'+
      knopf('Alle Einträge wieder einblenden','alle')+'</div>';
  }
  function kopf(){
    const sichtbar=model.nodes.filter(n=>!verborgen(n,settings)).length;
    return '<div class="kw-kopf"><div><p class="kw-eyebrow">DEINE WISSENSBASIS</p><h2>Dein Wissen im Überblick.</h2>'+
      '<p>'+number(sichtbar)+' von '+number(model.nodes.length)+' Ordnern und Notizen in der Ansicht</p></div>'+
      knopf(document.getElementById('buehne')?.classList.contains('gehirnvollbild')?'Kleine Ansicht':'Großansicht','gross','aria-pressed="'+String(document.getElementById('buehne')?.classList.contains('gehirnvollbild'))+'"')+'</div>'+
      '<div class="kw-werkzeuge"><label class="kw-suche"><span>'+escape(state.gruppe?'Suchen in '+state.gruppe:'Suchen in allen sichtbaren Bereichen')+'</span><input type="search" data-wsuche placeholder="Name, Marke oder Thema …" aria-label="Wissen durchsuchen" value="'+escape(state.suche)+'" autocomplete="off"></label>'+
      knopf('Ansicht anpassen','ansicht','aria-expanded="'+state.anpassen+'"')+'</div>'+optionen()+
      '<div class="kw-nav">'+knopf('Übersicht','start','aria-current="'+(!state.gruppe&&!state.suche&&!state.ausgeblendet?'page':'false')+'"')+
      knopf('Ausgeblendete ('+(settings.pfade.size+settings.gruppen.size)+')','verborgen','aria-pressed="'+state.ausgeblendet+'"')+
      '<button type="button" class="kw-button" data-oeffne="gehirn">Netzwerk ansehen</button></div>';
  }
  function karten(){
    const descriptions={Marken:'Stand, Entscheidungen und Wissen je Marke',Projekte:'Vorhaben, Arbeitsergebnisse und Hintergründe',Agenten:'Rollen und ihre Aufgaben','Aufträge':'Arbeit und nachvollziehbare Ergebnisse',Holding:'Gemeinsame Grundlagen und Ablage'};
    return '<div class="kw-karten">'+[...model.groups].filter(([g])=>!settings.gruppen.has(g)).map(([g,nodes])=>{
      const n=nodes.filter(n=>!verborgen(n,settings)).length;
      return '<button type="button" class="kw-karte" data-wbereich="'+escape(g)+'" style="--kw-farbe:'+(FARBEN[g]||'#d6d4c8')+'"><span class="kw-karte-top"><span class="kw-punkt"></span><span>Öffnen ↗</span></span><strong>'+escape(g)+'</strong><span class="kw-karte-text">'+escape(descriptions[g]||'Wissensbereich')+'</span><span class="kw-zahl">'+number(n)+' <small>Einträge</small></span></button>';
    }).join('')+'</div>';
  }
  function pfadzeile(){
    if(!state.gruppe)return '';
    let h='<nav class="kw-pfad" aria-label="Wissenspfad">'+knopf(escape(state.gruppe),'bereichstart');
    if(state.pfad!==null){
      let p='';for(const part of state.pfad.split('/')){
        p+=(p?'/':'')+part;const n=model.map.get(p);if(!n||n.gruppe!==state.gruppe)continue;
        h+='<span>/</span>'+knopf(escape(n.name),'pfad','data-wpfad="'+escape(p)+'"');
      }
    }
    return h+'</nav>';
  }
  function ergebnisse(){
    const items=liste(model,settings,state),max=Math.max(1,Math.ceil(items.length/SEITE));
    state.seite=Math.min(state.seite,max-1);
    const shown=items.slice(state.seite*SEITE,(state.seite+1)*SEITE);
    const title=state.ausgeblendet?'Einzeln ausgeblendet':state.suche?'Suchergebnisse':state.gruppe;
    let h=pfadzeile()+'<div class="kw-listenkopf"><h3>'+escape(title)+'</h3><span>'+number(items.length)+(items.length===1?' Eintrag':' Einträge')+'</span></div>';
    if(state.ausgeblendet&&settings.gruppen.size)h+='<div class="kw-gruppen-zurueck">'+[...settings.gruppen].map(g=>knopf(escape(g)+' wieder einblenden','gruppe-zurueck','data-wname="'+escape(g)+'"')).join('')+'</div>';
    h+='<div class="kw-liste">'+shown.map(n=>'<div class="kw-zeile"><button type="button" class="kw-eintrag" data-wlesen="'+escape(n.pfad)+'"><span class="kw-art" aria-hidden="true">'+(n.ordner?'▤':'▱')+'</span><span><strong>'+escape(n.name)+'</strong><small>'+escape(n.pfad||n.gruppe)+'</small></span><span aria-hidden="true">'+(n.ordner?'›':'↗')+'</span></button>'+knopf(state.ausgeblendet?'Einblenden':'Ausblenden',state.ausgeblendet?'ein':'aus','data-wpfad="'+escape(n.pfad)+'" aria-label="'+(state.ausgeblendet?'Einblenden: ':'Ausblenden: ')+escape(n.name)+'"')+'</div>').join('')+'</div>';
    if(!items.length)h+='<div class="kw-leer">'+(state.ausgeblendet?'Keine einzelnen Einträge ausgeblendet.':state.suche?'Keine sichtbaren Treffer. Suche verkürzen oder ausgeblendete Bereiche wieder einblenden.':'Hier sind keine sichtbaren Einträge. Über den Wissenspfad kommst du zurück.')+'</div>';
    if(max>1)h+='<div class="kw-seiten">'+knopf('← Zurück','zurueck',state.seite===0?'disabled':'')+'<span>Seite '+(state.seite+1)+' von '+max+'</span>'+knopf('Weiter →','weiter',state.seite>=max-1?'disabled':'')+'</div>';
    return h;
  }
  function render(fokus){
    if(!mount?.isConnected||!model)return;
    const status=mount.querySelector('[data-wstatus]')?.textContent||'';
    mount.innerHTML=kopf()+'<div class="kw-inhalt">'+(!state.gruppe&&!state.suche&&!state.ausgeblendet?karten():ergebnisse())+'</div>'+
      '<p class="kw-status" data-wstatus role="status" aria-live="polite">'+escape(status)+'</p>'+
      '<p class="kw-fuss">Stand '+escape(model.zeit?new Date(model.zeit).toLocaleString('de-AT'):'unbekannt')+'. '+number(model.ausgelassen)+' andere Dateien sind in dieser Notizübersicht nicht enthalten.</p>'+
      '<dialog class="kw-vorschau" hidden aria-label="Wissenseintrag lesen"></dialog>';
    if(fokus==='suche')mount.querySelector('[data-wsuche]').focus();
    else if(fokus)mount.querySelector('[data-waktion="'+fokus+'"]')?.focus();
  }
  function verstecken(p){
    if(!model.map.has(p))return;
    if(settings.pfade.size>=2000){meldung('Für weitere Ausblendungen bitte einen ganzen Bereich wählen.');return;}
    settings.pfade.add(p);render('verborgen');speichern();meldung('Eintrag aus der Ansicht genommen. Unter „Ausgeblendete“ kannst du ihn zurückholen.');
  }
  function zu(){
    preview++;const p=mount?.querySelector('.kw-vorschau');if(p){if(p.open)p.close();p.hidden=true;p.innerHTML='';}
    if(lastFocus?.isConnected)lastFocus.focus();else mount?.querySelector('[data-wsuche]')?.focus();
  }
  async function lesen(path){
    const n=model.map.get(path);if(!n)return;
    if(n.ordner){state={...state,gruppe:n.gruppe,pfad:n.pfad,suche:'',ausgeblendet:false,seite:0};render('bereichstart');return;}
    const turn=++preview;lastFocus=document.activeElement;
    const el=mount.querySelector('.kw-vorschau');if(!el)return;
    el.hidden=false;
    el.innerHTML='<div class="kw-vorschau-kopf"><div><h3>'+escape(n.name)+'</h3><p>'+escape(n.pfad)+'</p></div>'+knopf('Schließen','zu')+'</div><div class="kw-lesetext" tabindex="0">Wird gelesen …</div>';
    el.showModal();
    el.querySelector('[data-waktion="zu"]').focus();
    try{
      const r=await fetch('/gehirn/notiz',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pfad:path})});
      const d=await r.json();if(turn!==preview||!el.isConnected)return;
      el.querySelector('.kw-lesetext').textContent=d.fehler||d.text||(r.ok?'Diese Quelle enthält keinen lesbaren Text.':'Diese Quelle ist gerade nicht lesbar.');
    }catch(_){if(turn===preview&&el.isConnected)el.querySelector('.kw-lesetext').textContent='Diese Quelle ist gerade nicht lesbar.';}
  }
  function click(e){
    const button=e.target.closest('button');if(!button||!mount.contains(button))return;
    if(button.dataset.wbereich){
      const group=button.dataset.wbereich,roots=liste(model,settings,{gruppe:group});
      state={...state,gruppe:group,pfad:roots.length===1&&roots[0].ordner?roots[0].pfad:null,suche:'',ausgeblendet:false,seite:0};
      render('bereichstart');return;
    }
    if('wlesen' in button.dataset){lesen(button.dataset.wlesen);return;}
    const action=button.dataset.waktion,p=button.dataset.wpfad;
    if(!action)return;
    if(action==='zu'){zu();return;}
    if(action==='gross'){
      const stage=document.getElementById('buehne');stage?.classList.toggle('gehirnvollbild');
      button.textContent=stage?.classList.contains('gehirnvollbild')?'Kleine Ansicht':'Großansicht';
      button.setAttribute('aria-pressed',String(stage?.classList.contains('gehirnvollbild')));return;
    }
    if(action==='neu'){an(mount,true);return;}
    if(action==='ansicht'){state.anpassen=!state.anpassen;render('ansicht');return;}
    if(action==='start')state={...state,gruppe:'',pfad:null,suche:'',ausgeblendet:false,seite:0};
    if(action==='bereichstart')state={...state,pfad:null,suche:'',seite:0};
    if(action==='pfad')state={...state,pfad:p,suche:'',seite:0};
    if(action==='verborgen')state={...state,ausgeblendet:!state.ausgeblendet,gruppe:'',pfad:null,suche:'',seite:0};
    if(action==='weiter')state.seite++;
    if(action==='zurueck')state.seite=Math.max(0,state.seite-1);
    if(action==='aus'){verstecken(p);return;}
    if(action==='ein'){settings.pfade.delete(p);render('verborgen');speichern();meldung('Eintrag wieder in der Ansicht. Ein ausgeblendeter übergeordneter Bereich muss ebenfalls eingeblendet sein.');return;}
    if(action==='gruppe-zurueck'){settings.gruppen.delete(button.dataset.wname);render('verborgen');speichern();return;}
    if(action==='alle'){settings={gruppen:new Set(),pfade:new Set()};state={...state,gruppe:'',pfad:null,suche:'',ausgeblendet:false,seite:0};render('ansicht');speichern();meldung('Alle Bereiche und Einträge wieder eingeblendet.');return;}
    render(action==='weiter'||action==='zurueck'?action:'start');
  }
  async function an(ziel,retry=false){
    if(!ziel)return;
    if(mount===ziel&&ziel.querySelector('.kw-kopf')&&!retry)return;
    preview++;mount=ziel;ziel.classList.add('kw-raum');
    ziel.innerHTML='<div class="kw-leer" role="status">Deine Wissensübersicht wird geladen …</div>';
    ziel.onclick=click;
    ziel.oninput=e=>{
      if(!e.target.matches('[data-wsuche]'))return;
      const caret=e.target.selectionStart;
      state.suche=e.target.value;state.seite=0;state.ausgeblendet=false;render('suche');
      try{mount.querySelector('[data-wsuche]').setSelectionRange(caret,caret);}catch(_){}
    };
    ziel.onchange=e=>{
      if(!e.target.matches('[data-wgruppe]'))return;
      const g=e.target.dataset.wgruppe;e.target.checked?settings.gruppen.delete(g):settings.gruppen.add(g);
      if(settings.gruppen.has(state.gruppe)){state.gruppe='';state.pfad=null;}
      state.seite=0;render('ansicht');speichern();
    };
    ziel.onkeydown=e=>{
      const dialog=ziel.querySelector('.kw-vorschau');
      if(dialog&&!dialog.hidden){
        if(e.key==='Escape'){e.stopPropagation();e.preventDefault();zu();}
        if(e.key==='Tab'){
          const els=[...dialog.querySelectorAll('button,[tabindex="0"]')],first=els[0],last=els[els.length-1];
          if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
          else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
        }
      }
    };
    try{await laden();if(mount===ziel&&ziel.isConnected)render();}
    catch(error){if(mount===ziel&&ziel.isConnected)ziel.innerHTML='<div class="kw-leer">'+escape(error.message)+'</div>'+knopf('Erneut versuchen','neu');}
  }
  host.JackWissen={an};
})(typeof window==='undefined'?null:window);
