"""
dump_detections.py 결과 분석: 모델·입력 크기·conf별 탐지율과 오탐, 잘림·높이별 사람 탐지율,
정답 물체 위에 모델이 붙인 클래스, 오탐이 찍힌 위치를 출력한다.

실행 (ai/ 폴더에서): python eval/analyze_dumps.py
"""
import json, gzip, collections
from pathlib import Path
U = str(Path(__file__).resolve().parent.parent / "runs")
SC=['unity-classroom-03-s1','unity-classroom-03-s2','unity-classroom-03-s3']
GT={}
for s in SC:
    for l in open(f'{U}/unity/{s}/frames.jsonl'):
        r=json.loads(l)
        for cam in ('cam1','cam2'):
            g=[]
            for o in r['objects']:
                bb=(o.get('bbox') or {}).get(cam); v=(o.get('visible_ratio') or {}).get(cam)
                if bb: g.append(dict(cls=o['cls'],bbox=bb,vis=v,oid=o['object_id'],cut=bb[0]<=3 or bb[1]<=3 or bb[2]>=1917 or bb[3]>=1077,h=bb[3]-bb[1]))
            GT[(s,r['frame'],cam)]=g
def iou(a,b):
    ix=max(0,min(a[2],b[2])-max(a[0],b[0])); iy=max(0,min(a[3],b[3])-max(a[1],b[1])); i=ix*iy
    u=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-i; return i/u if u>0 else 0
def load(name):
    return {(d['scene'],d['frame'],d['camera']):d['boxes'] for d in map(json.loads,gzip.open(f'{U}/eval/dumps/{name}.jsonl.gz','rt'))}
D={n:load(n) for n in ['v2_640','v2_1280','v1_640','v1_1280','coco_640','coco_1280']}
ALIAS={'coco':{'person':'person','chair':'chair','dining table':'desk'}}
def mapped(name,boxes):
    out=[]
    for c,p,*b in boxes:
        if name.startswith('coco'):
            if c in ALIAS['coco']: out.append((ALIAS['coco'][c],p,b))
        else: out.append((c,p,b))
    return out
def evaluate(name,thr,cls,scenes=SC,cams=('cam1','cam2'),split=False):
    tp=fp=n=0; sp=collections.defaultdict(lambda:[0,0])
    for k,g in GT.items():
        if k[0] not in scenes or k[2] not in cams: continue
        gts=[x for x in g if x['cls']==cls and x['vis'] is not None and x['vis']>=0.5]
        dets=[d for d in mapped(name,D[name].get(k,[])) if d[0]==cls and d[1]>=thr]
        pairs=sorted(((iou(x['bbox'],d[2]),gi,di) for gi,x in enumerate(gts) for di,d in enumerate(dets)),reverse=True)
        ug,ud=set(),set()
        for v,gi,di in pairs:
            if v<0.5 or gi in ug or di in ud: continue
            ug.add(gi);ud.add(di)
        n+=len(gts); tp+=len(ug); fp+=len(dets)-len(ud)
        if split:
            for gi,x in enumerate(gts):
                key=('잘림' if x['cut'] else '전신', '<300' if x['h']<300 else ('300-450' if x['h']<450 else '450+'))
                sp[key][0]+=1; sp[key][1]+=gi in ug
    return tp,n,fp,sp
print('=== 1. 클래스별 탐지율 / 오탐 (S1~S3 전체, 가려짐<50%) ===')
for cls in ['person','chair','desk']:
    print(f'\n[{cls}]  모델_입력  |' + ''.join(f'  conf≥{t}        ' for t in (0.1,0.25,0.4,0.5)))
    for name in D:
        if cls=='desk' and name.startswith('v') is False and False: pass
        row=f'  {name:10}|'
        for t in (0.1,0.25,0.4,0.5):
            tp,n,fp,_=evaluate(name,t,cls); row+=f' {100*tp/max(n,1):5.1f}% 오탐{fp:5d}  '
        print(row)
print('\n=== 2. 사람: 잘림·높이별 (conf≥0.4) ===')
for name in ['v2_640','v2_1280','coco_640','coco_1280']:
    _,_,_,sp=evaluate(name,0.4,'person',split=True)
    print(f'  {name:10}', '  '.join(f'{a}{b}:{v[1]}/{v[0]}({100*v[1]/v[0]:.0f}%)' for (a,b),v in sorted(sp.items())))
print('\n=== 3. 장면·카메라별 사람 탐지율 (conf≥0.4) ===')
for name in ['v2_640','coco_640','coco_1280']:
    print(f'  {name:10}', '  '.join(f"{s[-2:]}/{c}:{100*evaluate(name,0.4,'person',[s],[c])[0]/max(1,evaluate(name,0.4,'person',[s],[c])[1]):.0f}%" for s in SC for c in ('cam1','cam2')))
# 4. what do models predict on desk / cart / chair GT boxes
print('\n=== 4. 정답 물체 위에 모델이 붙인 클래스 (IoU≥0.5, conf≥0.25) ===')
for name in D:
    conf=collections.defaultdict(collections.Counter)
    for k,g in GT.items():
        boxes=[b for b in D[name].get(k,[]) if b[1]>=0.25]
        for x in g:
            if x['cls'] not in ('desk','cart','chair') or x['vis'] is None or x['vis']<0.5: continue
            best=max(((iou(x['bbox'],b[2:]),b[0]) for b in boxes),default=(0,None))
            conf[x['cls']][best[1] if best[0]>=0.5 else '(없음)']+=1
    print(f'  {name:10}', {c:dict(v.most_common(4)) for c,v in conf.items()})
# 5. false positives: what GT do they sit on
print('\n=== 5. 오탐(conf≥0.4)이 어디에 찍혔나: 가장 많이 겹친 정답 물체 (IoU≥0.1) ===')
for name in D:
    where=collections.defaultdict(collections.Counter)
    for k,g in GT.items():
        for c,p,b in mapped(name,D[name].get(k,[])):
            if p<0.4: continue
            ious=[(iou(x['bbox'],b),x['cls']) for x in g]
            same=[v for v,cl in ious if cl==c and v>=0.5]
            if same: continue
            best=max(ious,default=(0,None))
            where[c][best[1] if best[0]>=0.1 else '배경']+=1
    print(f'  {name:10}', {c:dict(v.most_common(4)) for c,v in where.items()})
