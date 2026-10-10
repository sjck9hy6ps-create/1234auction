---
name: data-health-autofix
description: Weekly data-health check auto-recollects gaps and writes public/data-health.json for an in-app banner
metadata:
  node_type: memory
  type: project
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-10-03T00:46:04.720Z
---

Since 2026-10-03, data-health.yml (Tue 00:00 UTC) does three things:
- Re-collects flagged region-months itself.
- Classifies regions where the MOLIT source has the same count as "notes" (a real decline, no banner).
- Commits public/data-health.json. index.html shows a top banner only when status is 'attention'.

**Why:** the user asked that data problems get fixed or surfaced without reading GitHub email.

**How to apply:** if the user says "데이터 점검 결과 확인해줘", read public/data-health.json or the latest data-health run log. The bot commits that JSON to main, so pull --rebase before pushing. First notes (2026-08): 구리 apartment sales, 장흥·함평·순창 rent; all were real declines.

2026-10-03 added check 3: Kakao-verifies every recent (region, 읍/면) pair; flags pairs Kakao can't find inside that region (would have caught 양평→여주). Compares only sigungu, not the 읍면 name, because MOLIT keeps old names (달성군 구지면 → Kakao 구지읍).
