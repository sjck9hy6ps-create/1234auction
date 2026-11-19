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
    g = d.groupby("pnu").agg(n=("deal_date", "size"), last=("deal_date", "max"), danji=("danji", lambda s: s.mode().iloc[0] if len(s.dropna()) else ""), sg=("sg", "first"), bun=("bun", "first"), ji=("ji", "first")).reset_index()
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


def fetch_pnu(job):
    pnu, keep_units = job
    for yr in (YEAR, YEAR - 1):
        units = []; seen = set(); ok = True
        for page in range(1, 40):
            f, total, ok = vget(pnu, yr, page)
            if not ok: return pnu, None, False
            for x in f:
                if str(x.get("stdrYear")) != str(yr): continue
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


def main():
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


main()
