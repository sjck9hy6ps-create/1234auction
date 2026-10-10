---
name: plain-language-ui
description: App UI text must be understandable by first-time users — no statistics jargon
metadata:
  node_type: memory
  type: feedback
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-10-02T12:17:28.011Z
---

Write all user-facing app text (index.html) in plain Korean that someone seeing the app for the first time understands. No 중앙오차/쏠림/편향/percentile/MAPE/홀드아웃/IQR/시점보정.

**Why:** 2026-10-02 the user asked to rewrite the error/bias displays "처음 이 앱을 접하는 사람도 이해할 수 있는 쉬운 표현으로".

**How to apply:** Patterns used (commits d5403da, 29fe5cf): 중앙오차 → "예상가와 실제 거래가 차이: 보통 ±X% (이 물건이면 약 ±N만)"; 쏠림 → "실제로는 예상보다 X% 비싸게/싸게 팔린 편 → 예상가가 조심스럽게(낮게) 잡혀 안전한 쪽"; 40th/50th percentile → "빨리 팔릴 가격 기준" / "딱 가운데 값"; 홀드아웃 → "모델이 배우지 않은 실제 거래로 시험"; stats labels 중간값/최소/최대 → 보통/가장 낮게/가장 높게. Convert % to won amounts for the current property when possible. Code comments can stay technical.
- 2026-10-04: '⚠️ 시세 과대 의심' renamed to '⚠️ 손해 주의' (user: not intuitive for first-time viewers). Prefer outcome words (손해 주의, 성공 구간) over mechanism words (과대, 오차).
