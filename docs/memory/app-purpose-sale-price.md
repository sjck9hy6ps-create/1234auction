---
name: app-purpose-sale-price
description: "The app's core value is predicting the realistic resale price and future price direction — not bid-competition stats"
metadata:
  node_type: memory
  type: feedback
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-09-30T14:18:55.914Z
---

The bid price should come from "팔릴만한 가격(예상매도가) − 비용 − 목표마진", not from 최저가 × 회차 비율 / 낙찰가율 statistics. Improving 예상입찰가 accuracy means improving 예상매도가 accuracy and forecasting where prices are heading.

**Why:** 2026-09-30 I built a 최저가×회차 winning-bid predictor (backtest-better than 낙찰가율). User rejected it: "최저가의 몇%는 모든 경매인이 기본으로 아는 개념. 앱을 만드는 이유는 실제 팔릴만한 가격, 앞으로 가격이 어떻게 될지 알아내는 것." Change was reverted before deploy.

**How to apply:** Frame accuracy work around resale-price prediction (validate against 낙찰사례 with actual resaleMatch) and forward price trend. Don't propose competition/bid-rate modeling as the main lever. Confirm direction before large builds. See [[bidding-targets]].

2026-10-03 user rule (화정우미 case): 예상매도가 must track the subject's own complex's recent same-size trades. An estimate far from those "makes the app pointless". Fix in findSimilarComps:
- 3 or more own-complex same-size (±4평) trades in the last year → use those only, no other complexes.
- 1–2 such trades → widen to 3 years, still own complex only.
- Apartment top↔mid floor tiers may borrow from each other within the own complex. Basement and 1st floor stay separate.
Leave-one-out on 250 광주 trades: median abs error 8.7%→8.4%, share >20% off 59→55. Accuracy is still loose; a deeper method review is pending.
Follow-up the same day (옥천아파트, 진월동 363-4):
- findSimilarComps now also collects own-complex same-size trades from the last 3 years in one pass, and uses them even when the last year has none.
- Within own-complex lists it prefers exact area (±1평).
- getCompEstValueHeadless skips the dong-average area fallback when the type is apt and all comps are own-complex (record.sameComplex).
- AVM modal: an empty 단지명 now falls back to resolveOwnComplexName (same dong+지번) or buildingNameFromAddr. Without this it used region_fallback.
Leave-one-out on 400 trades: median error 6.6%→6.2%, within ±10% 66→68%.

2026-10-04: User explicitly declined adding small holding costs (5-month hold, 보유 중 관리비, 신탁대출 수수료, 6/1 보유세 auto, 기장료) — "모두 적용하면 낙찰받을 물건이 현저히 줄어" → keep cost model as is (interest 3 months default); treat 최소마진 1,000만 as the buffer. Don't re-propose unless backtests show losses traceable to them.
