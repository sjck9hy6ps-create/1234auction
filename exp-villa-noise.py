"""🏘 빌라 가격의 '잡음 바닥' 측정(2026-11-14, 측정 전용).
질문: 같은 건물·같은 면적·같은 시기에 거래된 집끼리도 가격이 얼마나 다른가? 이 차이는 거래 기록만 아는 어떤 모델도 넘을 수 없는 오차의 바닥(낙관적 하한 - 같은 시기 이웃 거래를 안다고 가정, 실제 예측은 과거 자료만 씀).
방법: 그룹 안에서 한 거래씩 빼고(leave-one-out) 나머지 거래의 중앙값으로 예측했을 때의 오차(|예측/실제 − 1|, 앱 채점과 같은 정의).
그룹: A 같은 건물·같은 달·면적 ±1.5㎡ / B A+같은 층 / C 같은 건물·같은 분기·면적 ±1.5㎡ / D 같은 동·같은 달·면적 ±2㎡·연식 ±2년(건물이 달라도)."""
import json
import numpy as np, pandas as pd
df = pd.read_pickle("input/villa-df.pkl"); df = df[(df["deal_date"] >= 20230101)].copy().reset_index(drop=True)
df["q"] = (df["ym"] // 100) * 4 + ((df["ym"] % 100) - 1) // 3
print("거래", len(df), flush=True)
def loo(keys, size_tol, extra=None, minn=2):
    errs = []; ns = []; price_band = []; n_groups = 0
    for _, g in df.groupby(keys, sort=False):
        if len(g) < minn: continue
        n_groups += 1
        s = g["size"].values; p = g["price"].values.astype(float); y = g["by2"].values
        for i in range(len(g)):
            m = (np.abs(s - s[i]) <= size_tol); m[i] = False
            if extra is not None:
                m &= (np.isnan(y) | np.isnan(y[i]) | (np.abs(y - y[i]) <= extra))
            if m.sum() < 1: continue
            est = float(np.median(p[m])); errs.append(est / p[i] - 1); ns.append(int(m.sum())); price_band.append(p[i])
    e = np.array(errs); a = np.abs(e)
    if not len(e): return {"건수": 0}
    pb = np.array(price_band)
    out = {"평가한 거래": int(len(e)), "평가 그룹": n_groups, "그룹내 이웃 거래 중앙": int(np.median(ns)), "바닥 오차(중앙)%": round(float(np.median(a)) * 100, 2), "±10% 이내 %": round(float((a <= .1).mean()) * 100, 1), "높게 10%+ %": round(float((e > .1).mean()) * 100, 1), "낮게 10%- %": round(float((e < -.1).mean()) * 100, 1)}
    for lab, lo, hi in (("8천 미만", 0, 8000), ("8천~1.5억", 8000, 15000), ("1.5억 이상", 15000, 1e12)):
        mm = (pb >= lo) & (pb < hi)
        if mm.sum() >= 300: out["가격대 " + lab] = {"건수": int(mm.sum()), "바닥 오차%": round(float(np.median(a[mm])) * 100, 2)}
    return out
res = {}
res["A 같은 건물·같은 달·면적 ±1.5㎡"] = loo(["bld", "ym"], 1.5)
df["fl"] = df["floor"].fillna(-99)
res["B A + 같은 층"] = loo(["bld", "ym", "fl"], 1.5)
res["C 같은 건물·같은 분기·면적 ±1.5㎡"] = loo(["bld", "q"], 1.5)
res["D 같은 동·같은 달·면적 ±2㎡·연식 ±2년(다른 건물 포함)"] = loo(["dk", "ym"], 2.0, extra=2.0)
print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("villa-noise-test.json", "w"), ensure_ascii=False, indent=1)
