"""건축물대장 캐시(building_info) 진단 - 읽기 전용(2026-10). 시군구별 '조회했지만 정보 없음' 비율과 예시를 출력."""
import os, json, collections, requests
URL = os.environ["SUPABASE_URL"].rstrip("/"); KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
rows, last = [], 0
while True:
    r = requests.get(f"{URL}/rest/v1/building_info?select=id,sigungu_cd,bjdong_cd,bun,ji,bld_nm,title_json&id=gt.{last}&order=id.asc&limit=1000", headers=H, timeout=120)
    r.raise_for_status(); b = r.json()
    if not b: break
    for x in b: rows.append((x["sigungu_cd"], x["bjdong_cd"], x["bun"], x["ji"], x["bld_nm"], x["title_json"] is None))
    last = b[-1]["id"]
    if len(b) < 1000: break
tot = collections.Counter(r[0] for r in rows); nul = collections.Counter(r[0] for r in rows if r[5])
print("전체", len(rows), "정보없음", sum(nul.values()))
pref = collections.Counter(); pnul = collections.Counter()
for k, v in tot.items(): pref[k[:2]] += v; pnul[k[:2]] += nul[k]
print("시도코드별 정보없음:", {k: f"{pnul[k]}/{pref[k]}" for k in sorted(pref)})
worst = sorted(tot, key=lambda k: -(nul[k] / tot[k]) if tot[k] >= 50 else 0)[:15]
print("정보없음 비율 높은 시군구:", [(k, nul[k], tot[k]) for k in worst])
ex = [r for r in rows if r[5]][:15]
print("예시:", ex)
