---
name: building-info-cache
description: 건축물대장 (building_info) cache bug found 2026-10-03, the fix, and the backlog status
metadata:
  type: project
---

Background: 건축물대장 comes from 건축HUB via api/get-building.js into the building_info table (180-day cache). It is separate from K-apt households (sync-kapt → kapt_complex_info).

Bug (2026-10-03):
- fetchBld returned httpStatus=429 (a number) for errMsg responses such as the daily quota "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR" (code 22).
- That passed the hadFetchError check (null-only), so errors were cached as "no building" for 180 days.
- 60,385 of 200,733 rows were empty, including 래미안첼리투스 and 이촌코오롱.

Fixes:
- Errors now return httpStatus null plus quotaExceeded, and are not cached.
- warmup-locations stops on quotaExceeded; its cap went 4000→7000/run.
- cleanup-building-empty.py deleted all 60,385 empty rows; 140,348 valid rows remain.

Backlog is about 89k buildings to re-fetch at ~7k/day. Suggested the user request 운영계정 (traffic increase) for 건축HUB on data.go.kr.

Idea pending: use 건축물대장 hhldCnt as a households fallback when K-apt is missing.
