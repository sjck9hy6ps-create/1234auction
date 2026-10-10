---
name: resale-detection-limits
description: 2026-10-06/07 validation of how reliable "낙찰 후 되팔기" matching is (dong/floor/size, window, placebo) and the user's decision to treat it as a 6-month trace indicator
metadata:
  type: project
---
**Why it's limited:** house_trades has no 호수. A match is same complex + same 동 + same floor + 면적 ±2㎡ (house_trades.size is a floored integer — checked: ±2 vs exact barely changes results, so don't re-collect decimals). 동 number exists in trades only from 2023-01.

**Measurements (14,924 apt cases 2023+, ≥1y old):**
- Found 58.6% with unlimited window (동 confirmed 46.2%, floor-only 12.4%); 12-month window ≈ 41–42% (동 confirmed 41.3%).
- Area mismatch explains only 2.9% of unmatched (CSV typos / 공급면적 ~61 cases); the main gap is 동/호수.
- Floor-only match is real 74.7% of the time overall, but only 29% if within 1 month, 51% within 3 months, 64% within 6 months; the first candidate is the true trade only ~51%. By complex 동 count: 1 동 98–100%, 2: 86–97%, 3–5: 74–86%, 6–10: 63–79%, 11–20: 50–62%.
- Placebo (same 동·floor·size trade BEFORE the sale): post 6m 31.1% vs pre 7.0% → ~24%p real excess; ~77% of "확실" are real. 12m: 45.5% vs 13.8% → 70%. Cumulative resale (확실): 1m 1.7%, 2m 6.5%, 3m 12.3%, 6m 27.8%, 12m 41.3% of all winners; median hold of resold ≈ 4.4 months.
- min-days 14 vs 30/45/60 changes precision little → keep 14.

**User decision (2026-10-07):** exact matching is impossible; use 동+floor and a 6-month window as a "trace" indicator, not a precise record.
**Status:** NOT yet applied in app/analysis (3-tier 확실/유력/불확실 labels, 6-month rename "6개월 내 팔린 흔적", subtracting baseline, removing "과거 60~74%가 팔림" text). Region-priority 30% weight still uses the old 되판 비율.
Related: [[winbid-model]], [[app-purpose-sale-price]].
