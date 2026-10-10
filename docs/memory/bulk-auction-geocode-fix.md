---
name: bulk-auction-geocode-fix
description: "2026-10-05 대전 diagnosis — 343 bidCases had wrong-city coords (fixed), 🏢 same-building bulk auction rule, build year now saved from 건축물대장"
metadata:
  node_type: memory
  type: project
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-10-04T22:37:01.273Z
---

2026-10-05 findings (bt18 backtest, 지방 apt 9,142 cases, harness = bt17 code with id/addr/bulk fields):
- 343 bidCases geocoded to another city with the same dong name (e.g. 대전 대흥동 → 서울 마포 대흥동; 부산 206, 대전 57, 광주 44, 전남 32). 342 re-geocoded and saved (field geoFixedAt). pickBestGeocodeResult now prefers same-sido results. Live 입찰물건 had 0 such errors.
- Coordinate fix alone barely changed 대전. The real cause was **same-building bulk auctions** (전세사기/부도 임대, e.g. 석봉동 353-33 had 34 cases). If the same building had ≥10 auctions within −180/+60 days: resale/estimate 0.93 and loss 90%. If ≥5 and the thin-data path applied: 0.81 and loss 93%. 대전 bulk: 0.68, loss 100%.
- Applied as 🏢 대량 경매 (sameBuildingAuctionCount; apt only): it forces 손해 주의, removes sweet/기회 and blocks the aggressive bid. BOARD_CALC_VER 22. Current targets hit: 도나우270, 송정크레지움센트럴, 수하임, 럭키골든스위트, 대동레미안센트럴시티5, 파크블루11차.
- After excluding 손해 주의 and bulk: 대전 accuracy median 1.006, over-10% 9%.
- Build year: 101 of 201 CSV-registered apt targets lacked buildYear. useAprDay from the households 건축물대장 call was being discarded; it is now saved (buildYearSource '건축물대장').
- The 입찰후보 drawer looped forever when households could not be found (fixed via the householdsTried check).

**Why:** the user wants accurate, trustworthy amounts; these were data errors, not a reason to be more conservative.
**How to apply:** when a region looks bad, check coordinates and bulk buildings first. Still pending: a per-path reliability range shown in the drawer. Related: [[first-deal-risk-priority]], [[goal-realized-profit-niche]].

Update 2026-10-05 (later the same day):
- Another 157 bidCases had coordinates pointing to a different 구 in the same city (e.g. 광주 남구 봉선동 → 서구). They were re-geocoded and marked geoFixedAt '2026-10-05b'. None of the live 입찰물건 had this problem.
- New thin-data estimate rule (BOARD_CALC_VER 23), tested on 1,120 resold cases:
  - If comps > own: sale = min(own med12 or med36, most recent same-size trade).
  - Else: sale = comps^0.7 × own^0.3, where own = med12 or the most recent trade.
  - Median error 9.9% → 9.1%; improved in every year 2022–2025.
- Ideas that did not help:
  - Adjusting by the dong quarterly index made results worse.
  - Using same-complex price per ㎡ across other sizes did not help.
- Not fixed: complexes with 0 own trades in 3 years (86 cases) still miss by about 24%. These stay flagged 손해 주의.

## Resale-matching rework (2026-10-05, evening)

**What was wrong:**
- Floor-only matching was mostly coincidence. Within 12 months, a same-floor trade happened in 56% of cases, but a ±2-floor control also traded in 43%.
- MOLIT trades include 동(棟) only for deals from **2023-01** onward. All 2022 months were 0%.
- house_trades did not store aptDong, cdealType (해제), rgstDate or buyer/seller.
- The bidCase CSV parser dropped the "101동" from the address.

**What was fixed:**
- Collectors now store apt_dong, rgst_date, cdeal_type, buyer_gbn and sler_gbn. The user added these columns to house_trades.
- MOLIT paging for >1000 rows per month was added.
- 2024–2026 were recollected. **2023-04..12 is still pending because of the quota.**
- get-house drops cancelled trades and now passes the 직거래 flag. It had never been passed before, so the app's 직거래 exclusion was a no-op.
- analyze-bidcases matching now uses the same 동 + same floor (conf=dong or floor). It includes 직거래 resales and skips trades below 70% of the winning bid.
- Fixed a bug where a NaN dong was treated as truthy.
- Backfilled `aptDong` on 7,567 bidCases from the CSVs in ~/Downloads (탱크옥션*.csv).

**Results** (2023-01..2025-03 지방 apt with known 동, n=3,758):
- 44.8% sold, confirmed by 동 (32% within 12 months).
- 16.4% matched by floor only.
- 38.8% show no sale, i.e. likely 실거주 or still held.
- Hold time: median 6.9 months (IQR 3.6–13.9).
- Resale ÷ winning bid: median 1.11; 36% sold below 1.08× the winning bid.

**Next:**
- Recollect 2023, then rerun the analysis.
- Run a control test (same 동, other floor).
- Redo the grade backtests and count "unsold" separately.
