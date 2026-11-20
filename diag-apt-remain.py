"""남은 공시가격 결측 사건을 하나씩 조회해 원인 판별(읽기만 함). 결과: diag-remain.json / 로그."""
import importlib.util, json, os, re, requests, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("collector", os.path.join(HERE, "collect-apt-official-price.py")); C = importlib.util.module_from_spec(sp); sp.loader.exec_module(C)
src = open(os.path.join(HERE, "api", "get-official-price.js"), encoding="utf-8").read()
leg = json.loads(re.search(r"const LEGACY_SIGUNGU_PREFIX = (\{.*?\});", src).group(1))
recs = {}
for ln in open("apt-official-price.jsonl", encoding="utf-8"):
    r = json.loads(ln); recs[r["pnu"]] = r
site = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
auc = requests.get(site + "/api/auction", timeout=180).json()
units = requests.get(site + "/api/data-coverage?mode=aptOfficial&i=units", timeout=60).json()["items"]
dg = lambda x: re.sub(r"\D", "", str(x or ""))
cases = []
for a in auc:
    if a.get("propType") not in ("apt", "아파트") or str(a["id"]) in units: continue
    bb = C.bunji_to_bunji(a.get("bunji"))
    if not (a.get("bCode") and bb and a.get("unitNo")): continue
    pnu = str(a["bCode"]) + "1" + bb[0] + bb[1]; r = recs.get(pnu)
    if r and r.get("units"): continue   # 호 목록이 있는 건물(범위·호 불일치)은 별도 분석
    cases.append((a, pnu, r))
print("조사 대상(건물 호 목록이 없는 사건)", len(cases), flush=True)
from concurrent.futures import ThreadPoolExecutor
def probe(x):
    a, pnu, r = x; out = []
    sg, tail = pnu[:5], pnu[5:]
    cands = [pnu]
    if sg in leg: cands.append(leg[sg] + tail)
    if r and r.get("via"): cands.append(r["via"])
    seen = set()
    for cp in cands:
        if cp in seen: continue
        seen.add(cp)
        for yr in (C.YEAR, C.YEAR - 1):
            f, total, ok = C.vget(cp, yr, 1)
            out.append({"pnu": cp, "year": yr, "ok": ok, "total": total, "nm": (f[0].get("ldCodeNm"), f[0].get("aphusNm")) if f else None})
            if f: break
    # 같은 번지의 다른 부번/본번 쪽 단서: 본번만(부번 0000)도 시도
    bj = pnu[:10]; bun = pnu[11:15]
    alt = bj + "1" + bun + "0000"
    if alt not in seen:
        f, total, ok = C.vget(alt, C.YEAR, 1); out.append({"pnu": alt, "year": C.YEAR, "ok": ok, "total": total, "nm": (f[0].get("ldCodeNm"), f[0].get("aphusNm")) if f else None, "note": "부번 0으로"})
    # 같은 본번(접두 15자리) 안의 건물 이름들(최대 12개)
    names = []
    for cp in ([leg[sg] + tail] if sg in leg else []) + [pnu]:
        seenn = {}
        for pg in (1, 2, 3):
            f, total, ok = C.vget(cp[:15], C.YEAR, pg)
            for x in (f or []): seenn.setdefault(x.get("aphusNm"), 0); seenn[x.get("aphusNm")] += 1
            if not f or len(f) < C.ROWS: break
        if seenn: names = [(k, v) for k, v in list(seenn.items())[:12]]; break
    return {"names15": names, "id": a["id"], "addr": a.get("addr"), "name": a.get("name"), "unit": a.get("unitNo"), "buildYear": a.get("buildYear"), "bCode": a.get("bCode"), "bunji": a.get("bunji"), "p": (r or {}).get("p"), "n": (r or {}).get("n"), "probe": out}
with ThreadPoolExecutor(max_workers=10) as ex: res = list(ex.map(probe, cases))
json.dump(res, open("diag-remain.json", "w"), ensure_ascii=False)
k = collections.Counter()
for r in res:
    hit = [p for p in r["probe"] if p["nm"]]
    k["조회됨(옛코드/다른키로 자료 있음)" if hit else ("조회 실패(통신)" if any(not p["ok"] for p in r["probe"]) else "VWorld 자료 0건")] += 1
print(k, flush=True)
for r in res[:400]: print(json.dumps(r, ensure_ascii=False)[:420], flush=True)
