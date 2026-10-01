#!/usr/bin/env python3
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import jack_betrieb as b

def run(root):
    start=b.now().isoformat()
    record={'start':start,'quelle':'timer','neue_dateien':[]}
    code=0
    try:
        record['neue_dateien']=b.tick(root)
        record['status']='ok'
    except Exception as error:
        code=1
        record.update(status='fehler',fehler=b.redact(str(error))[:300])
    record['ende']=b.now().isoformat()
    b.append(b.area(root)/'routinen.jsonl',record)
    print(json.dumps(record,ensure_ascii=False))
    return code

if __name__ == '__main__':
    raise SystemExit(run(Path(__file__).resolve().parent))
