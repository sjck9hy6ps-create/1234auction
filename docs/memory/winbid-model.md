---
name: winbid-model
description: 🎲 예상 낙찰가 model (2026-10-05) — validation numbers, how it's built/refreshed, app calibration, first board readout
metadata:
  type: project
---
User asked to see both "낙찰받을 수 있는 가격" and the margin-safe bid. It was validated first; the user then said "넣어줘".

**Validation**
- Target: winning bid ÷ the est at bid−30d. That est is the same-complex ±2㎡ 40th pct, 1y ≥3 trades, else 3y.
- Out-of-sample on 2025-07+ (n=6,781):
  - region average (the old app approach): 7.5%
  - GBM without 최저가: 6.5%
  - GBM with 최저가 and 유찰: 5.0%
  - deployable additive table: 5.6%
- Win rates on that sample: bidding the prediction wins 48%; +3% wins 64%; +5% wins 74%.
- 최저가 is used only for this prediction, never for 예상매도가.

**Build and storage**
- `winbid_model()` in analyze-bidcases.py runs weekly and writes `signal|__winbid__`.
- Factors: lb (log 최저가/est per 0.05), fails, region, tier, season, floor, size, own.
- resQ are the residual quantiles from a model fit without the last 12 months, scored on those 12 months.
- API: data-coverage mode=winbid. Fallback: public/winbid-model.json.

**App side**
- winbidBaseEst sets row.wbBase in computeBidBoardRow (BOARD_CALC_VER 27). winbidFor runs in finalize.
- App calibration: +0.018 log, because the client est runs higher. Checked on 770 2026 cases: error 5.6%, 49.7% win at the prediction.
- Display: the board 추천 입찰가 cell shows "예상 낙찰 X · 낙찰 N%". The drawer has a 🎲 box.

**First readout (2026-10-05)**
- Predicted winning bid ≈ 88.5% of 예상매도가.
- 109 of 120 apartment candidates have <35% win chance at 추천가. That matches the earlier finding that app bids win ~10–13%: a 1,000만 margin plus costs puts 추천가 around 80% of sale.

Related: [[app-purpose-sale-price]], [[first-deal-risk-priority]], [[sale-price-backtest-baseline]].

**Update 2026-10-08 (weights retuned):** walk-forward folds (2025H1, 2025H2, 2026) over 20.4k cases. Shrinkage k tuned: lb 10, fails 120, region 120, tier 5, season 300, floor 5, size 30, own 120. Added factors lab (감정가÷시세 bins, edges −0.2/−0.1/0/0.1/0.2/0.35), lbl (최저가 bin × lab) and labf (lab × fails). Result: median error 5.46 → 5.22%, ±10% 77.1 → 78.6%, bias −0.93% → ~0, win-at-prediction 45 → 50%. Tried and rejected: recency weighting, regional trailing "market mood", 준공연도/단지거래량/동거래량/면적 bins (≤0.1pt). GBM reaches 4.9% but can't run in-app. 감정가 is used only for 낙찰가 예측, not for 시세/예상매도가.
App check (826 지방 2026 cases): error 5.56%, bias +0.07%, 50.2% win at prediction, +5% actual 72.5% vs calc 72.3% → app offset +1.8% removed (client offset now 0; client prefers /winbid-model.json when the server model lacks `lab`).
