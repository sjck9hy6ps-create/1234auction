---
name: listing-cap-low-floor
description: "2026-10-05 — Naver listing paste parser, listing price used only as a cap, elevator-aware low-floor factors, minimum repair cost"
metadata:
  node_type: memory
  type: project
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-10-05T00:41:21.152Z
---

Built 2026-10-05 (BOARD_CALC_VER 25):

- **Naver 매물 붙여넣기** (임장 문답 in the 입찰후보 drawer): `parseNaverListings` + `summarizeNaverListings` + `applyNaverListings`.
  - Same-unit dedupe: same 동 + same floor (저/중/고 band if hidden) + price ranges overlap or within 5%. Units are kept separate if direction differs or one is 공실 and the other 세안고.
  - Stores `a.listingParse.items` and `a.listingHistory`. The history is meant for measuring the ask→deal gap later.
- **Listing cap rule** (`listingCapFor`):
  - Asks are used only as a cap and never raise the estimate.
  - Comparison set: same 평형 and floor band (1층 → 1–2층, else ±3). Exclude 세안고, include 급매.
  - Repair state must match the post-auction plan. Default is 올수리, because the age-based repair cost is budgeted. If 임장 cond is good/paper, compare with basic-state listings instead.
  - Need ≥3 comparable listings: use q25 if ≥8 listings, else the mean of the cheapest 2. Then subtract 3% for negotiation. The 3% is an assumption, not yet measured.
  - Fallback when fewer than 3 match the repair state: use other-state listings in the same band + the complex's (올수리 − 그 외) median gap.
  - Not applied when the paste is more than 60 days old.
- **Repair minimum:** 도배·장판 = 15만/평, minimum 200만 (`effRepairFee`). The user said repair can never be 0. 입주청소 is already a separate cost.
- **Low-floor factor:** the flat −5%/−3% was replaced by an elevator class (건축물대장 elevatorCnt if known, else maxF ≤5 / 6–10 / 11+) plus a shrinkage blend with this complex's 5-year all-size ppm ratio (k=10).
  - Tested on 1,037 resold 1–3층 cases: error 6.97% → 6.66%.
  - A 1km neighbor blend did not help.
- **절영 example:** the estimate looked high only because it was compared with unrenovated listings. After the repair-gap fallback the cap was 9,797 vs a trade-based value of 9,774.

**Why:** the user wants listing info reflected in the estimate, while being careful about asking prices vs real deals and about repair state.
**How to apply:** when elevator counts accumulate (the 건축물대장 daily quota was exhausted 2026-10-05), re-measure 6–10층 units without an elevator. When listingHistory and later trades accumulate, replace the 3% negotiation assumption. Related: [[first-deal-risk-priority]], [[bulk-auction-geocode-fix]].

**Per-unit 공시가격 test (2026-10-05) — rejected, not applied**
- The API mode `/api/get-official-price {addrJibun, dong, peers:1}` returns every unit of the same 동. It retries with a legacy PNU for 전남광주, 전북 and 강원.
- Test set: 2,577 dong-confirmed resales. Premium = unit price ÷ median of same-size units in the same 동.
- Correlation of premium with resale/estimate: −0.003 (line-only version: 0.013).
- Applying it made MAE worse (6.62% → 6.75–7.62%).
- Conclusion: the unit premium is already captured by the floor adjustment, or is swamped by condition and timing.
- The 공시가격-ratio idea for complexes with no trades can't be validated yet: only 36 base-path resales.
