# 보호구 판별 방식과 데이터셋

2026-11-05 결정 · 관련 이슈 [#71](https://github.com/geunchanKim/Comprehensive-Design-Project2-CCTV-Safety/issues/71)

안전조끼에 안전모를 추가해 함께 판별한다. 11월 계획의 안전조끼 단독 판별을 대체한다.

## 판별 방식

기존 사람 탐지·추적 모델은 바꾸지 않는다. 탐지된 사람 영역을 잘라 별도의 보호구 모델에 넣는다.

| 방식 | 내용 | 선택 |
| --- | --- | --- |
| A. 사람 영역 판별 | 사람 탐지 → 사람 영역 자르기 → 보호구 판별 | 선택 |
| B. 전체 화면 탐지 | 보호구 모델이 전체 화면에서 사람·보호구를 다시 찾고 사람과 짝짓기 | 제외 |

A를 고른 이유:

- 판별 결과가 잘라 낸 사람의 추적 ID에 바로 연결된다. B는 사람이 겹치면 보호구 상자를 엉뚱한 사람에게 붙일 수 있다.
- 전체 화면을 한 번 더 처리하지 않는다. v7 실측에서 엣지 탐지가 평균 85ms(검출 + 포즈), 처리 속도가 초당 10.7짝이라 목표(초당 10짝)까지 여유가 작다.
- 원본 해상도에서 잘라 작은 안전모도 크게 볼 수 있다.
- 논문에서 검증한 사람 탐지 모델과 위치 정확도를 그대로 유지한다.

착용 상태는 자주 바뀌지 않으므로 사람마다 몇 프레임에 한 번만 판별하는 방식을 검토한다. 포즈 관절점으로 머리·몸통 영역을 따로 자르는 방식도 2주 차에 비교한다.

## 클래스

| 항목 | 값 |
| --- | --- |
| 안전조끼 | 착용 / 미착용 |
| 안전모 | 착용 / 미착용 |

판단이 어려운 경우는 서버에서 `unknown`으로 처리한다. 대시보드 snapshot에는 `vest`와 같은 형식의 `helmet` 필드가 필요하다(3주 차).

## 데이터셋

| 용도 | 데이터셋 | 규모 | 라이선스 | 비고 |
| --- | --- | --- | --- | --- |
| 학습 | [Ultralytics Construction-PPE](https://docs.ultralytics.com/datasets/detect/construction-ppe) | 1,000장 (학습 800 / 검증 200) | CC BY 4.0 | Person·vest·no_vest·helmet·no_helmet 포함. 수집 사진과 생성 사진이 섞여 있음 |
| 평가 | [SH17](https://github.com/ahmadmughees/SH17dataset) | 8,099장 중 100명 선별 | CC BY-NC-SA 4.0 | Pexels 실제 사진. 조합별 25명씩 선별 |

- 학습 데이터는 YOLO 설정 `construction-ppe.yaml`로 내려받는다. 사람 상자를 잘라 그 안의 보호구 라벨로 사람별 정답을 만든다.
- 평가 100명은 조끼 O/X × 안전모 O/X 네 조합에서 25명씩 고른다. 라벨을 그대로 믿지 않고 100명 모두 눈으로 확인한다.
- 학습과 평가 데이터의 출처가 달라 평가 사진이 학습에 섞이지 않는다.
- 학습 데이터에 생성 사진이 있으므로 정확도는 실제 사진으로만 측정한다.

출처 표기

- Ultralytics team, *Ultralytics Construction-PPE Dataset*, 2026.
- SH17: A Dataset for Human Safety and Personal Protective Equipment Detection in Manufacturing Industry, arXiv:2407.04590, 2024.

## 촬영과 준비물

- 현재 교실 촬영 사진과 안전조끼·안전모는 없다.
- 공개 사진은 대부분 눈높이에서 촬영되었다. 위에서 보는 CCTV 각도 검증은 4주 차 교실 촬영에서 한다.
- 안전조끼 2벌, 안전모 2개를 4주 차 촬영 전까지 구매한다. 구매 일정은 11/8 주간 리뷰에서 정한다.

## v1 구현 (11/16, `feat/ppe-model-v1`)

| 단계 | 파일 | 내용 |
| --- | --- | --- |
| 데이터 | `ai/ppe/build_crops.py` | Construction-PPE의 사람 상자마다 영역을 넓혀(좌우 10%, 위 15%, 아래 5%) 원본 해상도로 자른다. 영역 안에 넓이 50% 이상 보이는 안전모·조끼 상자를 라벨로 옮긴다. 높이 48px 미만 사람은 뺀다 |
| 학습 | `ai/ppe/train_ppe.py` | 4종 탐지(`helmet`, `no_helmet`, `vest`, `no_vest`), COCO yolo11n에서 시작, 입력 320 |
| 상태 결정 | `ai/ppe/ppe_common.py` | 항목마다 conf 0.4 이상 중 가장 높은 상자로 `wearing`/`not_wearing`, 없으면 `unknown`. 옆 사람 것이 섞이지 않게 좌우 가장자리 10%는 버리고, 안전모는 위쪽 절반만 본다 |
| 평가 | `ai/ppe/eval_person.py` | 사람별 정답과 비교. 정답 unknown은 빼고, 모델 unknown은 틀린 것으로 센 정확도와 판별 못 한 비율을 따로 낸다 |

- 사람별 정답은 보호구 상자를 가장 많이 겹치는 사람 한 명에게만 준다. 씀·안 씀이 둘 다 붙거나 아무것도 없으면 unknown이다.
- 학습 라벨에는 영역 안에 보이는 옆 사람 보호구도 넣는다. 보이는데 라벨이 없으면 모델이 헷갈리기 때문이다.

| 사람 영역 | 학습 | 검증 |
| --- | --- | --- |
| 자른 사람 | 1,892 | 464 |
| 안전모 정답 씀 / 안 씀 / unknown | 1,209 / 570 / 113 | 275 / 168 / 21 |
| 조끼 정답 입음 / 안 입음 / unknown | 1,443 / 406 / 43 | 330 / 121 / 13 |

재현:

```bash
cd ai
python ppe/build_crops.py ~/datasets/construction-ppe ~/datasets/ppe-crops-v1
python ppe/train_ppe.py ~/datasets/ppe-crops-v1/data.yaml
python ppe/eval_person.py runs/ppe_v1/weights/best.pt ~/datasets/ppe-crops-v1 --out runs/ppe_v1/person_eval.json
```
