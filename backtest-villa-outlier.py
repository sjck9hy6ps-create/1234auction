"""
🏘️ 빌라 예상매도가: 같은 동·시군구 비교 거래에서 '㎡당 가격이 지나치게 높은 거래'(재개발 지분·통매매 등)를 빼면 정확해지는가 (2026-10-11, 사용자: 동작구 노량진동 33㎡ 지하층 물건 예상매도가 6.4억이 너무 높다)
변형: A 기존 / B~D 동·시군구 비교 거래(건물 단위는 그대로)에서 ㎡당 가격이 그 비교 거래 중간값의 1.6/2.0/2.5배 넘는 거래 제외(5건 이상일 때)
같은 시험 표본. 결과: 전체·단계별 보통 오차·±10%·±20%·상하위 10%·쏠림, 과대추정(예상>실제×1.3) 비율
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "backtest-villa.py"), encoding="utf-8").read()
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm

OLD = "        w = np.exp(-age / 365.0) * np.exp(-np.abs(sz[lo:hi][m] - size) / 10.0)\n        return ppm, w"
assert OLD in src
NEW = ("        keep = np.ones(len(ppm), bool)\n"
       "        if TRIM and key_col != 'bld' and len(ppm) >= 5: keep = ppm <= TRIM * np.median(ppm)\n"
       "        w = (np.exp(-age / 365.0) * np.exp(-np.abs(sz[lo:hi][m] - size) / 10.0))[keep]\n        return ppm[keep], w")

def make_estimate(trim):
    code = src.replace(OLD, NEW).split("def main():")[0]
    g = {"__name__": "bvmod", "__file__": os.path.join(HERE, "backtest-villa.py"), "np": np, "pd": pd, "os": os, "json": json, "importlib": importlib, "TRIM": trim}
    exec(compile(code, "bvmod", "exec"), g, g)
    return g["estimate"]

FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"

def stat(G):
    e = G["est"] / G["actual"] - 1; a = e.abs()
    return {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 1), "within10Pct": round(float((a <= .1).mean()) * 100, 1), "within20Pct": round(float((a <= .2).mean()) * 100, 1),
            "p10": round(float(e.quantile(.1)) * 100, 1), "p90": round(float(e.quantile(.9)) * 100, 1), "biasPct": round(float(e.median()) * 100, 1),
            "over30Pct": round(float((e > .3).mean()) * 100, 2)}

def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
    df = bv.prep(raw)
    T = df[df["deal_date"] >= bv.TEST_FROM]
    if len(T) > 15000: T = T.sample(15000, random_state=7)
    print(f"시험 {len(T):,}건")
    res = {}
    for name, trim in (("A 기존", None), ("B 1.6배 초과 제외", 1.6), ("C 2.0배 초과 제외", 2.0), ("D 2.5배 초과 제외", 2.5)):
        E = make_estimate(trim)(df, T); E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].copy()
        E["actual"] = df.loc[E["i"].values, "price"].values
        E["seoul"] = df.loc[E["i"].values, "region"].astype(str).str.startswith("서울").values
        res[name] = {"전체": stat(E), "서울": stat(E[E["seoul"]])}
        for l, G in E.groupby("lvl"):
            if len(G) >= 50: res[name][l] = stat(G)
        print(name, res[name]["전체"], flush=True)
    txt = json.dumps(res, ensure_ascii=False, indent=1); print(txt)
    json.dump(res, open("backtest-villa-outlier.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")

if __name__ == "__main__":
    main()
