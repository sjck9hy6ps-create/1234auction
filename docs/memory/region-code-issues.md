---
name: region-code-issues
description: LAWD region-code problems found 2026-10-01 (reorgs + shifted 경북/경남 labels) and what was fixed vs pending
metadata:
  node_type: memory
  type: project
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-10-01T13:56:42.857Z
---

Found 2026-10-01 by geocoding all 253 names (Kakao b_code) vs scripts/lawd-codes.mjs:
- MOLIT/Kakao only serve current codes; old codes return 0 rows (seen for 인천 28110/28140/28260, 광주 29xxx).
- FIXED (pushed 058cb7f, 3b7f69a): 광주·전남 → 12xxx '전남광주 X' in shared.mjs (apt+rent); 강원 42→51xxx, 전북 45→52xxx (names kept), 화성 41591/41593/41595/41597 added as '경기 화성시' in lawd-codes/shared/shared-villa. Before this, 강원/전북/화성 showed no data on the map (Kakao gives new codes) and 2026 apt trades weren't collected. 2026 apt sale+rent recollection runs started (36872397205, 36872400551).
- DONE 2026-10-02 (user ran sql/fix-gb-gn-region-labels.sql; verified 0 mismatches across 19 counties via get-house): 경북 47720–47930 and 경남 48750–48860 entries are shifted one county (e.g. code 47850 labelled '경북 예천군' is really 칠곡; 48820 '산청' is really 고성). DB rows carry the wrong county names; 경북 울릉(47940), 경남 함양(48870)/거창(48880)/합천(48890) never collected; label '경북 의성군'(47720) holds old 군위 data. Fix = correct lists + chain-rename region labels in house_trades/house_rent/villa_trades/single_trades/villa_rent (temp-prefix pattern like unify-region-names-migration.sql).
- DONE: apt sale+rent 2025 & 2026 recollected with new codes and chunked upserts (2,000 rows + retry; a whole-month upsert used to time out). Previously pending: apt rent for 광주/전남 2024–2025 sits under old names ('광주 X'/'전남 X', house_rent migration was reverted) → recollect rent 2025 (and 2024) with new codes.

See [[sale-price-backtest-baseline]], [[auction-app-workflow]].

After fixes, apt sale-price backtest coverage 지방 7,036→9,173 complexes (광주 297→1,247, 전북 222→747, 강원 145→664); 지방 median err 4.4%; 전북 8.1%→6.4%.

Missing map badges (2026-10-02): (1) cache-key mismatch — get-house turns null main_num into 0 so app key is "…||0|", while warmup-locations stored "…|||" → coords existed but app couldn't find them (안산 단원 villa 751/802, 서해 1,022/1,213). Fixed edfa2b9: prefetchCoordsFromDB also queries the blank-main_num key and splits lookups into 400-key chunks; warmup now writes app-style keys and treats legacy keys as cached. (2) newly backfilled/re-coded buildings (화성, 춘천) simply not geocoded yet → warmup run triggered. 화성 2026 MOLIT dongs now come as "동탄구 여울동" (gu prefix) and some bunji are blocks ("BL-7") — geocode falls back to name/road.
Also sub_num: DB/warmup stored sub_num 0 as "…|0" while app turns 0 into blank → apartments lost coords nationwide (32% of 42.9k complexes; 분당 183/194, 세종 191/213, 강남 134/466). Fixed 961985f: prefetch also queries main ''/sub '0' variants → nationwide 11.4% missing (rest = not yet geocoded, mostly relabeled 경북·경남 counties, warmup running).

2026-10-03 수도권 villa badge audit: 107,108 villa buildings, 133 without coords. Root cause for most: villa_trades 2025–2026 rows mislabeled (양평→'경기 여주시' 146, 연천→'경기 양주시' 47, 가평→'경기 포천시' 114, 안성 죽산면→'경기 이천시' 2) although code lists are correct; origin not found. Fix = sql/fix-gyeonggi-villa-region-labels.sql (user must run in Supabase), then warmup-locations + cache clear. Detection method: nationwide scan of 읍/면 first-token appearing under 2+ regions (legit dupes: 강원 남면/서면, 경남 대산면, 파주 군내면).
