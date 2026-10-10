---
name: villa-market-logic
description: User's villa (연립다세대) price-discovery approach differs from apartments — which app tools exist for it and must be kept
metadata:
  type: user
---
User (2026-10-05): apartments and villas need completely different price discovery.

For villas the user:
- finds dongs with many 신고가 (⭐ 신고가 지역 tab, which supports villas);
- infers building condition from 평단가 (등급 1~7 = 평단가 rank, computed within the same 연식단계 group, plus the 상세 필터 등급);
- looks for which 평형대 of villa is in demand in that dong.

The user likes 배지 간단/자세히.

Gap: "🔍 평형별 인기 단지 찾기" (in 경매물건 등록) is built on apartment popularity (`marketCycle.popular`, from house_trades), so it doesn't cover villa 평형 demand. A villa version was offered; user deferred all villa logic work (2026-10-05: "빌라 로직은 추후, 지금은 아파트 로직·UI만").

**How to apply:** never remove these as "unused". Judge villa features by villa logic, not the apartment same-complex model. Related: [[ui-cleanup-2026-10-05]], [[bidding-targets]].
