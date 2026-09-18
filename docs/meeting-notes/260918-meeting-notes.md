# 2026-09-18 회의록

## 주요 주제

- 제작한 ppt 발표
- 데이터셋과 인프라 구성 방법
- 충돌 감지 로직은 ttc 알고리즘으로 할 것?
- 주요 요구 사항: 시스템 모델 처리 속도(전체 딜레이)와 정확도
- 유니티를 활용한 시스템 모델 개발 방법과 실제 환경과의 비교 방법
- unity 시뮬레이션 내용 넣자 → 객체 인식 내용 빼야할듯

## 다음 할 일

- 유니티에서 현장 시뮬레이션 환경 구축
- 논문 작성을 위한 정확도와 속도 확보
- 데이터 수집 및 전송 통신 방법 검토

---

[클로바노트공유]

회의록 w2
https://clovanote.naver.com/s/3cNdureXWW3trVJShbU8ZoS?t=1033

---

```mermaid
flowchart TD
    subgraph Unity ["유니티 시뮬레이터 (Sim)"]
        Cam["가상 CCTV"]
        GT["Ground Truth (위치/속도)"]
    end

    subgraph Real ["실제 환경 (Real)"]
        RCam["실제 CCTV"]
        Sensors["RTK-GPS / 라이다"]
    end

    subgraph Pipeline ["분석 파이프라인 (Python Server)"]
        Stream["RTSP / 비디오 스트림"]
        YOLO["YOLO + Tracker (BYTETracker)"]
        Homo["Homography 변환 (2D -> 3D)"]
        Kalman["칼만 필터 (위치/속도 추정)"]
        TTC["TTC 계산 및 충돌 예측"]
    end

    subgraph Output ["출력 및 평가"]
        Alert["위험 경보 (TTC < Threshold)"]
        Vis["3D 관제 모니터링"]
        Eval["성능 평가 (MAE / RMSE / Precision)"]
    end

    Cam -->|가상 영상| Stream
    RCam -->|실제 영상| Stream

    Stream --> YOLO
    YOLO -->|2D BBox| Homo
    Homo -->|현실 좌표| Kalman
    Kalman -->|추정 위치/속도| TTC

    TTC --> Alert
    Kalman --> Vis
    
    GT -->|정답 데이터| Eval
    Sensors -->|실측 데이터| Eval
    Kalman -->|추정 데이터| Eval
```

지금으로서는 실제 환경의 실측 데이터가 없네요.