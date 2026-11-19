"""아파트 공시가격 → 앱용 자료(2026-11-19): apt-official-price.jsonl(건물별 면적별 요약)을 leader_follower_cache 'apt-official|N' 묶음으로 올림.
항목 키 = 시군구5|본번4|부번4, 값 = [[단지이름, [[전용㎡, 호수, 중앙값(만원)], …]], …](같은 번지에 법정동이 다른 단지가 있으면 여러 개). 앱(공시가격 필터·세금 계산)이 api/data-coverage?mode=aptOfficial로 받음."""
import os, sys, json, time, requests
SU = os.environ["SUPABASE_URL"].strip().rstrip("/"); SK = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
H = {"apikey": SK, "Authorization": "Bearer " + SK, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
SRC = os.environ.get("SRC", "apt-official-price.jsonl")
items = {}; n = 0; yr = {}
for ln in open(SRC, encoding="utf-8"):
    r = json.loads(ln)
    if not r.get("n") or not r.get("areas"): continue
    pnu = r["pnu"]; key = pnu[:5] + "|" + pnu[11:15] + "|" + pnu[15:19]
    ar = [[float(a), v[0], int(round(v[1] / 10000))] for a, v in r["areas"].items() if v[1] > 0]
    if not ar: continue
    items.setdefault(key, []).append([r.get("danji", ""), ar]); n += 1; yr[r.get("year")] = yr.get(r.get("year"), 0) + 1
keys = sorted(items); CH = 5000; now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
print(f"건물 {n:,}곳 · 번지 키 {len(keys):,}개 · 기준연도 {yr}", flush=True)
rows = []
for i in range(0, len(keys), CH):
    rows.append({"id": f"apt-official|{i // CH}", "payload": {"items": {k: items[k] for k in keys[i:i + CH]}}, "fetched_at": now})
rows.append({"id": "apt-official|meta", "payload": {"at": now, "n": n, "keys": len(keys), "chunks": len(rows), "years": {str(k): v for k, v in yr.items()}}, "fetched_at": now})
for r in rows:
    body = json.dumps(r, ensure_ascii=False, allow_nan=False)
    for a in range(4):
        x = requests.post(f"{SU}/rest/v1/leader_follower_cache?on_conflict=id", headers=H, data=body.encode("utf-8"), timeout=120)
        if x.status_code < 300: break
        print("재시도", r["id"], x.status_code, x.text[:160], flush=True); time.sleep(3 * (a + 1))
    else: sys.exit(1)
    print(f"올림 {r['id']} {len(body)/1e3:.0f}KB", flush=True)
