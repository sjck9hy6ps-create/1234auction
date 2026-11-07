"""금리·주간 수급이 앞으로 12주(약 3개월) 시도별 가격 변화를 얼마나 미리 알려주나 (2026-11-07). 한국부동산원 주간 매매가격지수·매수우위 + 한국은행 금리, 시간순 분리(2024-07 이전 학습 → 이후 채점)."""
import sys, json, numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
m = json.load(open(sys.argv[1]))
R = m["rone"]; wk = R["saleIdx"]["weeks"]; dt = R["saleIdx"]["dates"]
SIDO = ["서울", "부산", "대구", "인천", "전남광주>광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남광주>전남", "경북", "경남", "제주"]
def mon(arr):
    o = {}
    for t, v in arr: o[str(t)[:6]] = v
    return o
base = mon(m["ecos"]["baseRateD"]); mort = mon(m["ecos"]["mortgageM"])
def mv(d, ym, back=0):
    y, mm = int(ym[:4]), int(ym[4:6]) - back
    while mm <= 0: mm += 12; y -= 1
    for _ in range(4):
        k = f"{y}{mm:02d}"
        if k in d: return d[k]
        mm -= 1
        if mm <= 0: mm += 12; y -= 1
    return np.nan
def arr(t, n):
    a = R[t]["reg"].get(n); return None if a is None else np.array([np.nan if x is None else x for x in a], float)
gang = arr("saleIdx", "서울>강남지역>동남권")
rows = []
for s in SIDO:
    idx, dem, jdx = arr("saleIdx", s), arr("saleDemand", s), arr("jeonseIdx", s)
    if idx is None or dem is None: continue
    for k in range(60, len(wk) - 12):
        if not (idx[k] > 0 and idx[k - 12] > 0 and idx[k + 12] > 0): continue
        ym = (dt[k] or "")[:7].replace("-", "")
        if not ym: continue
        g4 = np.log(gang[k] / gang[k - 4]) if gang is not None and gang[k - 4] > 0 else np.nan
        g12 = np.log(gang[k] / gang[k - 12]) if gang is not None and gang[k - 12] > 0 else np.nan
        rows.append(dict(sido=s, date=dt[k], y=np.log(idx[k + 12] / idx[k]), w4=np.log(idx[k] / idx[k - 4]), w12=np.log(idx[k] / idx[k - 12]), w52=np.log(idx[k] / idx[k - 52]) if idx[k - 52] > 0 else np.nan,
                         dem=dem[k], dem4=np.nanmean(dem[k - 3:k + 1]), dem12=np.nanmean(dem[k - 12:k]), jw4=np.log(jdx[k] / jdx[k - 4]) if jdx is not None and jdx[k - 4] > 0 else np.nan,
                         g4=g4, g12=g12, base=mv(base, ym), base_c6=mv(base, ym) - mv(base, ym, 6), mort=mv(mort, ym, 1), mort_c6=mv(mort, ym, 1) - mv(mort, ym, 7)))
D = pd.DataFrame(rows); D["date"] = pd.to_datetime(D["date"])
tr = D.date < "2024-07-01"; te = D.date >= "2024-07-01"
# 학습 구간에서 미래 12주가 겹치지 않게 12주 비움
tr = tr & (D.date < pd.Timestamp("2024-07-01") - pd.Timedelta(weeks=12))
print("학습", int(tr.sum()), "채점", int(te.sum()))
def score(cols, name):
    mdl = HistGradientBoostingRegressor(loss="absolute_error", max_iter=200, learning_rate=0.05, max_depth=4, min_samples_leaf=40, random_state=0).fit(D.loc[tr, cols], D.y[tr])
    p = mdl.predict(D.loc[te, cols]); e = D.y[te] - p
    up = (np.sign(p) == np.sign(D.y[te])).mean()
    print(f"{name:34s} 오차중앙 {np.median(np.abs(e))*100:.2f}%p  평균오차 {np.mean(np.abs(e))*100:.2f}%p  방향 맞힘 {up*100:.1f}%")
    return mdl
e0 = D.y[te]; print(f"{'(기준) 변화 없다고 예측':34s} 오차중앙 {np.median(np.abs(e0))*100:.2f}%p  평균오차 {np.mean(np.abs(e0))*100:.2f}%p")
e1 = D.y[te] - D.w12[te] * 1.0; print(f"{'(기준) 지난 12주 그대로 이어짐':34s} 오차중앙 {np.median(np.abs(e1))*100:.2f}%p  평균오차 {np.mean(np.abs(e1))*100:.2f}%p  방향 {(np.sign(D.w12[te])==np.sign(D.y[te])).mean()*100:.1f}%")
score(["w4", "w12", "w52"], "가격 흐름만")
score(["w4", "w12", "w52", "dem", "dem4", "dem12", "jw4"], "+매수우위·전세")
score(["w4", "w12", "w52", "dem", "dem4", "dem12", "jw4", "base", "base_c6", "mort", "mort_c6"], "+금리")
score(["w4", "w12", "w52", "dem", "dem4", "dem12", "jw4", "base", "base_c6", "mort", "mort_c6", "g4", "g12"], "+강남 동남권 먼저 움직임")
# 시도별 지연 반응: 강남 동남권 12주 변화와 다른 시도 다음 12주 변화 상관(2022~)
sub = D[(D.date >= "2022-01-01") & (D.sido != "서울")].dropna(subset=["g12", "y"])
print("강남 동남권 지난 12주 변화 ↔ 다른 시도 다음 12주 변화 상관", round(float(sub.g12.corr(sub.y)), 3), "표본", len(sub))
sub2 = D[(D.date >= "2022-01-01")].dropna(subset=["dem", "y"]); print("매수우위 ↔ 다음 12주 변화 상관", round(float(sub2.dem.corr(sub2.y)), 3), " 가격 지난12주 ↔ 다음 12주", round(float(sub2.w12.corr(sub2.y)), 3))
