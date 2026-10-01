"""SearXNG ohne zusätzlichen HTTP-Dienst; ausschließlich ausdrückliche Suchanfrage."""
import sys,json,os
from pathlib import Path
runtime=Path(sys.argv[1]);sys.path.insert(0,str(runtime/'source'))
request=json.loads(sys.stdin.read(4096));query=request['query']
if not isinstance(query,str) or not 3<=len(query)<=300:raise ValueError('Ungültige Suchanfrage')
os.environ['SEARXNG_SETTINGS_PATH']=str(runtime/'settings.yml');os.environ['SEARXNG_DATA_PATH']=str(runtime/'daten')
from flask import Flask
from searx import settings
from searx.search import initialize,Search
from searx.search.models import SearchQuery,EngineRef
engines=[x for x in settings['engines'] if x['name'] in ('duckduckgo','brave')]
if len(engines)!=2:raise ValueError('Suchanbieter nicht wie geprüft verfügbar')
initialize(engines,enable_metrics=False)
app=Flask('JACK-Websuche-ohne-Listener')
with app.test_request_context('/'):
 out=Search(SearchQuery(query,[EngineRef(x['name'],'general') for x in engines],lang='de-DE',safesearch=1,timeout_limit=8)).search()
 data=[{'titel':str(x['title'])[:500],'url':str(x['url'])[:2000],'text':str(x['content'])[:1500],'engines':list(x['engines'])} for x in out.get_ordered_results()[:10]]
 print(json.dumps({'treffer':data,'fehler':[list(x) for x in out.unresponsive_engines]},ensure_ascii=False))
