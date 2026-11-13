"""🏛️ 빌라 호별 공시가격 수집 (2026-11-12, 측정용) - villa-df의 건물(PNU)을 무작위로 SAMPLE곳 뽑아 연도별(2024·2025·2026) 공동주택가격(VWorld)을 받아 jsonl로 저장.
시세 파악에 '개별 호의 정부 공시가격'이 새 정보가 되는지 시험하기 위한 자료(거래 결과가 아닌 정부 공표 자료). 공표일(4월 말) 이후 거래에만 쓰도록 시험에서 시점을 지킴.
앱 서버 프록시(/api/get-house?action=vworldProxy&kind=apt)로 호출 - 키는 서버에만 있음. 이어하기: 이미 받은 (PNU, 연도)는 건너뜀."""
import os, json, time, random, sys
import pandas as pd, requests
from concurrent.futures import ThreadPoolExecutor
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app"); SEC = os.environ["COLLECT_PROXY_SECRET"].strip()
SAMPLE = int(os.environ.get("SAMPLE", "15000")); YEARS = [int(x) for x in (os.environ.get("YEARS") or str(__import__("datetime").date.today().year)).split(",")]   # 비우면 올해만(5월 정기 실행: 새로 공표된 연도); THREADS = int(os.environ.get("THREADS", "8"))
OUT = "official-price.jsonl"
df = pd.read_pickle(os.environ.get("DF_FILE", "input/villa-df.pkl"))
d = df[(df["deal_date"] >= 20240501) & df["sg"].notna() & df["bj"].notna() & df["bun"].notna()]
pnu = d["sg"].astype(str) + d["bj"].astype(str) + "1" + d["bun"].astype(str).str.zfill(4) + d["ji"].fillna("0").astype(str).str.zfill(4)
P = sorted(set(pnu.tolist())); print(f"2024-05 이후 거래가 있는 건물 {len(P):,}곳 중 {min(SAMPLE, len(P)):,}곳 표본", flush=True)
random.Random(5).shuffle(P); P = P[:SAMPLE]
done = set()
if os.path.exists(OUT):
    for ln in open(OUT, encoding="utf-8"):
        try: r = json.loads(ln); done.add((r["pnu"], r["year"]))
        except Exception: pass
todo = [(p, y) for p in P for y in YEARS if (p, y) not in done]; print(f"받을 것 {len(todo):,}건(이미 {len(done):,}건)", flush=True)
fails = 0
def get(job):
    p, y = job
    for k in range(4):
        try:
            r = requests.get(SITE + "/api/get-house", params={"action": "vworldProxy", "secret": SEC, "kind": "apt", "pnu": p, "stdrYear": str(y), "format": "json", "numOfRows": "1000", "pageNo": "1"}, timeout=60).json()
            j = json.loads(r.get("body", "{}")); f = None
            for v in j.values():
                if isinstance(v, dict) and "field" in v: f = v["field"]
            if f is None: return p, y, [], True
            f = f if isinstance(f, list) else [f]
            seen = set(); rows = []
            for x in f:
                key = (x.get("dongNm"), x.get("floorNm"), x.get("hoNm"), x.get("prvuseAr"), x.get("pblntfPc"))
                if key in seen or str(x.get("stdrYear")) != str(y): continue
                seen.add(key); rows.append([x.get("dongNm") or "", x.get("floorNm") or "", x.get("hoNm") or "", x.get("prvuseAr"), x.get("pblntfPc")])
            return p, y, rows, True
        except Exception:
            time.sleep(2 * (k + 1))
    return p, y, None, False
t0 = time.time(); n = 0; got = 0
with open(OUT, "a", encoding="utf-8") as fo, ThreadPoolExecutor(max_workers=THREADS) as ex:
    for p, y, rows, ok in ex.map(get, todo):
        n += 1
        if ok: fo.write(json.dumps({"pnu": p, "year": y, "units": rows}, ensure_ascii=False) + "\n"); got += 1 if rows else 0
        else: fails += 1
        if n % 1000 == 0:
            fo.flush(); print(f"  {n:,}/{len(todo):,} 완료 · 자료 있음 {got:,} · 실패 {fails} · {int(time.time() - t0)}초", flush=True)
print(f"끝: {n:,}건 · 자료 있음 {got:,} · 실패 {fails}", flush=True)
