---
name: user-app-usage-flow
description: How the user actually uses the auction app day to day (as understood 2026-10-04) — the core loop to optimize for
metadata:
  node_type: memory
  type: user
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-10-04T14:12:05.913Z
---

Core loop (지방 아파트 focus: 부산·전남광주·대전; 빌라 later):
1. 탱크옥션 검색결과 CSV → 📋 입찰희망 대량 등록 (and re-upload later to apply 유찰/매각 results).
2. 🎯 입찰후보 board: verdict/👍 입찰 추천 구간/⚠️ 손해 주의/🎯기회/🧭틈새, column sort, 예상매도가 + 최근 비슷한 층 거래, 추천 입찰가. Speed matters (must open instantly).
3. Detail: 입찰 판단 카드, 시세 그래프(1/3/10년), 건축물대장·공시가격; 권리관계는 매각물건명세서 직접 확인 후 인수금액을 입력해 입찰가에서 차감.
4. Bid rule: 최소 순수익 1,000만, 매매사업자 세금(종소세 누진, 85㎡ 초과 부가세), 수리비는 가능성으로 비용에 포함.
5. 💼 내 자산: holdings → 주택 수/세율; 매도 가정 시뮬레이션.
6. 낙찰사례 CSV 대량 업로드(과거 2022~) → 검증·백테스트 근거.
Style: wants evidence (backtests) before rule changes; rejects 감정가/최저가-based logic; plain Korean labels. Related: [[goal-realized-profit-niche]], [[my-assets-tax-profile]], [[plain-language-ui]].
