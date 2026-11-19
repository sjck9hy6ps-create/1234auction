"""🏛️ 아파트 공시가격 수집 (2026-11-19, 사용자: 공시가격 필터용 - 모든 아파트 매매건에 대해, 우선순위 입찰후보 → 경매건 → 그 외)
흐름: 실거래(house_trades) 건물 → 좌표 캐시(complex_coords)의 법정동코드 → PNU(19자리) → VWorld 공동주택가격(앱 서버 프록시, 키는 서버에만 있음)
결과: 건물(PNU)별 면적별 공시가격 요약(개수·중앙값·최소·최대). 입찰후보·경매건은 호별 원자료(동·층·호·면적·가격)도 함께 보관.
이어하기: 이미 받은 PNU는 건너뜀. MAX_MIN분이 지나면 멈추고 올림(다시 돌리면 이어서). 기준연도는 올해, 자료가 없으면 작년.
"""
import os, json, time, sys, importlib.util, datetime, statistics
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, requests

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("avm", os.path.join(HERE, "train-avm.py"))
avm = importlib.util.module_from_spec(_s); _s.loader.exec_module(avm)

SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app"); SEC = os.environ["COLLECT_PROXY_SECRET"].strip()
SAMPLE = int(os.environ.get("SAMPLE", "0") or 0)          # 0 = 전부
MAX_MIN = float(os.environ.get("MAX_MIN", "300"))
THREADS = int(os.environ.get("THREADS", "8"))
ROWS = int(os.environ.get("ROWS", "400"))
YEAR = int(os.environ.get("YEAR") or datetime.date.today().year)
OUT = "apt-official-price.jsonl"


def bunji_to_bunji(b):
    parts = str(b or "").split("-")
    try: m = int(parts[0])
    except Exception: return None
    try: s = int(parts[1]) if len(parts) > 1 else 0
    except Exception: s = 0
    return str(m).zfill(4), str(s or 0).zfill(4)


def board_rows():
    """앱이 새벽에 미리 계산해 둔 입찰 물건(아파트): (시군구, 본번, 부번, 단지명, 임장후보 여부)"""
    out = []
    try:
        meta = requests.get(SITE + "/api/data-coverage?mode=boardCacheMeta", timeout=60).json()
        n = int(meta.get("count") or 0); ch = int(meta.get("goChunks") or 0)
        CH = 150; nch = (n + CH - 1) // CH
        for i in range(nch):
            for a in range(3):
                try:
                    j = requests.get(f"{SITE}/api/data-coverage?mode=boardCacheChunk&i={i}", timeout=90).json(); break
                except Exception: time.sleep(2)
            else: continue
            for v in (j.get("items") or {}).values():
                r = v.get("row") or {}
                if r.get("type") != "apt": continue
                bb = bunji_to_bunji(r.get("bunjiFull"))
                if not bb: continue
                out.append((str(r.get("lawd") or ""), bb[0], bb[1], str(r.get("name") or "").strip(), bool((r.get("visit") or {}).get("go"))))
        print(f"입찰 물건(아파트) {len(out):,}건 · 임장 후보 {sum(1 for x in out if x[4]):,}", flush=True)
    except Exception as e:
        print("입찰 물건 목록 읽기 실패:", e, flush=True)
    return out


def build_pnus():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,deal_date", extra_filter="")
    raw = raw.dropna(subset=["dong", "bunji"])
    print(f"아파트 거래 {len(raw):,}건", flush=True)
    mnum = pd.to_numeric(raw["main_num"], errors="coerce"); snum = pd.to_numeric(raw["sub_num"], errors="coerce")
    base = raw["dong"].fillna("").astype(str) + "|" + raw["danji"].fillna("").astype(str) + "|" + raw["bunji"].fillna("").astype(str) + "|" + raw["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd", order_col="id")
    cmap = {r.cache_key: (r.sigungu_cd, r.bjdong_cd) for r in cc.itertuples() if r.sigungu_cd and r.bjdong_cd}
    print(f"좌표 캐시(법정동코드 있음) {len(cmap):,}건", flush=True)
    cc2 = k_new.map(cmap)
    for alt in (k_leg, k_leg0):
        miss = cc2.isna(); cc2 = cc2.where(~miss, alt.map(cmap))
    raw["sg"] = cc2.map(lambda x: x[0] if isinstance(x, tuple) else None); raw["bj"] = cc2.map(lambda x: x[1] if isinstance(x, tuple) else None)
    bb = raw["bunji"].map(bunji_to_bunji)
    raw["bun"] = bb.map(lambda x: x[0] if x else None); raw["ji"] = bb.map(lambda x: x[1] if x else None)
    nocode = raw["sg"].isna() | raw["bj"].isna() | raw["bun"].isna()
    print(f"법정동코드 못 찾은 거래 {int(nocode.sum()):,}건 ({nocode.mean()*100:.1f}%)", flush=True)
    d = raw[~nocode].copy()
    d["pnu"] = d["sg"].astype(str) + d["bj"].astype(str) + "1" + d["bun"] + d["ji"]
    g = d.groupby("pnu").agg(n=("deal_date", "size"), last=("deal_date", "max"), danji=("danji", lambda s: s.mode().iloc[0] if len(s.dropna()) else ""), dong=("dong", "first"), sg=("sg", "first"), bun=("bun", "first"), ji=("ji", "first")).reset_index()
    names = d.groupby("pnu")["danji"].agg(lambda s: sorted(set(str(x).strip() for x in s.dropna()))[:6]).to_dict()
    g["names"] = g["pnu"].map(names)
    print(f"고유 건물(PNU) {len(g):,}곳", flush=True)
    return g, int(nocode.sum()), len(raw)


def vget(pnu, year, page):
    for k in range(4):
        try:
            r = requests.get(SITE + "/api/get-house", params={"action": "vworldProxy", "secret": SEC, "kind": "apt", "pnu": pnu, "stdrYear": str(year), "format": "json", "numOfRows": str(ROWS), "pageNo": str(page)}, timeout=60).json()
            j = json.loads(r.get("body", "{}"))
            f = None; total = None
            for v in j.values():
                if isinstance(v, dict) and "field" in v: f = v["field"]
                if isinstance(v, dict) and "totalCount" in v:
                    try: total = int(v["totalCount"])
                    except Exception: pass
            if f is None: return [], total, True
            return (f if isinstance(f, list) else [f]), total, True
        except Exception:
            time.sleep(2 * (k + 1))
    return None, None, False


INFO = {}   # pnu -> (응답의 법정동명 ldCodeNm, 단지명 aphusNm) - 코드가 맞는지 확인·기록용
def fetch_pnu(job):
    pnu, keep_units = job
    for yr in (YEAR, YEAR - 1):
        units = []; seen = set(); ok = True
        for page in range(1, 40):
            f, total, ok = vget(pnu, yr, page)
            if not ok: return pnu, None, False
            for x in f:
                if str(x.get("stdrYear")) != str(yr): continue
                if pnu not in INFO: INFO[pnu] = (x.get("ldCodeNm") or "", x.get("aphusNm") or "")
                key = (x.get("dongNm"), x.get("floorNm"), x.get("hoNm"), x.get("prvuseAr"), x.get("pblntfPc"))
                if key in seen: continue
                seen.add(key); units.append(key)
            if len(f) < ROWS: break
        if units: return pnu, (yr, units), True
    return pnu, (YEAR, []), True


def summarize(units):
    by = {}
    for dn, fl, ho, ar, pc in units:
        try: a = round(float(ar), 1); p = int(float(pc))
        except Exception: continue
        if p > 0: by.setdefault(a, []).append(p)
    return {str(a): [len(v), int(statistics.median(v)), min(v), max(v)] for a, v in sorted(by.items())}


def retry_empty():
    """자료가 없던 건물(시군구 코드가 바뀐 지역)을 옛 코드로 다시 조회 - 광주·전남(12xxx→29xxx/46xxx)·강원·전북은 get-official-price.js의 매핑, 인천 분구는 서구(28260)·중구(28110)·동구(28140) 후보로 시도"""
    import re
    src = open(os.path.join(HERE, "api", "get-official-price.js"), encoding="utf-8").read()
    leg = json.loads(re.search(r"const LEGACY_SIGUNGU_PREFIX = (\{.*?\});", src).group(1))
    inc = {"28275": ["28260"], "28290": ["28260"], "28125": ["28110", "28140"], "28155": ["28110", "28140"]}
    recs = [json.loads(ln) for ln in open(OUT, encoding="utf-8")]
    todo = [r for r in recs if r.get("n", 0) == 0 and not r.get("retried")]
    print(f"자료 없는 건물 {len(todo):,}곳 재시도(전체 {len(recs):,}곳)", flush=True)
    def alts(pnu):
        sg = pnu[:5]; c = []
        if sg in leg: c.append(leg[sg] + pnu[5:])
        for o in inc.get(sg, []): c.append(o + pnu[5:])
        if pnu[:10] == "2827510400": c.append("28260" + "10600" + pnu[10:])
        return c
    def work(r):
        for ap in alts(r["pnu"]):
            _, res, ok = fetch_pnu((ap, r.get("p", 3) <= 2))
            if ok and res and res[1]:
                yr, units = res
                nr = {"pnu": r["pnu"], "year": yr, "p": r.get("p", 3), "danji": r.get("danji", ""), "n": len(units), "areas": summarize(units), "via": ap}
                if nr["p"] <= 2: nr["units"] = [list(u) for u in units]
                return nr
        r2 = dict(r); r2["retried"] = True; return r2
    fixed = {}; t0 = time.time()
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        for i, nr in enumerate(ex.map(work, todo)):
            fixed[nr["pnu"]] = nr
            if (i + 1) % 500 == 0: print(f"  {i+1:,}/{len(todo):,} · 찾음 {sum(1 for v in fixed.values() if v.get('n'))} · {int(time.time()-t0)}초", flush=True)
    with open(OUT + ".new", "w", encoding="utf-8") as fo:
        for r in recs: fo.write(json.dumps(fixed.get(r["pnu"], r), ensure_ascii=False) + "\n")
    os.replace(OUT + ".new", OUT)
    print(f"끝: 재시도 {len(todo):,}곳 중 새로 찾음 {sum(1 for v in fixed.values() if v.get('n')):,}곳", flush=True)


def fix_gaps():
    """결측 보완(2026-11-20, 사용자: 공시가격이 없다는 건 말이 안 됨) - ① 경매 아파트 물건의 법정동코드(bCode)+지번으로 PNU를 만들어 수집 목록에 없던 건물 추가 ② 자료 없는 건물 중 인천 분구(서해·검단·영종·제물포구) 건물은 옛 법정동코드를
    동 이름으로 찾아(예전 좌표 캐시의 옛 코드) 조회하고 응답의 법정동명(ldCodeNm)에 그 동 이름이 있을 때만 채택. 광주·전남·강원·전북은 get-official-price.js의 시군구 매핑."""
    import re, collections
    src = open(os.path.join(HERE, "api", "get-official-price.js"), encoding="utf-8").read()
    leg = json.loads(re.search(r"const LEGACY_SIGUNGU_PREFIX = (\{.*?\});", src).group(1))
    recs = {}
    for ln in open(OUT, encoding="utf-8"):
        r = json.loads(ln); recs[r["pnu"]] = r
    g, _, _ = build_pnus(); dong_of = dict(zip(g["pnu"], g["dong"])); name_of = dict(zip(g["pnu"], g["danji"]))
    # 옛 인천 법정동코드: 동 이름 → (시군구, 법정동) (분구 전에 저장된 좌표 캐시)
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd", order_col="id")
    old = collections.defaultdict(collections.Counter)
    for r in cc.itertuples():
        if r.sigungu_cd in ("28110", "28140", "28260", "28200") and r.bjdong_cd: old[str(r.cache_key).split("|")[0].strip()][(r.sigungu_cd, r.bjdong_cd)] += 1
    old_map = {d: c.most_common(1)[0][0] for d, c in old.items()}
    print(f"옛 인천 법정동코드 {len(old_map)}개 동", flush=True)
    todo = []   # (pnu, 후보 PNU 목록, 검증할 동 이름, 우선순위, 단지명)
    # ② 자료 없는 건물
    for pnu, r in recs.items():
        if r.get("n"): continue
        cands = []; sg = pnu[:5]; dn = (dong_of.get(pnu) or "").strip()
        if sg in leg: cands.append((leg[sg] + pnu[5:], None))
        if dn in old_map and sg.startswith("28"): cands.append((old_map[dn][0] + old_map[dn][1] + pnu[10:], dn))
        if cands: todo.append((pnu, cands, r.get("p", 3), r.get("danji", "")))
    # ① 경매 물건에서 수집 목록에 없던 건물
    auc = requests.get(SITE + "/api/auction", timeout=120).json(); add = 0
    for a in auc:
        if a.get("propType") not in ("apt", "아파트") or not a.get("bCode") or not a.get("bunji"): continue
        bb = bunji_to_bunji(a.get("bunji"))
        if not bb: continue
        pnu = str(a["bCode"]) + "1" + bb[0] + bb[1]
        if pnu in recs or any(t[0] == pnu for t in todo[-50:]): continue
        sg = pnu[:5]; dn = str(a.get("dong") or "").strip(); cands = [(pnu, None)]
        if sg in leg: cands.append((leg[sg] + pnu[5:], None))
        if sg.startswith("28") and dn in old_map: cands.append((old_map[dn][0] + old_map[dn][1] + pnu[10:], dn))
        todo.append((pnu, cands, 2, str(a.get("name") or ""))); add += 1; recs.setdefault(pnu, None)
    todo = list({t[0]: t for t in todo}.values())
    print(f"보완 대상 {len(todo):,}곳(경매 물건에서 새로 추가 {add:,}곳)", flush=True)
    def work(t):
        pnu, cands, pr, nm = t
        for cp, dn in cands:
            _, res, ok = fetch_pnu((cp, pr <= 2))
            if not (ok and res and res[1]): continue
            ld = (INFO.get(cp) or ("", ""))[0]
            if dn and dn not in ld: continue   # 동 이름이 맞을 때만(옛 코드 추정이 틀린 경우 거름)
            yr, units = res
            rec = {"pnu": pnu, "year": yr, "p": pr, "danji": nm, "n": len(units), "areas": summarize(units), "via": cp, "ld": ld, "nm": (INFO.get(cp) or ("", ""))[1]}
            if pr <= 2: rec["units"] = [list(u) for u in units]
            return pnu, rec
        return pnu, None
    found = 0; t0 = time.time()
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        for i, (pnu, rec) in enumerate(ex.map(work, todo)):
            if rec: recs[pnu] = rec; found += 1
            elif recs.get(pnu) is None: recs.pop(pnu, None)
            if (i + 1) % 300 == 0: print(f"  {i+1:,}/{len(todo):,} · 찾음 {found:,} · {int(time.time()-t0)}초", flush=True)
    with open(OUT + ".new", "w", encoding="utf-8") as fo:
        for r in recs.values():
            if r: fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(OUT + ".new", OUT)
    left = sum(1 for r in recs.values() if r and not r.get("n"))
    print(f"끝: 보완 대상 {len(todo):,}곳 중 새로 찾음 {found:,}곳 · 아직 자료 없음 {left:,}곳", flush=True)


def main():
    if os.environ.get('FIX_GAPS') == '1': return fix_gaps()
    if os.environ.get('RETRY_EMPTY') == '1': return retry_empty()
    g, nocode_n, tot_n = build_pnus()
    bd = board_rows()
    # 우선순위: 1 = 입찰후보(임장 후보), 2 = 그 밖의 경매건, 3 = 그 외 전부(거래 많은 순)
    idx = {}
    for i, r in enumerate(g.itertuples()):
        idx.setdefault((r.bun, r.ji), []).append(i)
    pri = np.full(len(g), 3, dtype=int); hit = 0; miss = 0
    for lawd, bun, ji, name, go in bd:
        cand = idx.get((bun, ji), [])
        c2 = [i for i in cand if str(g.at[i, "sg"]) == lawd] or cand
        c3 = [i for i in c2 if name and (name in (g.at[i, "names"] or []))] or ([] if len(c2) != 1 else c2)
        if not c3: miss += 1; continue
        hit += 1
        for i in c3: pri[i] = min(pri[i], 1 if go else 2)
    g["pri"] = pri
    print(f"입찰 물건 건물 연결 {hit:,}건 · 못 찾음 {miss:,}건 · 우선순위 1: {int((pri==1).sum()):,} · 2: {int((pri==2).sum()):,} · 3: {int((pri==3).sum()):,}", flush=True)
    g = g.sort_values(["pri", "n"], ascending=[True, False]).reset_index(drop=True)
    done = set()
    if os.path.exists(OUT):
        for ln in open(OUT, encoding="utf-8"):
            try: done.add(json.loads(ln)["pnu"])
            except Exception: pass
    todo = [(r.pnu, int(r.pri) <= 2) for r in g.itertuples() if r.pnu not in done]
    if SAMPLE: todo = todo[:SAMPLE]
    print(f"받을 것 {len(todo):,}곳(이미 {len(done):,}곳)", flush=True)
    meta = {r.pnu: (int(r.pri), int(r.n), r.danji, str(r.sg)) for r in g.itertuples()}
    t0 = time.time(); n = got = fails = 0; units_n = 0
    with open(OUT, "a", encoding="utf-8") as fo, ThreadPoolExecutor(max_workers=THREADS) as ex:
        it = iter(todo)
        # 시간 제한: 작업을 조금씩 나눠 제출
        BATCH = THREADS * 25
        while True:
            chunk = [x for _, x in zip(range(BATCH), it)]
            if not chunk: break
            for pnu, res, ok in ex.map(fetch_pnu, chunk):
                n += 1
                if not ok: fails += 1; continue
                yr, units = res
                pr, cnt, dj, sg = meta[pnu]
                rec = {"pnu": pnu, "year": yr, "p": pr, "danji": dj, "n": len(units), "areas": summarize(units)}
                if pr <= 2: rec["units"] = [list(u) for u in units]
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); got += 1 if units else 0; units_n += len(units)
            fo.flush()
            if n % (BATCH * 2) < BATCH or True:
                el = time.time() - t0
                print(f"  {n:,}/{len(todo):,} 완료 · 자료 있음 {got:,} · 실패 {fails} · 호 {units_n:,} · {int(el)}초 · 초당 {n/max(el,1):.1f}곳", flush=True)
            if (time.time() - t0) / 60 > MAX_MIN:
                print("시간 제한에 도달: 여기까지 올리고 멈춤(다시 돌리면 이어서 받음)", flush=True); break
    print(f"끝: {n:,}건 · 자료 있음 {got:,} · 실패 {fails} · 법정동코드 없음 거래 {nocode_n:,}/{tot_n:,}", flush=True)


if __name__ == "__main__":
    main()
