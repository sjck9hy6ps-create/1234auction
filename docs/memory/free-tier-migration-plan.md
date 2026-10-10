---
name: free-tier-migration-plan
description: The user wants to drop Supabase Pro ($25/mo) after current data collection finishes; plan to move trade data to static files (Cloudflare Pages)
metadata:
  node_type: memory
  type: project
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-10-05T03:30:42.843Z
---

**Current state (2026-10-05):**
- Supabase is on the Pro Plan ($25/mo, cycle starts on the 19th). Disk is 8 GB provisioned, with 0 overage. Spend cap is on.
- Row counts: house_trades 4.6M, house_rent 7.3M, villa_trades 0.33M, villa_rent 0.35M, single_trades 0.14M, complex_coords 0.37M, building_info 0.15M.
- Everything else is free: GitHub Actions (repo is PUBLIC), Vercel Hobby, Upstash free, and the public APIs.
- Log ingestion is 4.4 GB and marked "UPCOMING" (possible future charge).

**User decision:** "현재 수집중인 작업들을 모두 완료한 후 무료화 할게" — they want to keep all current features, use every collected record as backup data, and pay nothing.

**Agreed plan:**
1. Export all trades and rents to compressed per-시군구/per-year files.
2. Host them on Cloudflare Pages (free, unlimited bandwidth, 20k files × 25 MB). The user must sign up and register the API token in GitHub secrets.
3. Switch get-house, the analysis scripts and the collectors to read and write files.
4. Run in parallel for 1–2 weeks and confirm the results match.
5. Downgrade Supabase to Free (500 MB) for the small tables only.

Do not delete anything before the backup has been verified, and ask the user before deleting.

**Wait for:** the 2023–2026 recollection (apt_dong etc.), the building-info backlog, and the user's go-ahead. Related: [[redis-limit-incident]], [[building-info-cache]].

**User timeline (2026-10-05):**
- 10/15 finish collection, 10/16 check, 10/17–18 migration.
- Downgrade before 10/19, when the billing cycle renews.
- Supabase must be under 500 MB before the downgrade, so the big trade tables must be deleted. Ask first.
- A daily 09:00 scheduled task "building-info-backlog-check" notifies the user when the 건축물대장 backlog is done.

**Pending before migration:**
- Re-run collect-history for 2023. It hit the MOLIT daily quota at 2023-04, so 2023-04–12 still lack apt_dong.
- Run analyze-bidcases with dong(棟)-based resale matching and report:
  - conf=dong vs floor
  - true resale rate
  - holding period
  - loss rate

**Free-plan risks to plan for:**
- building_info will outgrow 500 MB as nationwide collection continues → move it to files as well.
- Vercel Hobby is non-commercial only and already uses 12 of 12 functions.
- The repo must stay PUBLIC; private would mean a 2,000 min/month Actions limit.
- AI document parsing uses paid APIs: Anthropic in parse-auction.js and Gemini in parse-registry.js. The user should check those bills.
