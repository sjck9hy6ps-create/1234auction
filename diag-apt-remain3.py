"""'같은 본번에 다른 건물만 있음' 사건 시험(읽기만 함): ① 같은 본번 모든 건물에서 동·호·층이 일치하는 호가 있는지 ② 개별주택가격 API로 조회되는지."""
import importlib.util, json, os, re, requests, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("collector", os.path.join(HERE, "collect-apt-official-price.py")); C = importlib.util.module_from_spec(sp); sp.loader.exec_module(C)
src = open(os.path.join(HERE, "api", "get-official-price.js"), encoding="utf-8").read()
leg = json.loads(re.search(r"const LEGACY_SIGUNGU_PREFIX = (\{.*?\});", src).group(1))
site = os.environ.get("SITE_URL", "https://1234auction.vercel.app"); SEC = os.environ["COLLECT_PROXY_SECRET"].strip()
auc = requests.get(site + "/api/auction", timeout=180).json()
units = requests.get(site + "/api/data-coverage?mode=aptOfficial&i=units", timeout=60).json()
items, rng = units["items"], units.get("ranges", {})
dg = lambda x: re.sub(r"\D", "", str(x or ""))
def ho_of(s0):
    s0 = str(s0 or ""); d0 = None
    m = re.search(r"(\d+)\s*동", s0)
    if m: d0 = m.group(1)
    s0 = re.sub(r"\d+\s*(동|층|단지)", "", s0)
    if "-" in s0: a0, b0 = s0.rsplit("-", 1); d0 = d0 or dg(a0); s0 = b0
    return dg(s0).lstrip("0"), (d0 or "").lstrip("0")
cases = []
for a in auc:
    if a.get("propType") not in ("apt", "아파트") or str(a["id"]) in items or str(a["id"]) in rng: continue
    bb = C.bunji_to_bunji(a.get("bunji"))
    if not (a.get("bCode") and bb and a.get("unitNo")): continue
    cases.append((a, str(a["bCode"]) + "1" + bb[0] + bb[1]))
print("미연결 사건", len(cases), flush=True)
cache = {}
def rows15(pre):
    if pre not in cache:
        out = []
        for pg in range(1, 40):
            f, t, ok = C.vget(pre, C.YEAR, pg)
            out += f or []
            if not f or len(f) < C.ROWS: break
        cache[pre] = out
    return cache[pre]
def house(pnu):
    try:
        r = requests.get(site + "/api/get-house", params={"action": "vworldProxy", "secret": SEC, "kind": "house", "pnu": pnu, "stdrYear": str(C.YEAR), "format": "json", "numOfRows": "2", "pageNo": "1"}, timeout=60).json(); return str(r)[:300]
    except Exception as e: return "err " + str(e)[:80]
res = []; cnt = collections.Counter()
for a, pnu in cases:
    sg = pnu[:5]; pre = (leg.get(sg, sg) + pnu[5:])[:15]
    rows = rows15(pre) or (rows15(pnu[:15]) if pre != pnu[:15] else [])
    ho = dg(a["unitNo"]).lstrip("0"); fl = str(a.get("floor") or "").strip()
    m = re.findall(r"(\d+)\s*동", str(a.get("aptDong") or "") + " " + str(a.get("addr") or "")); dong = (m[-1] if m else "").lstrip("0")
    if not rows: cnt["본번 0건"] += 1; continue
    hit = []
    for x in rows:
        h, d = ho_of(x.get("hoNm")); dd = d or (re.match(r"\D*(\d+)", str(x.get("dongNm") or "")) or [None, ""])[1].lstrip("0")
        if h == ho and (not dong or not dd or dd == dong): hit.append((x.get("aphusNm"), x.get("dongNm"), x.get("floorNm"), x.get("hoNm"), x.get("prvuseAr"), x.get("pblntfPc")))
    names = sorted({k[0] for k in hit})
    cnt["호 일치 있음" if hit else "일치 없음"] += 1
    res.append({"id": a["id"], "addr": a.get("addr"), "name": a.get("name"), "unit": a.get("unitNo"), "floor": fl, "dong": dong, "n_rows": len(rows), "bldgs": sorted({x.get("aphusNm") for x in rows})[:8], "hit": hit[:5], "hit_names": names})
print(cnt, flush=True)
for r in res: print(json.dumps(r, ensure_ascii=False)[:520], flush=True)
print("== 개별주택가격 API(kind=house) 시험:", house("2635010300114050033"), flush=True)
json.dump(res, open("diag-remain3.json", "w"), ensure_ascii=False)
