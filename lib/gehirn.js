/* Originalbild aus Obsidian. Kein Nachbau und keine gespeicherten Ersatzbilder. */
window.JackGehirn=(()=>{
  let generation=0,timer=null,currentURL=null;
  const el=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
  const send=data=>fetch('/obsidian/steuerung',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  function hide(){generation++;clearTimeout(timer);timer=null;document.body.classList.remove('gehirn-offen');if(currentURL){URL.revokeObjectURL(currentURL);currentURL=null;}send({art:'stop'}).catch(()=>{});}
  async function show(container){
    hide();const own=generation;document.body.classList.add('gehirn-offen');container.replaceChildren();
    const bar=el('div');bar.className='gehirnwerkzeuge';const button=el('button','In Obsidian öffnen');
    const hint=el('p','Verbindung zum Originalgraphen wird geprüft …');hint.className='gehirnstand';hint.setAttribute('role','status');
    const image=el('img');image.alt='Originalgraph aus Obsidian – GOTT WALD HOLDING';image.hidden=true;image.style.cssText='display:none;width:100%;max-height:70vh;object-fit:contain;touch-action:none;cursor:grab';
    const info=el('p','Hier erscheint der echte Obsidian-Graph. Zoomen und Verschieben wirken direkt auf diese Ansicht. Änderungen an Dateien zeigt Obsidian nach seiner Verarbeitung.');
    info.className='gehirnstand';bar.append(button);container.append(bar,hint,image,info);
    let seq=0,busy=false,drag=false,last=0;
    button.onclick=()=>{hint.textContent='PROBLEM: Obsidian ist nach zwei Speicherabbrüchen gestoppt. Der weitere Diagnosetest wartet auf deine Freigabe.';};
    const position=e=>{const r=image.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))};};
    const action=(art,e,delta)=>send({art,seq,...position(e),...(delta===undefined?{}:{delta})}).catch(()=>{});
    image.onwheel=e=>{e.preventDefault();action('wheel',e,e.deltaY);};
    image.onpointerdown=e=>{drag=true;image.setPointerCapture(e.pointerId);action('down',e);};
    image.onpointermove=e=>{if(drag&&Date.now()-last>45){last=Date.now();action('move',e);}};
    image.onpointerup=e=>{drag=false;action('up',e);};
    image.onpointercancel=e=>{drag=false;action('up',e);};
    image.ondragstart=()=>false;
    async function poll(){
      if(own!==generation||busy)return;busy=true;
      try{
        await send({art:'ansehen'});
        const state=await(await fetch('/obsidian/status')).json();
        if(own!==generation)return;
        if(!state.live){image.hidden=true;image.style.display='none';hint.textContent='Nicht live · '+state.fehler;hint.dataset.live='false';}
        else{
          const response=await fetch('/obsidian/bild');
          if(!response.ok)throw Error('Obsidian liefert kein aktuelles Bild.');
          const blob=await response.blob();if(own!==generation)return;
          const next=URL.createObjectURL(blob),old=currentURL;currentURL=next;image.src=next;image.hidden=false;image.style.display='block';
          if(old)URL.revokeObjectURL(old);seq=state.seq;
          hint.textContent='Live · Originalgraph aus Obsidian · GOTT WALD HOLDING';hint.dataset.live='true';
        }
      }catch(error){image.hidden=true;image.style.display='none';hint.textContent='Nicht live · '+error.message;hint.dataset.live='false';}
      finally{busy=false;if(own===generation)timer=setTimeout(poll,500);}
    }
    poll();
  }
  return {show,hide};
})();
