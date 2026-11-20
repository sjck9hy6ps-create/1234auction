"""아파트 공시가격 → 앱용 자료(2026-11-19): apt-official-price.jsonl(건물별 면적별 요약)을 leader_follower_cache 'apt-official|N' 묶음으로 올림.
항목 키 = 시군구5|본번4|부번4, 값 = [[단지이름, [[전용㎡, 호수, 중앙값(만원)], …]], …](같은 번지에 법정동이 다른 단지가 있으면 여러 개). 앱(공시가격 필터·세금 계산)이 api/data-coverage?mode=aptOfficial로 받음."""
import os, sys, json, time, re, importlib.util, requests
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
# ---- 호별 공시가격(경매 물건 id → 만원) - 지분경매처럼 앱의 평형이 건물 전체와 다른 물건도 동·호로 찾음(2026-11-20, 사용자 지적: 건물에 대한 공시가격이라 평형으로 찾으면 안 됨)
def build_units():
    HERE = os.path.dirname(os.path.abspath(__file__))
    sp = importlib.util.spec_from_file_location("collector", os.path.join(HERE, "collect-apt-official-price.py")); C = importlib.util.module_from_spec(sp); sp.loader.exec_module(C)
    src = open(os.path.join(HERE, "api", "get-official-price.js"), encoding="utf-8").read()
    leg = json.loads(re.search(r"const LEGACY_SIGUNGU_PREFIX = (\{.*?\});", src).group(1))
    recs = {}
    for ln in open(SRC, encoding="utf-8"):
        r = json.loads(ln); recs[r["pnu"]] = r
    site = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
    auc = requests.get(site + "/api/auction", timeout=180).json()
    dg = lambda x: re.sub(r"\D", "", str(x or ""))
    jobs = []   # (경매 id, pnu, 동, 호)
    for a in auc:
        if a.get("propType") not in ("apt", "아파트") or not a.get("bCode") or not a.get("bunji") or not a.get("unitNo"): continue
        bb = C.bunji_to_bunji(a.get("bunji")); ho = dg(a.get("unitNo"))
        if not bb or not ho: continue
        dm = re.findall(r"(\d+)\s*동", str(a.get("aptDong") or "") + " " + str(a.get("addr") or "")); dong = dm[-1] if dm else ""
        jobs.append((a["id"], str(a["bCode"]) + "1" + bb[0] + bb[1], dong, ho))
    # 호 목록이 없는 건물(요약만 있거나 아직 안 받은 건물)은 지금 받아 옴: 쓴 적 있는 실제 조회 PNU(via) → 새 PNU → 옛 시군구 코드 순
    need = sorted({j[1] for j in jobs if not (recs.get(j[1]) or {}).get("units")})
    print(f"경매 아파트 {len(jobs):,}건 · 호 목록을 새로 받을 건물 {len(need):,}곳", flush=True)
    from concurrent.futures import ThreadPoolExecutor
    def get(pnu):
        cands = [(recs.get(pnu) or {}).get("via"), pnu, (leg.get(pnu[:5], "") + pnu[5:]) if pnu[:5] in leg else None]
        for cp in [c for c in cands if c]:
            _, res, ok = C.fetch_pnu((cp, True))
            if ok and res and res[1]: return pnu, [list(u) for u in res[1]]
        return pnu, None
    got = {}
    with ThreadPoolExecutor(max_workers=int(os.environ.get("THREADS", "8"))) as ex:
        for pnu, u in ex.map(get, need):
            if u: got[pnu] = u
    out = {}; rng = {}; miss = 0; why = {}
    def bad(k): why[k] = why.get(k, 0) + 1
    for aid, pnu, dong, ho in jobs:
        us = (recs.get(pnu) or {}).get("units") or got.get(pnu)
        if not us: miss += 1; bad("건물 호 목록 못 받음"); continue
        cand = [u for u in us if dg(u[2]) == ho and (not dong or dg(u[0]) == dong or not dg(u[0]))]
        if not cand: miss += 1; bad("그 호가 목록에 없음"); continue
        try: pr = sorted(float(u[4]) for u in cand)
        except Exception: miss += 1; bad("가격 읽기 실패"); continue
        # 동을 모르는데 같은 호가 여러 동에 있으면: 가격이 서로 3% 이내로 같을 때만 중앙값을 씀(면적으로 찾지 않음)
        if len(cand) > 1 and not dong and pr[-1] > pr[0] * 1.03:
            miss += 1; bad("동을 몰라 여러 동 가격이 다름"); rng[str(aid)] = [int(round(pr[0] / 10000)), int(round(pr[-1] / 10000)), len(pr)]; continue
        out[str(aid)] = int(round(pr[len(pr) // 2] / 10000))
    print("못 찾은 이유:", why, flush=True)
    print(f"호별 공시가격 {len(out):,}건 · 못 찾음 {miss:,}건", flush=True)
    build_units.ranges = rng
    return out
keys = sorted(items); CH = 5000; now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
print(f"건물 {n:,}곳 · 번지 키 {len(keys):,}개 · 기준연도 {yr}", flush=True)
rows = []
for i in range(0, len(keys), CH):
    rows.append({"id": f"apt-official|{i // CH}", "payload": {"items": {k: items[k] for k in keys[i:i + CH]}}, "fetched_at": now})
try:
    um = build_units(); rows.append({"id": "apt-official|units", "payload": {"items": um, "ranges": getattr(build_units, "ranges", {}), "at": now}, "fetched_at": now})
except Exception as e:
    print("호별 공시가격 만들기 실패(면적별 자료만 올림):", e, flush=True)
rows.append({"id": "apt-official|meta", "payload": {"at": now, "n": n, "keys": len(keys), "chunks": len(rows), "years": {str(k): v for k, v in yr.items()}}, "fetched_at": now})
for r in rows:
    body = json.dumps(r, ensure_ascii=False, allow_nan=False)
    for a in range(4):
        x = requests.post(f"{SU}/rest/v1/leader_follower_cache?on_conflict=id", headers=H, data=body.encode("utf-8"), timeout=120)
        if x.status_code < 300: break
        print("재시도", r["id"], x.status_code, x.text[:160], flush=True); time.sleep(3 * (a + 1))
    else: sys.exit(1)
    print(f"올림 {r['id']} {len(body)/1e3:.0f}KB", flush=True)
