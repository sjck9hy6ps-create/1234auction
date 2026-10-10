---
name: court-reduction-rules
description: 유찰 저감률은 법원별로 다름(사용자는 수도권20/지방30으로 알고 있었음) - 실측 패턴과 앱 적용 방식
metadata:
  node_type: memory
  type: project
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-10-03T22:08:32.317Z
---

2026-10-04 실측(낙찰사례 2,447건 + 경매물건의 최저가÷감정가 계단):
- 매번 20%: 서울, 안양, 충주
- 매번 30%: 인천, 안산, 성남, 부천, 고양, 수원, 용인, 청주
- 첫 유찰 30% → 이후 20% (70→56→44.8): 광주·전남 전역(목포·순천·광양·여수·화순 등)
사용자는 "수도권 20%, 지방 30%"로 알고 있었음 → 앱은 데이터로 학습한 규칙을 쓰고, 자료 없을 때만 그 기본값 사용.

**Why:** 🎯입찰후보 보드가 입찰일 지난 물건을 "유찰 가정"으로 다음 최저가를 추정해 재판정하기 때문(public/index.html BID_REDUCTION_PATTERNS / bidReductionPatternFor).
**How to apply:** 저감률을 언급·수정할 때 이 표를 근거로; 70%는 두 규칙 공통이라 판별에 안 씀. 관련: [[bidding-targets]]
