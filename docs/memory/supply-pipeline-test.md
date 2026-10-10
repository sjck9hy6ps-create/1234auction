---
name: supply-pipeline-test
description: 2026-10-05 입주 예정 물량(청약홈) vs 낙찰 후 되팔기 검증 — signal weak/inconsistent, not applied
metadata:
  type: project
---
Script `analyze-supply.py` + workflow analyze-supply.yml (monthly, 3일). Source: 청약홈 APT 공고 via /api/data-coverage?mode=applyhomeRaw&src=apt (2,879 공고, 입주 2020-03~2032-03, 296 시군구). Saves `signal|__supply__` (byRegion months/complexes/trades1y + validation).

Result (12,314 dong-known apt cases, supply in 시군구 ÷ 1-yr trades):
- Buckets by relative supply: no monotonic pattern (sold-in-12mo 20/26/13/17/18%).
- 2024–25 same-region: 12-month window "평소보다 많을 때" sold 15.6% vs 23.8%, resale÷bid 1.108 vs 1.126; but 6-month window reverses (29.3% vs 22.8%).
- Conclusion: inconsistent, at most ~1% price effect → not applied to estimate/grades.

**Why:** user wants only validated reliability gains ([[first-deal-risk-priority]]).
**How to apply:** don't re-propose 입주 물량 as a rule; data is stored if the user wants it as reference info. Missing: 비청약 공급(임대·조합원분).
