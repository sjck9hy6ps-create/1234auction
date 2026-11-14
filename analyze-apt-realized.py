"""🏢 아파트: 추천가로 샀다면 실제로 남았을 마진 점검(2026-11-14, 측정 전용) - 빌라와 같은 방식.
rows(apt-case-rows: 사례마다 낙찰일 35일 전 자료로 앱이 다시 계산한 값) + 낙찰 후 180일 안 같은 단지·같은 평형(±3㎡) 실거래(되팔 가격 대리값).
실현 순이익 ≈ 앱 예상 순마진 − (예상매도가 − 대리 매도가) (빌라와 같은 1:1 가정, 세금 변화 제외)."""
import os, json, glob, importlib.util, statistics as st, collections
import numpy as np, pandas as pd, requests
HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); avm = bv.avm
SITE = "https://1234auction.vercel.app"
bc = requests.get(SITE + "/api/auction?kind=bidCases", timeout=300).json()
BC = {c["id"]: c for c in bc if "아파트" in (c.get("propertyType") or "") and c.get("finalBidPrice")}
rows = []
for f in glob.glob("aptrows-*/rows.json"): rows += [r for r in json.load(open(f)) if not r.get("err")]
print("사례 rows", len(rows), "낙찰사례(아파트)", len(BC), flush=True)
raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year,cdeal_type", extra_filter="&deal_date=gte.20250201")
T = bv.prep(raw); T["dt"] = pd.to_datetime(T["deal_date"].astype(str), format="%Y%m%d", errors="coerce")
print("아파트 거래", len(T), "최근", T["deal_date"].max(), flush=True)
G = {k: g for k, g in T.groupby(["dong", "bunji"])}
SIDO = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}
out = []
for r in rows:
    c = BC.get(r["id"]); 
    if not c or not r.get("saleFinal") or not r.get("act"): continue
    sido = SIDO.get((c.get("addrJibun") or "").split(" ")[0], "")
    g = G.get((c["dong"], str(c["bunji"])))
    if g is None: continue
    sd = pd.to_datetime(c["saleDate"]); area = c["areaM2"]
    if sido: g = g[g["region"].astype(str).str.startswith(sido)]
    m = g[(g["dt"] > sd) & (g["dt"] <= sd + pd.Timedelta(days=180)) & ((g["size"] - area).abs() <= 3)]
    if len(m) < 1: continue
    ref = float(np.median(m["ppm"].values)) * area
    out.append({"id": r["id"], "sale": r["saleFinal"], "ref": ref, "n": int(len(m)), "act": r["act"], "rec": r.get("rec"), "margin": r.get("margin"), "verdict": r.get("verdict"), "mkt": r.get("mkt"), "saleDate": c["saleDate"], "minB": r.get("minB"), "probRec": r.get("probRec")})
print("대리값 있는 사례", len(out), flush=True)
O = pd.DataFrame(out)
def err(X): e = X["sale"] / X["ref"] - 1; a = e.abs(); return {"n": int(len(X)), "오차중앙%": round(float(a.median()) * 100, 1), "쏠림중앙%": round(float(e.median()) * 100, 1), "±10%": round(float((a <= .1).mean()) * 100, 1), "높게10%+": round(float((e > .1).mean()) * 100, 1)}
res = {"예상매도가 vs 이후 같은 단지 실거래(전체)": err(O)}
O["won"] = (O["rec"].notna()) & (O["rec"] > O["act"])
res["추천가로 낙찰될 사례"] = err(O[O["won"]]); res["추천가로는 못 이길 사례"] = err(O[~O["won"] & O["rec"].notna()])
for v, g in O.groupby("verdict"):
    if len(g) >= 40: res["판정·" + str(v)] = err(g)
W = O[O["won"] & O["margin"].notna()].copy(); W["real"] = W["margin"] - (W["sale"] - W["ref"])
def rm(X): return {"n": int(len(X)), "예상 순마진 중앙(만)": round(float(X["margin"].median())), "실현(대리) 중앙(만)": round(float(X["real"].median())), "평균 예상→실현(만)": [round(float(X["margin"].mean())), round(float(X["real"].mean()))], "손실 %": round(float((X["real"] < 0).mean()) * 100, 1), "예상 대비 새는 마진 평균(만)": round(float((X["margin"] - X["real"]).mean()))}
res["실제 마진(추천가로 낙찰될 사례, 판정 전체)"] = rm(W)
for v, g in W.groupby("verdict"):
    if len(g) >= 30: res["실제 마진·판정 " + str(v)] = rm(g)
# 일괄 보수화(추천가 낮추기) 시뮬레이션: 빌라와 같은 방식(입찰가 1만 낮추면 순이익 1.02만 늘어남)
sim = {}
A = O[O["rec"].notna() & O["margin"].notna()]
for h in (0, 0.02, 0.04, 0.06, 0.08, 0.10):
    tot = 0.0; w = 0
    for r in A.itertuples():
        bid = r.rec - h * r.sale / 1.02
        if bid > r.act: tot += r.margin - (r.sale - r.ref) - (bid - r.rec) * 1.02; w += 1
    sim[f"보수 {int(h * 100)}%"] = {"낙찰률%": round(w / len(A) * 100, 1), "시도당 실현 기대 순이익(만)": round(tot / len(A))}
res["일괄 보수화 시뮬레이션(추천가 있는 사례)"] = sim
print(json.dumps(res, ensure_ascii=False, indent=1, default=str)); json.dump(res, open("apt-realized.json", "w"), ensure_ascii=False, indent=1, default=str)
O.to_json("apt-realized-rows.json", orient="records", force_ascii=False)
