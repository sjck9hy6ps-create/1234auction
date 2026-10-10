---
name: market-cycle-analysis
description: analyze-cycle.py results (2026-10-03) — cycle position, forecast validation, follower-history signal — and the app integration
metadata:
  type: project
---

analyze-cycle.py runs weekly via analyze-cycle.yml (Tue 03:00 KST). It stores results in leader_follower_cache, ids 'cycle|__summary__' and 'cycle|<region>'. The app reads them through API mode=marketCycle.

What it computes:
- A two-way-FE (unit = complex+5㎡ bucket, by month) price index for 전국, 시도 and 시군구.
- Zigzag turning points: 5% for 시군구, 3% for 전국/시도.
- Phase: months in phase, % from peak/trough, momentum, volume.

First run (2017-09~2026-09, 4.16M trades):
- 전국: 2022-04 peak → 2023-01 trough → 상승기 44 months; +11% from the trough, −5.8% vs the peak.
- Cycle-position forecast (6/12m) did NOT beat naive zero (MAE 4.4% vs 2.7%), so it is shown as reference only, not applied to 예상매도가.

Follower history (complex quarterly series vs the app's leader):
- β = slope of 4-quarter changes; lag = argmax corr 0–4 quarters.
- Backtest over 11 cutoffs, n=114k: gap >3% → 56% beat 시군구 over the next year, avg +1.5%; negative gap −2.5%; corr 0.20; catch-up coef ≈0.2.
- Fix: the current gap now uses β clipped to 0–1.5. Only β 0.3–1.5 with corr ≥0.2 counts as a follower (isFollower), and only those get expectedCatchupPct. A strict validation (followerValidationStrict) runs as well.

UI (3660d0e):
- 📈 사이클 button and panel: 전국/시도/시군구 phase plus sparkline and a top follower list.
- Auction badge 대장 line prefers the history-based catch-up (buildFollowerHistLineHtml).

Note: the 건축물대장 hhldCnt is per-동 (표제부; 총괄표제부 is not fetched), so it is unsuitable as a complex households fallback.
Rerun on 2026-10-03 (popularity leaders for 지방, strict followers): strict set n=63.6k, gap>3% → 57.0% beat 시군구, +1.43% vs −2.56%, coef 0.227. UI caps the displayed catch-up at ±5% and warns when |gap| >30%. Example, 부산 해운대: 2021-11 peak → 2025-02 trough → 상승 19 months, −17.4% vs the peak.

User priors (2026-10-03):
- 수도권 and 지방 apartments can't share one standard.
- 수도권: 전세가율 + 대장그룹 선행.
- 지방: 전세가율 + 미분양.
- 거래량 applies to both.

Implemented analyze-cycle-forecast.py (manual workflow analyze-cycle-forecast.yml):
- Separate ridge models per segment, 6-month horizon, walk-forward over 2021–2025, feature-set ablation including a same-sample comparison.
- Results are stored at 'cycle|__forecast__'.
- Added API mode=unsoldHistory, which stitches the old 광주 (A.0006) and 전남 (A.0014) KOSIS codes before 2026-07.

First forecast run (2026-10-03, walk-forward 2021–2025, 6m horizon):
- house_rent jeonse starts only 2024-01, so 전세가율 could not be validated. Started a sequential backfill of 2023→2017 through collect-history-rent.yml (per-year runs).
- 수도권 base: direction 68.1% vs momentum 63%, but MAE 7.8% vs naive 6.2%. +대장그룹 선행: direction 68.9%, big-drop recall 49.5→53.6% (marginal).
- 지방 base: direction 60.6% vs momentum 64.9%; +미분양 (linear) no gain.
- Magnitude (MAE) is worse than naive everywhere, so use direction/warnings only.
- Next: once 전세 is backfilled, rerun analyze-cycle-forecast. Also test nonlinear unsold (extremes).

2026-10-04: 전세 backfill 2017–2023 done (5.73M rows; jeonse is now 3.84M from 2017-09, monthly_rent=0).

Walk-forward (ridge) with 전세:
- 수도권: direction ~68%, MAE still worse than naive.
- 지방: +전세 raised direction 60.6→63.6 and big-drop recall 29→39, still below momentum (65%) on direction.

Condition tables (pooled), showing the share of 6m drops >2%:
- Volume −30%: 수도권 52%, 지방 46%. Volume +40%: 4–10%.
- 수도권 전세가율 <50%: 33%, vs 70–80%: 18%.
- 지방 unsold ×2+: 35%, vs halved: 14%. 지방 jr_chg −3pp: 29%, vs +3pp: 18%.
- 대장그룹 선행 at region level: weak, non-monotonic.

Risk rule shipped (risk_flags):
- 높음 = volume −30%+ (or ≥2 weak flags). 높음: 수도권 51.9% drop share / avg −3.76%; 지방 42.6% / −2.08%. 낮음: 7% / 16%.
- 보통 (one weak flag) ≈ 낮음, so the UI shows 높음 / 낮음(참고 신호).
- The modal's risk margin adds |avg 높음 drop|% when the subject region is 높음.
- Current risk uses the second-to-last month (reporting lag).
