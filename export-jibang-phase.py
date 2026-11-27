"""지방 시군구별·월별 시장 국면 지표(2026-11-28, 측정 전용). 각 달 말 기준으로 그 달까지의 자료만:
가격(㎡당 중앙) 3·6·12개월 변화, 24개월 고점 대비 위치, 거래량(최근 6개월 vs 직전 6개월, vs 36개월 평균), 전세 ㎡당 6·12개월 변화, 시군구 전세가율."""
import os, json, importlib.util
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(s); s.loader.exec_module(bv); avm = bv.avm
NOT_METRO = "&and=(region.not.like.서울*,region.not.like.경기*,region.not.like.인천*)"
raw = avm.fetch_all_rows("house_trades", cols="region,price,size,deal_date,dealing_type", extra_filter="&deal_date=gte.20190101" + NOT_METRO)
T = bv.prep(raw) if "ppm" not in raw.columns else raw
T["ym"] = (pd.to_numeric(T["deal_date"]) // 100).astype(int)
rr = avm.fetch_all_rows("house_rent", cols="region,deposit,size,deal_date", extra_filter="&deal_date=gte.20190101&monthly_rent=eq.0" + NOT_METRO)
for c in ("deposit", "size", "deal_date"): rr[c] = pd.to_numeric(rr[c], errors="coerce")
rr = rr.dropna(); rr = rr[rr["size"] > 10]; rr["jppm"] = rr["deposit"] / rr["size"]; rr["ym"] = (rr["deal_date"] // 100).astype(int)
print("매매", len(T), "전세", len(rr), flush=True)
def months(a, b):
    out = []; y, m = a // 100, a % 100
    while y * 100 + m <= b: out.append(y * 100 + m); m += 1; y, m = (y + 1, 1) if m > 12 else (y, m)
    return out
M = months(201901, int(T["ym"].max()))
out = {}
for reg, g in T.groupby("region"):
    mp = g.groupby("ym")["ppm"].median().reindex(M); mn = g.groupby("ym").size().reindex(M).fillna(0)
    gj = rr[rr["region"] == reg]; jp = gj.groupby("ym")["jppm"].median().reindex(M)
    p3 = mp.rolling(3, min_periods=2).median(); j3 = jp.rolling(3, min_periods=2).median()
    o = {}
    for i, ym in enumerate(M):
        if i < 36: continue
        def chg(series, k): a, b = series.iloc[i], series.iloc[i - k]; return float(a / b - 1) if a > 0 and b > 0 else None
        hi = p3.iloc[i - 23:i + 1].max()
        v6 = mn.iloc[i - 5:i + 1].sum(); v6p = mn.iloc[i - 11:i - 5].sum(); v36 = mn.iloc[i - 35:i + 1].sum() / 6
        sale12 = g[(g["ym"] > M[i - 12]) & (g["ym"] <= ym)]["ppm"].median(); jr12 = gj[(gj["ym"] > M[i - 12]) & (gj["ym"] <= ym)]["jppm"].median()
        o[ym] = {"p3": chg(p3, 3), "p6": chg(p3, 6), "p12": chg(p3, 12), "dd": float(p3.iloc[i] / hi - 1) if hi > 0 and p3.iloc[i] > 0 else None,
                 "v6": float(v6 / v6p - 1) if v6p > 0 else None, "vLong": float(v6 / v36 - 1) if v36 > 0 else None,
                 "j6": chg(j3, 6), "j12": chg(j3, 12), "jr": float(jr12 / sale12) if sale12 and jr12 and sale12 > 0 else None}
    out[reg] = o
json.dump(out, open("jibang-phase.json", "w"))
print("완료 시군구", len(out), flush=True)
