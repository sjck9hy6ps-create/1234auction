"""
🏷️ 예상매도가 사후 채점(2026-11-13): 과거 낙찰 사례(villa-cases-asof)의 '그때 예상매도가'를, 낙찰일 이후 실제로 신고된 같은 건물(없으면 같은 동 비슷한 면적) 실거래가와 비교.
낙찰 후 되판 가격은 없으므로 '같은 건물의 이후 실거래'를 되팔 가격의 대리 기준으로 사용. 낙찰일 +0~180일 거래만(신고 지연 때문에 최근 사례는 표본이 적음).
"""
import os, json, importlib.util
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); avm = bv.avm
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
cases = json.load(open(os.environ.get("CASES_FILE", "input/villa-cases-asof.json")))
raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.20260301{FLT}")
df = bv.prep(raw); print(f"거래 {len(df):,}건(2026-03~), 최근 거래일 {df['deal_date'].max()}", flush=True)
df["dt"] = pd.to_datetime(df["deal_date"].astype(str), format="%Y%m%d", errors="coerce")
bg = {k: g for k, g in df.groupby("bld")}; dg = {k: g for k, g in df.groupby("dk")}
rows = []
for c in cases:
    sd = pd.to_datetime(str(c["sale"]), format="%Y%m%d", errors="coerce")
    if pd.isna(sd): continue
    bld = f"{c['region']}|{c['dong']}|{c['bunji']}"; dk = f"{c['region']}|{c['dong']}"; area = c["area"]
    def pick(g, tol, minn):
        if g is None: return None
        m = g[(g["dt"] > sd) & (g["dt"] <= sd + pd.Timedelta(days=180)) & ((g["size"] - area).abs() <= tol)]
        return m if len(m) >= minn else None
    m = pick(bg.get(bld), 6, 1); kind = "같은 건물"
    if m is None: m = pick(dg.get(dk), 4, 3); kind = "같은 동 비슷한 면적 3건+"
    if m is None: continue
    # 면적 차이를 평당 가격으로 보정한 실거래 기준값(중앙)
    ref = float(np.median(m["ppm"].values)) * area
    rows.append({"id": c["id"], "kind": kind, "n": int(len(m)), "lvl": c["lvl"], "est": c["est"], "base": c["base"], "q25": c["q25"], "q10": c["q10"], "ref": ref, "nbld": c.get("nBld")})
R = pd.DataFrame(rows); print(f"매칭 {len(R)}건 / 사례 {len(cases)}건", flush=True)
def stat(T):
    e = T["est"].values / T["ref"].values - 1; a = np.abs(e)
    return {"n": int(len(T)), "오차중앙%": round(float(np.median(a)) * 100, 1), "쏠림중앙%": round(float(np.median(e)) * 100, 1), "±10%": round(float((a <= .1).mean()) * 100, 1), "±20%": round(float((a <= .2).mean()) * 100, 1),
            "크게높게(+10%↑)": round(float((e > .1).mean()) * 100, 1), "크게낮게(-10%↓)": round(float((e < -.1).mean()) * 100, 1),
            "하위25%값적중(목표75)": round(float((T["ref"].values >= T["q25"].values).mean()) * 100, 1), "하위10%값적중(목표90)": round(float((T["ref"].values >= T["q10"].values).mean()) * 100, 1)}
res = {"전체": stat(R) if len(R) else None}
for k, G in R.groupby("kind"): res[k] = stat(G)
for l, G in R.groupby("lvl"):
    if len(G) >= 30: res["단계·" + l] = stat(G)
print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("sale-vs-trades.json", "w"), ensure_ascii=False, indent=1)
