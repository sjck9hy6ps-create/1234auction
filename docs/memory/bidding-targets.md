---
name: bidding-targets
description: Which segments the user bids on and the analysis lens used for each
metadata:
  type: project
---

Targets (2026-09-30): 전국 아파트 + 수도권(서울·경기·인천) 빌라. 지방 빌라 is out of scope.

Per-segment lens the user designed:
- 수도권 아파트: prices follow 대장아파트; watch 대장 + 차순위 complexes' past trend and judge future moves by the 대장 (user rarely bids on 대장 itself - too expensive). Implemented as leader-follower (getLeaderFollowerRank).
- 지방 아파트: only resident-preferred complexes trade → ranked as "인기순".
- 수도권 빌라: low volume makes samples thin; user tracks high-volume neighborhoods as "돈되는 지역".

User plans to upload 지방 아파트 낙찰사례 (and any other needed data) as backup data.

**How to apply:** Report accuracy split by 수도권 아파트 / 지방 아파트 / 수도권 빌라 and tie improvements to these lenses. See [[app-purpose-sale-price]].

Rank badges (2026-10-02, user: "모든 아파트 배지에 순위표기가 있어야 함"): fixed e50b2e0 + 9fd095e — (1) map rank info was replaced per region and regions auto-fetched once per session → A→B→A lost A's ranks; now merged. (2) dong grouping/keys by last token (화성 "동탄구 목동" vs "목동"). (3) complexes with <20 trades since 2017 now ranked (not leader-eligible); dongs with a single qualified complex mark it 대장 (leaderSource 'only'). LF_ALGO_VERSION=2 invalidates old caches. Coverage after: 강남 471/474, 화성 705/705, 칠곡 73/73, 순천 168/168, 춘천 143/143.
2026-10-03: removed per-dong LF_TOP_N=100 cap (now 5000, LF_ALGO_VERSION=3, cd1041b). Nationwide after warmups: apt complexes without coords 10/43,086; without rank/대장 15/36,768 (0.04%, mostly brand-new complexes or names with "&amp;").

2026-10-03 villa ranks: index.html now loads leaderFollower type=villa for 수도권 lawdCd 11/28/41 into a separate villaRankMap. It is shown on villa trade badges and on 입찰희망/낙찰사례 badges. Resolution goes by type: name, then same-type trade at the same 지번, then a rank-table key ending in the 지번 digits ("경진아트빌(1398-11)"). 입찰희망 bunji is often truncated, so fullBunjiFromAddr re-reads it from the address. warmup-leader-follower also warms 수도권 villas. Check on 안산 상록: villa trade badges 445/449 ranked, 입찰희망 26/35 (the rest have no trade history).
Later on 2026-10-03 the user decided: "빌라순위는 없애줘". The server's villa rank is 50% price level, which they find a hindrance. isVillaRankRegion now returns false, so villaRankMap stays empty. The villa warmup was removed. The apt/villa map separation stays, so villas never borrow apt ranks. Don't re-add villa ranks unless they ask for a volume-only criterion.

2026-10-03 rank fix:
- Discovered: households (K-apt) were never filled, so turnover was unused nationwide and leaders were mostly price_fallback. Ranks were effectively 평단가 50% + 거래량 50% for 수도권 and 지방 alike.
- User's 인기순 means (가) actually traded a lot/often (major weight) plus (나) people looking at it. View counts are unavailable, so (나) uses recent-1y vs prior trade growth as a proxy.
- data-coverage LF_ALGO_VERSION=4. Non-수도권 regions rank and pick leader by popularity: 0.4 turnover3y + 0.3 recent3y volume + 0.3 interest; without households, 0.7 volume + 0.3 interest. leaderSource='popularity', rankBasis field.
- sync-kapt fixed: it had been stuck since 9/28 on an empty 'test001' detail in 아산, with only 1,861 rows. Now: legacy code fallback (LEGACY_CODES_BY_NAME in the regenerated lawd_codes_py.py, which had been stale), cap 4000, restarted from idx 0 on 2026-10-03.
2026-10-03: the user's current focus is 지방 아파트. 수도권 아파트 is not a current interest. More 지방 낙찰사례 uploads are their preferred lever, so prioritize 지방 validation and features over 수도권.

2026-10-04 user goal: find the truly liquid ("거래가 잘 되는") popular 지방 complexes and focus auction bidding on them.
User hypothesis: 수도권 moves together (상향평균화), so complex-level change matters; 지방 is polarized, with only popular complexes trading.
Validating with analyze-liquidity.py (workflow analyze-liquidity.yml, weekly Mon 20:00 UTC). It writes the summary to cycle|__liquidity__ and per-region popular-complex lists to pop|<region>.

2026-10-04: User said current discussion/tuning baseline is **지방 아파트**; 빌라 formulas need separate rework later (villa thresholds 1.3 etc. are provisional). Final 손해 주의 approach: 예상매도가 display unchanged (실거래 기반), only bid lowered so margin holds at historically realized value (OVERSHOOT_SALE_FACTORS); shown as "손해 주의 여유: X 더 낮춤".
