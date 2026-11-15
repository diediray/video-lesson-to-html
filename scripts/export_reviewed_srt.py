#!/usr/bin/env python3
"""Export a reviewed transcript after verifying coverage against the ASR journal."""
import argparse,json
from pathlib import Path


def ts(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--reviewed',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    read=lambda name:[json.loads(x) for x in Path(name).read_text(encoding='utf8').splitlines() if x.strip()]
    source=read(a.source);reviewed=read(a.reviewed)
    if len(source)!=len(reviewed):raise ValueError(f'Segment count mismatch: {len(source)} vs {len(reviewed)}')
    cues=[]
    for i,(old,new) in enumerate(zip(source,reviewed)):
        if old['index']!=i or new.get('index')!=i:raise ValueError(f'Unexpected segment index at {i}')
        if any(abs(float(old[k])-float(new[k]))>.001 for k in ('start','end')):raise ValueError(f'Time range changed at {i}')
        status=new.get('review_status');text=new.get('text','').strip()
        if status not in {'reviewed','uncertain','non_speech','digital_silence'}:raise ValueError(f'No review decision at {i}')
        if status=='uncertain' and not new.get('uncertain'):raise ValueError(f'Missing uncertain flag at {i}')
        if status!='uncertain' and new.get('uncertain'):raise ValueError(f'Unexpected uncertain flag at {i}')
        spans=new.get('uncertain_spans',[])
        if spans and status!='uncertain':raise ValueError(f'Unexpected uncertainty spans at {i}')
        for span in spans:
            if not span or text.count(span)!=1:raise ValueError(f'Uncertainty span must occur exactly once at {i}')
        if not text and old.get('text','').strip() and status!='non_speech':raise ValueError(f'Nonempty original was dropped at {i}')
        if status=='non_speech' and not new.get('reason','').strip():raise ValueError(f'Missing reason for non-speech at {i}')
        if text:
            cues.append(f'{len(cues)+1}\n{ts(new["start"])} --> {ts(new["end"])}\n{text}\n')
    Path(a.output).write_text('\n'.join(cues),encoding='utf8')
    print(json.dumps({'segments':len(reviewed),'cues':len(cues),'uncertain':sum(x['review_status']=='uncertain' for x in reviewed),'output':a.output},ensure_ascii=False))
if __name__=='__main__':main()
