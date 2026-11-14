"""🏢 건축물대장 세대수 보완 수집(2026-11-14, 사용자: 아파트 회전율 세대수 연결을 최대한 높임).
건축물대장(building_info)에 '동 하나 값'(hhldCnt)만 있고 단지 전체 세대수(총괄표제부·동 합계, hhVer 2)가 없는 아파트 건물을 최근 12개월 거래가 많은 순서로 다시 조회해 채움.
조회는 앱 서버(/api/get-building?force=1)를 거쳐 건축HUB로 나감(저장은 서버가 함). 일일 한도 보호를 위해 CAP(기본 3000)건까지만, 한도 초과가 나오면 바로 멈춤."""
import os, sys, json, time, importlib.util, concurrent.futures as cf
from collections import Counter
from datetime import datetime, timezone, timedelta
import pandas as pd, requests
HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("loc", os.path.join(HERE, "compute-location-index.py")); loc = importlib.util.module_from_spec(_s); _s.loader.exec_module(loc)
avm = loc.avm
CAP = int(os.environ.get("CAP", "3000")); BASE = os.environ.get("APP_BASE", "https://1234auction.vercel.app"); THREADS = 4
cut = int((datetime.now(timezone.utc).date() - timedelta(days=365)).strftime("%Y%m%d"))
tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,deal_date,cdeal_type,dealing_type", extra_filter=f"&deal_date=gte.{cut}")
tr = tr[(tr["cdeal_type"].fillna("").astype(str).str.strip() == "") & (tr["dealing_type"].fillna("") != "직거래")].copy()
cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd", order_col="id")
hmap = {r.cache_key: (r.sigungu_cd, r.bjdong_cd) for r in cc.itertuples() if r.sigungu_cd and r.bjdong_cd}
bi = avm.fetch_all_rows("building_info", cols="id,sigungu_cd,bjdong_cd,bun,ji,bld_nm,hv:title_json->>hhVer,hc:title_json->>hhldCnt", order_col="id")
need = {}
for r in bi.itertuples():
    try: hc = int(float(r.hc))
    except Exception: hc = 0
    if hc > 0 and r.hv != "2": need.setdefault((r.sigungu_cd, r.bjdong_cd, str(r.bun), str(r.ji)), []).append(str(r.bld_nm or ""))
print(f"세대수 보완이 필요한 대장 건물(동 하나 값만 있음) {len(need):,}곳")
sg = loc.lookup(tr, hmap)
bp = tr["bunji"].fillna("").astype(str).str.split("-", n=1, expand=True)
bun = bp[0].str.replace(r"\D", "", regex=True).str.zfill(4)
ji = (bp[1] if bp.shape[1] > 1 else pd.Series("0", index=tr.index)).fillna("0").str.replace(r"\D", "", regex=True).replace("", "0").str.zfill(4)
cnt = Counter()
for a, b, c in zip(sg, bun, ji):
    if isinstance(a, tuple):
        k = (a[0], a[1], b, c)
        if k in need: cnt[k] += 1
order = [k for k, _ in cnt.most_common()]
print(f"그중 최근 12개월 아파트 거래가 있는 건물 {len(order):,}곳(거래 {sum(cnt.values()):,}건) → 이번에 {min(CAP, len(order)):,}곳 조회")
todo = order[:CAP]
done = ok = fail = 0; quota = False
def one(k):
    names = [n for n in need[k] if "__d" not in n] or [""]
    r = requests.get(BASE + "/api/get-building", params={"sigunguCd": k[0], "bjdongCd": k[1], "bun": k[2], "ji": k[3], "bldNm": names[0], "force": "1"}, timeout=60)
    j = r.json() if r.ok else {}
    return j
with cf.ThreadPoolExecutor(THREADS) as ex:
    futs = {}
    it = iter(todo)
    for k in it:
        if quota: break
        futs[ex.submit(one, k)] = k
        if len(futs) >= THREADS * 4:
            for f in cf.as_completed(list(futs)):
                try:
                    j = f.result(); done += 1
                    if j.get("quotaExceeded"): quota = True
                    elif (j.get("title") or {}).get("hhVer") == 2: ok += 1
                    else: fail += 1
                except Exception: done += 1; fail += 1
                futs.pop(f)
            if done % 200 < THREADS * 4: print(f"  진행 {done:,}/{len(todo):,} (세대수 채움 {ok:,} · 못 채움 {fail:,})", flush=True)
    for f in cf.as_completed(list(futs)):
        try:
            j = f.result(); done += 1
            if j.get("quotaExceeded"): quota = True
            elif (j.get("title") or {}).get("hhVer") == 2: ok += 1
            else: fail += 1
        except Exception: done += 1; fail += 1
print(f"끝: 조회 {done:,}건 · 세대수 채움 {ok:,} · 못 채움 {fail:,}" + (" · 건축HUB 일일 한도 초과로 중단" if quota else ""))
