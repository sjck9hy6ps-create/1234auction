"""단지 전체 거래 활발도 검증(2026-11-21): 같은 시군구 안에서 최근 12개월 거래 건수 순위(상위 20% / 중간 / 하위 40%)가 이후 거래를 얼마나 맞히는지.
오늘 기준 3·6·9·12개월 전 시점마다 판정하고, 그 뒤 월평균 거래·'이후 거래 0건' 비율을 등급별로 비교. 대상: 최근 24개월 안에 거래가 있었던 단지(같은 시군구 10곳 이상)."""
import importlib.util, os, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py")); cyc = importlib.util.module_from_spec(sp); sp.loader.exec_module(cyc)
avm = cyc.avm
raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type", extra_filter="&deal_date=gte.20210101")
df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
for c in ("price", "size", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"]); df = df[(df["price"] > 0) & (df["size"] > 10)]
df["ym"] = (df["deal_date"] // 10000) * 12 + (df["deal_date"] // 100 % 100) - 1
df["ckey"] = df["region"].astype(str) + "|" + df["dong"].astype(str).str.split().str[-1] + "|" + df["danji"].astype(str)
last = int(df["ym"].max()) - 1
print(f"거래 {len(df):,}건 · 마지막 완전한 달 {last // 12}-{last % 12 + 1:02d}", flush=True)
res = {}
for back in (3, 6, 9, 12):
    T = last - back; fm = last - T
    univ = df[(df["ym"] > T - 24) & (df["ym"] <= T)]   # 앱은 지역 실거래 최근 2년만 있어 같은 범위로 순위를 매김
    c12 = univ[univ["ym"] > T - 12].groupby("ckey", observed=True).size()
    allc = pd.DataFrame({"ckey": univ["ckey"].unique()}); allc["region"] = allc["ckey"].str.split("|").str[0]
    allc["n12"] = allc["ckey"].map(c12).fillna(0)
    fwd = df[(df["ym"] > T) & (df["ym"] <= last)].groupby("ckey", observed=True).size()
    allc["fwd"] = allc["ckey"].map(fwd).fillna(0)
    rows = []
    for rg, g in allc.groupby("region"):
        if len(g) < 10: continue
        pct = g["n12"].rank(pct=True, method="average")
        tier = np.where(pct >= 0.8, "상위20%", np.where(pct >= 0.4, "중간", "하위40%"))
        rows.append(pd.DataFrame({"tier": tier, "n12": g["n12"].to_numpy(), "fwd": g["fwd"].to_numpy()}))
    r = pd.concat(rows)
    out = {}
    for t, g in r.groupby("tier"):
        out[t] = {"단지수": len(g), "직전12개월 평균건수": round(float(g["n12"].mean()), 1), "이후 월평균 거래": round(float(g["fwd"].mean() / fm), 2), "이후 거래 0건 단지 %": round(float((g["fwd"] == 0).mean()) * 100, 1)}
    res[f"{back}개월 전(이후 {fm}개월)"] = out
    print(f"[{back}개월 전] 단지 {len(r):,}", json.dumps(out, ensure_ascii=False), flush=True)
json.dump(res, open("apt-activity-test.json", "w"), ensure_ascii=False, indent=1)
