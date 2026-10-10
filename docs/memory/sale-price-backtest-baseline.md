---
name: sale-price-backtest-baseline
description: "2026-09-30 baseline accuracy of 예상매도가 on real auction units vs their actual resale, and the method used"
metadata:
  node_type: memory
  type: project
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-09-30T14:35:38.192Z
---

Step 1 (2026-09-30): scored the app's 예상매도가 on 낙찰사례 with resaleMatch, predicting as of 30 days before the auction date (trades filtered by date, 시점보정/findComplexMomentum disabled), run in the in-app browser against the live site via findSimilarComps + getCompEstValueHeadless.

Baseline (exact matches, suspicious resale<=bid removed):
- 수도권 빌라: prediction possible for only ~50% (151/292); median error 11.9%, mean 17.5%, ±10% 41%. With 3+ comps: median 10.5%; with 1-2 comps: median 17.5%, mean 30%.
- 수도권 아파트: n=20, median 6.1%, mean 17.7%.
- 지방 아파트: too few cases (user will upload 낙찰사례).
Causes found: the real cause of missing comps was villa_trades DB gaps (see Step 2), not coordinates — complex_coords has ~98% of villa buildings (client coordCache only looked partial mid-session). Missed cases concentrate in 안산 단원구/인천 서구.

**How to apply:** Any 예상매도가 change must be re-scored with this same as-of method and compared to these numbers. See [[app-purpose-sale-price]], [[bidding-targets]].

Step 2 (2026-09-30, not yet deployed at time of writing): added area-market fallback (calcAreaMarketEstimate/applyAreaFallback in index.html — comps<3 → same-dong/1km, same type, ±5y age, ±6평, 40th pct). Verified via the same as-of harness: 수도권 빌라 coverage 53%→86%, median 11.7%, mean 16.5%; 수도권 아파트 97%, median 4.8%, mean 5.6%. Also found villa_trades DB gaps (19 수도권 시군구 missing ~2024-10~2026-04; 인천 new gu need old codes 28110/28140/28260 split by dong; 화성시 41590 post-split months missing, codes unknown) — fixed backfill script to handle 인천 legacy codes; villa client load window raised to 3y in get-house.js.

Step 3 (2026-10-01): forward trend (calcForwardTrend in index.html, applied to 적정입찰가 & applyCompBid, apt only). Validated on 935k nationwide apt trades (get-house pull), 6 cutoffs 2025-07..2026-05, base = unit's last-3-month median ppp, target = next 4 months; fit on first 3 cutoffs, scored on last 3. 수도권: 0.5×max(0, 대장 3-month move, cap 10%) → median err 3.92%→3.48%, bias −2.4%→0 (β stable 0.31–0.58; followers track 대장 rises ~half, ignore falls). 지방: 인기 top-3 flow weak → 0.2× (3.77%→3.71%). Villas not validated/applied.

After backfill (2026-10-01, steps 2-3 deployed, villa 3y window live): 수도권 빌라 coverage 93% (97% excl. 인천 서구), median 12.3%, mean 16.4% — accuracy plateau ~12% for villas; coverage was the data bottleneck. 인천 서해구/검단구 still empty before 2025-11 (legacy-code backfill produced nothing — unresolved; ask user for the 1차 log lines for 28275). Warm get-house cache with ?skipRealtime=1 (it refreshes Redis).
Incheon (2026-10-01): MOLIT old codes 28110/28140/28260 return 0 rows for all months; history appears re-filed under new codes. Backfill script changed to new-code-first, legacy fallback. Note: GitHub "Re-run" reuses the original commit and inputs — new script changes need a fresh "Run workflow".
2026-10-01 later: 인천 4 new gu backfilled 2023-10..2026-09 via new codes (worked). Found & fixed (pushed, commit 1845f63) a bug in calcAreaMarketEstimate: same dong name in different 시군구 (인천 서구 연희동 vs 서울 서대문구 연희동) got mixed → 2-3x overestimates. Region now resolved: unique region → it; else coord votes within 3km; else nearest coord'd complex within 2km. Re-score: 수도권 빌라 93% / median 12.7% / mean 17.3%; 아파트 97% / 4.8% / 5.8%. Many backfilled villas lack coordCache coords until warmup-locations catches up (run #89 was cancelled at 6h).

Downturn check (2026-10-02, scripts/analyze-downturn.mjs via Actions, 2.07M apt trades 2020-06..2024-12, 14 quarterly cutoffs, even=fit/odd=score): declines do NOT persist 4 months (시군구 −5%+ → next 4m 수도권 0.0%, 지방 −0.3%); decline coefficients 0.02–0.11 → keep upside-only rule. In 하락장 the recent-price base under-predicts (bias +2.8% 수도권/+1.9% 지방) but error widens: 수도권 하락 5.5/보합 3.3/상승 4.8%, 지방 4.8/4.0/4.7%. Shipped (b2fd4e9): regime detection (시군구 3m move < −2% = 하락장) + per-regime error and min-margin warning in calcCompValuation. Weekly data health check (data-health.yml, Tue 09:00 KST) added 1bc0da1.

지방 auction-unit check (2026-10-02): user uploaded 1,031 전남·광주 apt 낙찰사례 (2026-01..10) via the app's 낙찰가 백테스트 일괄등록 (auctions store, isBacktest, ids 17909…). Resale = same dong+bunji, area ±1.5㎡, same floor, ≥14 days after bid → 269 found (234 after dropping resale ≤ bid×1.02); median resale gap 2.3 months. As-of (bid−30d) app estimate vs resale: 전체 median err 8.2% / mean 11.2% / bias −5.4% (prediction below resale); 광주 6.1%/−3.1%, 전남 시군 9.3%/−6.8%. Forward trend changed little (80 cases nonzero). Much wider than general-trade backtest (4.4%) — auction resales often post-renovation/fast flips.
Match-rate diagnosis (2026-10-02, user doubted 240/1000): MOLIT gives 읍·면 dongs as "완도읍 군내리" while auction addresses give "군내리" → exact dong compares failed (120 cases). Fixed with dongKey() (last token) in index.html (match index, matchesAuctionKey, scoreResaleCandidate, area estimate, forward trend) and scripts/match-bid-cases.mjs (commit 12eedc6). After fix: 322/1031 resales; error 7.9% median / bias −5.0%. Remaining unmatched mostly legit: time since auction (0–2mo 6%, 6–10mo 57% matched), complexes never traded in MOLIT (bulk-auctioned new/unsold complexes like 남교크레지움·수하임), unit not resold (same-size trades on other floors). Floor-only vs 동·호: causes possible false positives (other unit same floor), not misses.

2026-10-03 re-score (전남·광주 1,031 backtest auctions; 281 valid resales):
- Method: as-of (bid−30d) with window.Date overridden and oneYearAgo reset so the own-complex 3y logic runs.
- Old (e2a0701) vs new: median 7.9%→7.4%, share >20% off 15→13%, bias −4.8→−4.3%. On the 97 changed cases: 7.5→6.3%.

Bid-outcome simulation (solveAuctionBidFromRecord, dealer, default costs):
- Fixed 2,000만 margin: 19% win rate, 15% loss rate after winning, total net 4.42억.
- Winner's curse: won cases had estimates +3.3% too high (68% overestimated).
- Risk margin 500만 + est × (5% if own-complex ≥3 same-size trades, else 9%): 29% win rate, 16% loss rate, total net 7.54억. Shipped as a suggestion (ac35527, renderRiskMarginSuggestion), apt only.

2026-10-04 full-pipeline check (🎯입찰후보 board logic as-of bid−30d on 975 전남·광주 backtest apts; resale = same dong+bunji, ±1.5㎡, same floor, ≥14d, not 직거래; 276 valid):
- Harness pitfall: when rewinding trades, keep latest's identity fields (road_name etc.) from the full record — copying an older trade's road_name broke coordCache keys and dropped the subject complex.
- Bug fixed (3a3df91): own complex had no same floor-tier trade → fell to other complexes (광양 흥한에르가 1층 2.51억 vs 1.75억; 월산 우영 3.73억 vs 1.4억). Now borrows own-complex other tier ×0.915 (1층 = 91.5% of mid, 11k trades). 25 estimates changed, 5 with resale: 43.3%→5.9%.
- After: median err 7.4%, bias −3%, >20% off 34. By verdict: ✅ 4.3% / 🟡 6.2% / ❌ 10.3%. Winners' realized net: ✅ group loss 11%, ❌ group loss 17%.
- 추천 입찰가 = median 93.8% of actual winning bid; would win 29% of ✅/🟡. Won-with-resale: ✅ 8 (median +2,580만, 1 loss), 🟡 9 (1 loss). Small samples; 인기·위험 are current snapshots (slight leakage).

2026-10-04 유찰·생활권 checks (same 968/594 전남·광주 backtest):
- By 유찰 count: 신건 winners paid 106% of est sale, 40% lost; 1회 89%/17%; 2회+ 81%/5%. Popular(top20%)+1회: 91%, 26% lost, app rec bid wins 2%; popular+2회+: 74.5%, 2% lost (41 resales), app wins 14%, 0 losses → shipped as 🎯기회 / 경쟁 치열 / 신건 notes (ea9acda).
- 생활권 (1km radius, 2y trades) vs 법정동 tier: similar overall; both top → resale 64%, dong top but 생활권 mid → 42%, dong mid/생활권 top → 54%. 700m/1.5km similar. Shipped: popular = both top (4428a04).
