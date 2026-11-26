"""낙찰 후 같은 단지·같은 평형(±3㎡) 실거래가(되팔 가격 대리값)를 사건별로 뽑기(2026-11-26, 1회 유찰 기회 정밀 시험용, 측정 전용).
analyze-apt-realized.py와 같은 연결 방식(동+번지, 시도 일치). 90일·180일 두 구간의 ㎡당 중앙값×면적과 건수를 저장."""
import os, json, importlib.util
import numpy as np, pandas as pd, requests
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(s); s.loader.exec_module(bv); avm = bv.avm
SITE = "https://1234auction.vercel.app"
bc = requests.get(SITE + "/api/auction?kind=bidCases", timeout=300).json()
BC = [c for c in bc if "아파트" in (c.get("propertyType") or "") and c.get("finalBidPrice") and c.get("saleDate") and c.get("areaM2")]
print("아파트 낙찰사례", len(BC), flush=True)
raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year,cdeal_type", extra_filter="&deal_date=gte.20241101")
T = bv.prep(raw); T["dt"] = pd.to_datetime(T["deal_date"].astype(str), format="%Y%m%d", errors="coerce")
print("아파트 거래", len(T), "최근", T["deal_date"].max(), flush=True)
G = {k: g for k, g in T.groupby(["dong", "bunji"])}
SIDO = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주", "전남광주통합특별시": "전남"}
last = T["dt"].max()
out = {}
for c in BC:
    g = G.get((c.get("dong"), str(c.get("bunji"))))
    if g is None: continue
    sido = SIDO.get((c.get("addrJibun") or "").split(" ")[0], "")
    if sido: g = g[g["region"].astype(str).str.startswith(sido)]
    sd = pd.to_datetime(c["saleDate"]); area = float(c["areaM2"])
    g = g[(g["size"] - area).abs() <= 3]
    o = {"area": area, "obs": int((last - sd).days)}
    for d in (90, 180):
        m = g[(g["dt"] > sd) & (g["dt"] <= sd + pd.Timedelta(days=d))]
        o[f"n{d}"] = int(len(m))
        if len(m): o[f"ref{d}"] = round(float(np.median(m["ppm"].values)) * area)
    pre = g[(g["dt"] <= sd) & (g["dt"] > sd - pd.Timedelta(days=180))]
    o["npre"] = int(len(pre))
    if len(pre): o["pre180"] = round(float(np.median(pre["ppm"].values)) * area)
    out[c["id"]] = o
json.dump(out, open("apt-postref.json", "w"))
print("연결된 사례", len(out), "이후 180일 거래 있음", sum(1 for v in out.values() if v.get("n180")), flush=True)
