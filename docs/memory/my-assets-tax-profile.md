---
name: my-assets-tax-profile
description: "User's real holdings/tax status (매매사업자, 엑슬루타워 오피스텔 재고, 중랑구 분양권 예정) and the 💼 내 자산 tab that feeds 주택수·종소세·종부세 into all bid calcs"
metadata:
  node_type: memory
  type: project
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-10-04T09:19:18.548Z
---

User (2026-10-04): 개인 부동산매매사업자. Holds 인천 미추홀구 용현동 659 엑슬루타워 오피스텔 105동 502호 (경매 낙찰, 재고자산). Will acquire a 서울 중랑구 아파트 분양권 (예정). User wants tax brackets to change automatically as holdings change.

Built 💼 내 자산 tab (public/index.html: loadMyAssets/myAssetSummary/myHouseRankFor/myIncomeBaseManwon/effLocalCheap; storage /api/auction?kind=myAssets, item 'profile' + one item per asset). Seeded with the two holdings (오피스텔 주거용=true conservatively, 시가표준액 unknown; 분양권 planned & counted). Result: 주택 수 2 → next auction = 3번째 → 비조정 취득세 8.4% unless 공시가 ≤1억 (지방 ≤2억; estimated as sale×0.69 when missing). Dealer 종소세 now marginal on top of the year's income.

**Why:** 취득세 중과 swings rec bid by ~2,300만 on a 4억 apt — must reflect real holdings.
**How to apply:** ask user to fill 오피스텔 시가표준액/주거용 여부 and 분양권 계약일; if they say 오피스텔 is 업무용 or ≤1억, count drops. Related: [[goal-realized-profit-niche]], [[app-purpose-sale-price]].

Update 2026-10-04 (user edited in the tab): 오피스텔 set 업무용 (residential=false), 중랑구 분양권 entry removed, includePlanned=false → 주택 수 0, next auction = 1st house (1.1%). Board now caches heavy per-row calc in IDB 'bidBoardCache:v1' (24h, boardBaseSig; bump BOARD_CALC_VER when board logic changes) and asset changes only re-run finalizeBidBoardRow (~0.1s). '매도 가정' sim is local-only (localStorage myAssetsSim).
