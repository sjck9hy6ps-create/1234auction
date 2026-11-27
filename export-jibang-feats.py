"""지방 아파트 낙찰 사건별 '지방 시장' 특징 뽑기(2026-11-27, 측정 전용·앱 값 불변). 모두 입찰 35일 전까지의 자료만(미래값 없음).
세대수·연식·단지 회전율·시군구 안 단지 가격 순위(대장도)·전세가율·시군구 가격/거래량 흐름·시군구 시장 규모·광역시 여부."""
import os, re, json, importlib.util
import numpy as np, pandas as pd, requests
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(s); s.loader.exec_module(bv); avm = bv.avm
SITE = "https://1234auction.vercel.app"
NOT_METRO = "&and=(region.not.like.서울*,region.not.like.경기*,region.not.like.인천*)"
def nm(x): return re.sub(r"[^0-9A-Za-z가-힣]", "", avm.normalize_complex_name(x or "")).replace("아파트", "")
bc = requests.get(SITE + "/api/auction?kind=bidCases", timeout=300).json()
C = [c for c in bc if "아파트" in (c.get("propertyType") or "") and c.get("finalBidPrice") and c.get("saleDate", "") >= "2023-01-01" and c.get("areaM2")
     and not str(c.get("addrJibun") or "").startswith(("서울", "경기", "인천"))]
print("지방 아파트 낙찰 사건", len(C), flush=True)
raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter="&deal_date=gte.20210601" + NOT_METRO)
T = bv.prep(raw); T["dt"] = pd.to_datetime(T["deal_date"].astype(str), format="%Y%m%d", errors="coerce"); T["by"] = pd.to_numeric(T["build_year"], errors="coerce")
T["dong1"] = T["dong"].astype(str).str.split().str[-1]; T["nmk"] = T["danji"].map(nm)
print("지방 매매", len(T), flush=True)
rr = avm.fetch_all_rows("house_rent", cols="region,dong,danji,deposit,monthly_rent,size,deal_date", extra_filter="&deal_date=gte.20220101&monthly_rent=eq.0" + NOT_METRO)
for c in ("deposit", "size", "deal_date"): rr[c] = pd.to_numeric(rr[c], errors="coerce")
rr = rr.dropna(subset=["deposit", "size", "deal_date"]); rr["dt"] = pd.to_datetime(rr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce")
rr["dong1"] = rr["dong"].astype(str).str.split().str[-1]; rr["nmk"] = rr["danji"].map(nm)
print("지방 전세", len(rr), flush=True)
kp = avm.fetch_all_rows("kapt_complex_info", cols="kapt_code,kapt_name,as3,households", order_col="kapt_code", extra_filter="&households=gt.0")
HH = {}
for r in kp.itertuples(): HH.setdefault((str(r.as3).strip().split()[-1] if r.as3 else "", nm(r.kapt_name)), set()).add(int(r.households))
GB = {k: g for k, g in T.groupby(["dong", "bunji"])}; GR = {k: g for k, g in T.groupby("region")}; RN = {k: g for k, g in rr.groupby(["dong1", "nmk"])}
SIDO = {"부산": "부산", "대구": "대구", "광주": "광주", "대전": "대전", "울산": "울산", "세종": "세종"}
out = {}
for c in C:
    g = GB.get((c.get("dong"), str(c.get("bunji"))))
    if g is None or not len(g): continue
    sd = pd.Timestamp(c["saleDate"]); cut = sd - pd.Timedelta(days=35); area = float(c["areaM2"])
    reg = g["region"].mode()[0]; g = g[g["region"] == reg]; danji = g["danji"].mode()[0]; nk = nm(danji); d1 = str(g["dong1"].mode()[0])
    gp = g[g["dt"] <= cut]
    o = {"reg": reg, "metroCity": 1 if str(c.get("addrJibun", ""))[:2] in SIDO else 0}
    hh = HH.get((d1, nk)); o["hh"] = next(iter(hh)) if hh and len(hh) == 1 else None
    by = g["by"].dropna(); o["age"] = int(sd.year - by.median()) if len(by) else None
    s6 = gp[(gp["dt"] > cut - pd.Timedelta(days=182)) & ((gp["size"] - area).abs() <= 3)]; o["n6s"] = int(len(s6))
    c12 = gp[gp["dt"] > cut - pd.Timedelta(days=365)]; o["n12c"] = int(len(c12)); o["turn"] = (len(c12) / o["hh"]) if o["hh"] else None
    s12 = c12[(c12["size"] - area).abs() <= 5]; o["p12"] = float(s12["price"].median()) if len(s12) else None
    R = GR.get(reg)
    if R is not None:
        Rp = R[(R["dt"] <= cut)]
        R12 = Rp[Rp["dt"] > cut - pd.Timedelta(days=365)]
        cm = R12.groupby(["dong", "bunji"])["ppm"].median()
        if len(c12) and len(cm) >= 5: o["rank"] = float((cm < c12["ppm"].median()).mean())   # 시군구 안 단지 ㎡당 가격 순위(1=대장)
        a = Rp[Rp["dt"] > cut - pd.Timedelta(days=182)]; b = Rp[(Rp["dt"] <= cut - pd.Timedelta(days=182)) & (Rp["dt"] > cut - pd.Timedelta(days=365))]
        if len(a) >= 20 and len(b) >= 20: o["mom"] = float(a["ppm"].median() / b["ppm"].median() - 1); o["volChg"] = float(len(a) / len(b) - 1)
        o["sggN12"] = int(len(R12))
    rn = RN.get((d1, nk))
    if rn is not None and o.get("p12"):
        j = rn[(rn["dt"] <= cut) & (rn["dt"] > cut - pd.Timedelta(days=365)) & ((rn["size"] - area).abs() <= 5)]
        if len(j) >= 2: o["jr"] = float(j["deposit"].median() / o["p12"])
    out[c["id"]] = o
json.dump(out, open("jibang-feats.json", "w"))
print("완료", len(out), "세대수", sum(1 for v in out.values() if v.get("hh")), "전세가율", sum(1 for v in out.values() if v.get("jr")), "순위", sum(1 for v in out.values() if v.get("rank") is not None), flush=True)
