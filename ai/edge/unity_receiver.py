"""
Unity → 엣지 프레임 수신기

Unity가 같은 순간에 렌더링한 카메라 이미지들을 한 요청으로 보내면,
카메라별로 탐지·추적한 뒤 묶음 메시지를 만들어 서버로 보낸다.

────────────────────────────────────────────────────────────────
Unity → 엣지 요청 형식 (트랙 C와 맞출 약속)
  POST http://<엣지 IP>:8100/frames   (multipart/form-data)
    meta : JSON 문자열
           {"session_id": "unity-classroom-01", "frame": 1532, "ts": 1790774606123}
           frame = Unity 프레임 번호, ts = 렌더링 시각(epoch ms)
    cam1 : JPEG 파일   ← 파일 필드 이름이 곧 camera_id
    cam2 : JPEG 파일
  응답: {"ok": true, "pair_id": 1532, "counts": {"cam1": 3, "cam2": 2}, "ms": 41}

엣지 → 서버 메시지 (POST /detections, 트랙 B와 맞춘 묶음 형식)
  {"session_id": ..., "pair_id": 1532,
   "frames": [{"camera_id": "cam1", "frame_id": 1532, "ts": ..., "image_size": [w, h],
               "detections": [{"track_id", "cls", "conf", "bbox": [x1, y1, x2, y2]}]}, ...]}
────────────────────────────────────────────────────────────────

실행 (ai/ 폴더에서)
  python edge/unity_receiver.py --dry-run                           # 서버 없이 JSONL로 저장
  python edge/unity_receiver.py --server http://121.182.60.2:32130  # 서버로 전송
"""

import argparse
import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from detector import AI_DIR, Detector, draw
from server_client import ServerClient

app = FastAPI(title="edge-unity-receiver")
STATE: dict = {}                 # main()에서 설정: detectors, client, args, stats
DETECT_LOCK = threading.Lock()   # 추적기는 스레드 안전하지 않아서 한 번에 한 묶음씩 처리


def get_detector(camera_id: str) -> Detector:
    """카메라마다 추적기가 따로 있어야 track_id가 섞이지 않는다"""
    detectors = STATE["detectors"]
    if camera_id not in detectors:
        print(f"[{camera_id}] 탐지기 준비 중...")
        detectors[camera_id] = Detector(model=STATE["args"].model, conf=STATE["args"].conf)
    return detectors[camera_id]


def process_pair(meta: dict, images: dict) -> dict:
    with DETECT_LOCK:
        frames = []
        for camera_id in sorted(images):
            img = images[camera_id]
            dets = get_detector(camera_id)(img)
            h, w = img.shape[:2]
            frames.append({
                "camera_id": camera_id,
                "frame_id": meta["frame"],
                "ts": meta["ts"],
                "image_size": [w, h],
                "detections": dets,
            })
            vis_dir = STATE["vis_dir"]
            if vis_dir and meta["frame"] % STATE["args"].save_every == 0:
                cv2.imwrite(str(vis_dir / f"{meta['frame']:06d}_{camera_id}.jpg"), draw(img.copy(), dets))
    return {"session_id": meta["session_id"], "pair_id": meta["frame"], "frames": frames}


@app.get("/health")
def health():
    return {"ok": True, "cameras": sorted(STATE["detectors"]), **STATE["stats"]}


@app.post("/frames")
async def receive_frames(request: Request):
    t0 = time.perf_counter()
    form = await request.form()

    try:
        meta = json.loads(form["meta"])
        meta["frame"] = int(meta["frame"])
        meta["ts"] = int(meta["ts"])
        meta["session_id"] = str(meta["session_id"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(400, 'meta가 없거나 형식이 틀렸어요. 예: {"session_id": "...", "frame": 1, "ts": 1790774606123}')

    images = {}
    for key, value in form.multi_items():
        if key == "meta":
            continue
        data = await value.read()
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, f"{key} 이미지를 읽을 수 없어요 (JPEG/PNG만 가능)")
        images[key] = img
    if not images:
        raise HTTPException(400, "카메라 이미지가 없어요. 파일 필드 이름을 camera_id로 보내 주세요 (예: cam1, cam2)")

    message = await run_in_threadpool(process_pair, meta, images)
    STATE["client"].send(message)

    ms = round((time.perf_counter() - t0) * 1000)
    stats = STATE["stats"]
    stats["pairs"] += 1
    stats["total_ms"] += ms
    if stats["pairs"] % 50 == 0:
        c = STATE["client"].stats
        print(f"  묶음 {stats['pairs']}개 처리, 평균 {stats['total_ms'] / stats['pairs']:.0f}ms | "
              f"전송 {c['sent']} 실패 {c['failed']} 버림 {c['dropped']}")
    return {"ok": True, "pair_id": meta["frame"],
            "counts": {f["camera_id"]: len(f["detections"]) for f in message["frames"]}, "ms": ms}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0", help="Unity가 다른 PC면 0.0.0.0 유지")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--server", default=None, help="서버 주소, 예: http://121.182.60.2:32130")
    parser.add_argument("--dry-run", action="store_true", help="서버로 보내지 않고 JSONL로만 저장")
    parser.add_argument("--model", choices=["v2", "ensemble"], default="v2")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--out", default=str(AI_DIR / "runs" / "edge" / "unity"), help="결과 저장 폴더")
    parser.add_argument("--save-every", type=int, default=0, help="N프레임마다 박스 그린 이미지 저장 (0 = 저장 안 함)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    vis_dir = None
    if args.save_every:
        vis_dir = out_dir / "vis"
        vis_dir.mkdir(parents=True, exist_ok=True)

    client = ServerClient(args.server, out_dir, dry_run=args.dry_run)
    if not client.check_server():
        print(f"[경고] 서버 {args.server}/health 응답 없음 → 실패한 메시지는 {client.failed_path}에 저장돼요")

    STATE.update(detectors={}, client=client, args=args, vis_dir=vis_dir, stats={"pairs": 0, "total_ms": 0})
    mode = "dry-run (JSONL 저장)" if args.dry_run else f"서버 전송 → {args.server}"
    print(f"Unity 수신 대기: http://{args.host}:{args.port}/frames | {mode} | 저장: {out_dir}")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        client.close()
        print(f"종료 | {client.stats}")


if __name__ == "__main__":
    main()