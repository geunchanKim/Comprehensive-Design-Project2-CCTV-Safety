"""
라벨 세트(label_set.py make 결과)를 고치는 로컬 라벨링 화면. 외부로 아무것도 보내지 않는다

사용법
  python eval/label_tool.py ~/datasets/classroom-det-v1          # http://localhost:8765 열기
  python eval/label_tool.py ~/datasets/classroom-det-v1 --port 8800

조작
  상자 클릭 → 선택, Delete/Backspace → 지우기, C → 클래스 바꾸기 (사람 ↔ 의자)
  빈 곳 드래그 → 새 상자 (1 = 사람, 2 = 의자 중 지금 고른 클래스)
  Enter 또는 → → 저장하고 다음, ← → 이전 (저장 안 한 변경은 확인), S → 저장만
  저장하면 그 사진은 "확인함"으로 기록된다 (<dataset>/reviewed.json). 채점은 확인 안 한 사진이 있으면 알린다

같은 물체에 겹친 상자(같은 클래스, IoU 0.5 이상)는 점선으로 표시한다. 대부분 지워야 할 중복이다
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from label_set import CLASSES, read_yolo, to_yolo  # noqa: E402

W, H = 1920, 1080   # 녹화 해상도 (라벨 파일은 정규화 좌표라 화면 크기와 무관)


def load_reviewed(dataset: Path) -> dict:
    path = dataset / "reviewed.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_labels(dataset: Path, name: str, boxes: list[dict]) -> None:
    """boxes: [{"cls": "person"|"chair", "box": [x1, y1, x2, y2] 픽셀}] → YOLO txt + 확인 기록"""
    lines = []
    for b in boxes:
        x1, y1, x2, y2 = (max(0.0, min(float(v), lim)) for v, lim in zip(b["box"], (W, H, W, H)))
        if x2 - x1 >= 2 and y2 - y1 >= 2 and b["cls"] in CLASSES:
            lines.append(f"{CLASSES.index(b['cls'])} {to_yolo((x1, y1, x2, y2), W, H)}\n")
    (dataset / "labels" / f"{name}.txt").write_text("".join(lines))
    reviewed = load_reviewed(dataset)
    reviewed[name] = len(lines)
    (dataset / "reviewed.json").write_text(json.dumps(reviewed, indent=1, ensure_ascii=False))


PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>라벨 확인</title>
<style>
:root{--bg:#111;--fg:#eee;--muted:#999;--person:#22c55e;--chair:#e879f9;--sel:#facc15}
body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}
header{display:flex;gap:12px;align-items:center;padding:8px 12px;flex-wrap:wrap}
header b{font-size:15px}.muted{color:var(--muted)}
button{background:#333;color:var(--fg);border:1px solid #555;border-radius:6px;padding:4px 10px;cursor:pointer}
button.on{outline:2px solid var(--sel)}
#wrap{padding:0 12px}canvas{width:100%;cursor:crosshair;display:block}
.k{border:1px solid #555;border-radius:4px;padding:0 4px;font-family:monospace}
#bar{height:6px;background:#333;margin:0 12px}#bar i{display:block;height:100%;background:var(--person)}
</style></head><body>
<header><b id="name"></b><span id="pos" class="muted"></span><span id="state"></span>
<button id="b1" onclick="setCls('person')">1 사람</button><button id="b2" onclick="setCls('chair')">2 의자</button>
<button onclick="go(-1)">← 이전</button><button onclick="save(1)">저장·다음 (Enter)</button>
<span class="muted">클릭 선택 · <span class="k">Del</span> 지우기 · <span class="k">C</span> 클래스 · 드래그 새 상자 · 점선 = 겹친 상자</span>
<span id="count" class="muted"></span></header><div id="bar"><i id="fill"></i></div>
<div id="wrap"><canvas id="cv" width="1920" height="1080"></canvas></div>
<script>
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');let files=[],reviewed={},i=0,boxes=[],sel=-1,cls='person',img=new Image(),dirty=false,drag=null;
const color=c=>getComputedStyle(document.documentElement).getPropertyValue(c==='person'?'--person':'--chair');
function iou(a,b){const ix=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0])),iy=Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));const n=ix*iy;return n/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-n)}
function setCls(c){cls=c;document.getElementById('b1').className=c==='person'?'on':'';document.getElementById('b2').className=c==='chair'?'on':''}
async function init(){const r=await (await fetch('api/list')).json();files=r.files;reviewed=r.reviewed;i=files.findIndex(f=>!(f in reviewed));if(i<0)i=0;setCls('person');load()}
async function load(){const f=files[i];boxes=await (await fetch('api/labels/'+f)).json();sel=-1;dirty=false;img=new Image();img.onload=draw;img.src='img/'+f+'.jpg';info()}
function info(){const n=Object.keys(reviewed).length;document.getElementById('name').textContent=files[i];document.getElementById('pos').textContent=(i+1)+' / '+files.length;
document.getElementById('state').textContent=(files[i] in reviewed?'✓ 확인함':'아직 확인 안 함')+(dirty?' · 저장 안 됨':'');document.getElementById('fill').style.width=(100*n/files.length)+'%';
const p=boxes.filter(b=>b.cls==='person').length,c=boxes.length-p;document.getElementById('count').textContent=`이 사진: 사람 ${p} · 의자 ${c} | 확인 ${n}/${files.length}`}
function draw(){ctx.drawImage(img,0,0,1920,1080);boxes.forEach((b,k)=>{const dup=boxes.some((o,m)=>m!==k&&o.cls===b.cls&&iou(o.box,b.box)>=0.5);
ctx.setLineDash(dup?[14,8]:[]);ctx.lineWidth=k===sel?6:3;ctx.strokeStyle=k===sel?'#facc15':color(b.cls);const [x1,y1,x2,y2]=b.box;ctx.strokeRect(x1,y1,x2-x1,y2-y1);
ctx.setLineDash([]);ctx.fillStyle=ctx.strokeStyle;ctx.font='bold 28px system-ui';ctx.fillText((k+1)+' '+(b.cls==='person'?'사람':'의자'),x1+4,Math.max(28,y1-6))});
if(drag&&drag.moved){ctx.setLineDash([6,4]);ctx.lineWidth=3;ctx.strokeStyle=color(cls);ctx.strokeRect(drag.x,drag.y,drag.cx-drag.x,drag.cy-drag.y);ctx.setLineDash([])}info()}
function pt(e){const r=cv.getBoundingClientRect();return [(e.clientX-r.left)*1920/r.width,(e.clientY-r.top)*1080/r.height]}
cv.onmousedown=e=>{const [x,y]=pt(e);drag={x,y,cx:x,cy:y,moved:false}};
cv.onmousemove=e=>{if(!drag)return;const [x,y]=pt(e);drag.cx=x;drag.cy=y;if(Math.abs(x-drag.x)+Math.abs(y-drag.y)>8)drag.moved=true;draw()};
cv.onmouseup=e=>{if(!drag)return;const d=drag;drag=null;if(d.moved){const b=[Math.min(d.x,d.cx),Math.min(d.y,d.cy),Math.max(d.x,d.cx),Math.max(d.y,d.cy)];
if(b[2]-b[0]>4&&b[3]-b[1]>4){boxes.push({cls,box:b});sel=boxes.length-1;dirty=true}}else{
const hit=boxes.map((b,k)=>[k,b]).filter(([k,b])=>d.x>=b.box[0]&&d.x<=b.box[2]&&d.y>=b.box[1]&&d.y<=b.box[3]).sort((p,q)=>(p[1].box[2]-p[1].box[0])*(p[1].box[3]-p[1].box[1])-(q[1].box[2]-q[1].box[0])*(q[1].box[3]-q[1].box[1]));
sel=hit.length?hit[0][0]:-1}draw()};
async function save(next){await fetch('api/labels/'+files[i],{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(boxes)});reviewed[files[i]]=boxes.length;dirty=false;
if(next&&i<files.length-1){i++;load()}else{draw();if(next&&Object.keys(reviewed).length===files.length)alert('90장 모두 확인했어요. 채점을 돌리면 됩니다.')}}
function go(d){if(dirty&&!confirm('저장하지 않은 변경이 있어요. 버리고 이동할까요?'))return;const n=i+d;if(n>=0&&n<files.length){i=n;load()}}
document.onkeydown=e=>{if(e.key==='Delete'||e.key==='Backspace'){if(sel>=0){boxes.splice(sel,1);sel=-1;dirty=true;draw()}e.preventDefault()}
else if(e.key==='c'||e.key==='C'){if(sel>=0){boxes[sel].cls=boxes[sel].cls==='person'?'chair':'person';dirty=true;draw()}}
else if(e.key==='1')setCls('person');else if(e.key==='2')setCls('chair');
else if(e.key==='Enter'||e.key==='ArrowRight'){save(1);e.preventDefault()}else if(e.key==='ArrowLeft')go(-1);
else if(e.key==='s'||e.key==='S')save(0);else if(e.key==='Escape'){sel=-1;draw()}};
init();
</script></body></html>"""


def make_handler(dataset: Path):
    names = sorted(p.stem for p in (dataset / "images").glob("*.jpg"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body: bytes, kind: str, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _name(self, prefix: str) -> str | None:
            name = unquote(self.path[len(prefix):])
            return name if name in names else None

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(PAGE.encode(), "text/html; charset=utf-8")
            if self.path == "/api/list":
                body = {"files": names, "reviewed": load_reviewed(dataset)}
                return self._send(json.dumps(body).encode(), "application/json")
            if self.path.startswith("/api/labels/") and (name := self._name("/api/labels/")):
                boxes = [{"cls": c, "box": [round(v, 1) for v in b]}
                         for c, b in read_yolo(dataset / "labels" / f"{name}.txt", W, H)]
                return self._send(json.dumps(boxes).encode(), "application/json")
            if self.path.startswith("/img/") and self.path.endswith(".jpg"):
                name = unquote(self.path[len("/img/"):-len(".jpg")])
                if name in names:
                    return self._send((dataset / "images" / f"{name}.jpg").read_bytes(), "image/jpeg")
            self._send(b"not found", "text/plain", 404)

        def do_POST(self):
            if self.path.startswith("/api/labels/") and (name := self._name("/api/labels/")):
                boxes = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                save_labels(dataset, name, boxes)
                return self._send(b"{}", "application/json")
            self._send(b"not found", "text/plain", 404)

    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="라벨 세트 확인·수정 화면 (로컬)")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    dataset = args.dataset.expanduser()
    if not (dataset / "images").is_dir():
        raise SystemExit(f"라벨 세트가 아니에요: {dataset} (label_set.py make 결과 폴더)")
    print(f"라벨링 화면: http://localhost:{args.port}  (끝내기: Ctrl+C)")
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(dataset)).serve_forever()
