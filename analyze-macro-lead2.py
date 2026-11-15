"""금리·수급 신호가 앞으로 12주 가격 변화를 미리 알려주는가 - 구간을 나눠 시간순 채점(2026-11-15, 사용자: 거시경제 관점 시험).
2026-11-07 시험은 2024-07 이후만 채점했음. 이번엔 2021~2023(금리 인상기·하락기)도 채점 구간에 넣고, 반드시 '그 시점 이전 자료만'으로 학습한다.
한계: 한국부동산원 주간 지수는 2020년부터라 2022년 전환기를 채점할 때 학습 자료엔 금리 인상기가 없음(그래서 선행성을 학습으로 못 배움) - 이 한계를 결과에 함께 적는다.
입력: macro.json(collect-macro.py 결과). 서버·앱에 저장하지 않음."""
import sys, json, numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
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
print("주간 지수", wk[0], "~", wk[-1], "주 수", len(wk), "· 날짜", dt[0], "~", dt[-1])
rows = []
for s in SIDO:
    idx, dem, jdx = arr("saleIdx", s), arr("saleDemand", s), arr("jeonseIdx", s)
    if idx is None: continue
    for k in range(52, len(wk) - 12):
        if not (idx[k] > 0 and idx[k - 12] > 0 and idx[k + 12] > 0 and idx[k - 4] > 0): continue
        ym = (dt[k] or "")[:7].replace("-", "")
        if not ym: continue
        dm = dem[k] if dem is not None else np.nan
        rows.append(dict(sido=s, date=pd.Timestamp(dt[k]), y=np.log(idx[k + 12] / idx[k]), w4=np.log(idx[k] / idx[k - 4]), w12=np.log(idx[k] / idx[k - 12]), w52=np.log(idx[k] / idx[k - 52]) if idx[k - 52] > 0 else np.nan,
                         dem=dm, jw4=np.log(jdx[k] / jdx[k - 4]) if jdx is not None and jdx[k - 4] > 0 else np.nan,
                         base=mv(base, ym), base_c6=mv(base, ym) - mv(base, ym, 6), mort=mv(mort, ym, 1), mort_c6=mv(mort, ym, 1) - mv(mort, ym, 7)))
D = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
print("행", len(D), "기간", D.date.min().date(), "~", D.date.max().date())
SETS = {"가격 흐름만": ["w4", "w12", "w52"], "+매수우위·전세": ["w4", "w12", "w52", "dem", "jw4"], "+금리": ["w4", "w12", "w52", "dem", "jw4", "base", "base_c6", "mort", "mort_c6"]}
WINDOWS = [("2022-07~2023-06 하락기", "2022-07-01", "2023-07-01"), ("2023-07~2024-06 바닥·반등", "2023-07-01", "2024-07-01"), ("2024-07~2025-06", "2024-07-01", "2025-07-01"), ("2025-07~현재", "2025-07-01", "2100-01-01"), ("2021-07~2022-06 인상 시작", "2021-07-01", "2022-07-01")]
def fit(cols, tr):
    X = tr[cols].fillna(tr[cols].median())
    return HistGradientBoostingRegressor(loss="absolute_error", max_iter=150, learning_rate=0.05, max_depth=3, min_samples_leaf=30, random_state=0).fit(X, tr.y), tr[cols].median()
out = {}
for name, a, b in WINDOWS:
    te = D[(D.date >= a) & (D.date < b)]; tr = D[D.date < pd.Timestamp(a) - pd.Timedelta(weeks=12)]
    if len(te) < 50 or len(tr) < 200:
        print(f"── {name}: 채점 {len(te)} · 학습 {len(tr)} → 학습 자료 부족"); continue
    rev = np.sign(te.w12) != np.sign(te.y)
    print(f"── {name} (채점 {len(te)}행, 학습 {len(tr)}행 / 지난 12주와 방향이 뒤집힌 비율 {rev.mean()*100:.0f}%)")
    e0 = te.y; e1 = te.y - te.w12
    print(f"   {'변화 없음 예측':16s} 오차중앙 {np.median(np.abs(e0))*100:.2f}%p")
    print(f"   {'지난 12주 유지':16s} 오차중앙 {np.median(np.abs(e1))*100:.2f}%p  방향 {(np.sign(te.w12)==np.sign(te.y)).mean()*100:.1f}%  (뒤집힌 구간 방향 0%)")
    out[name] = {}
    for sn, cols in SETS.items():
        mdl, med = fit(cols, tr); p = mdl.predict(te[cols].fillna(med)); e = te.y - p
        hit = (np.sign(p) == np.sign(te.y)).mean(); hitrev = (np.sign(p[rev.values]) == np.sign(te.y[rev])).mean() if rev.sum() else np.nan
        print(f"   {sn:16s} 오차중앙 {np.median(np.abs(e))*100:.2f}%p  방향 {hit*100:.1f}%  뒤집힌 구간 방향 {hitrev*100:.1f}%")
# 금리 인상 뒤 12주: 기준금리가 오른 달(전달 대비) 직후 12주 가격 변화 평균 vs 그 외
D["ym"] = D.date.dt.strftime("%Y%m")
D["bu"] = [mv(base, y) - mv(base, y, 1) for y in D.ym]
for lab, f in (("기준금리를 올린 달", D.bu > 0.01), ("기준금리를 내린 달", D.bu < -0.01), ("변동 없는 달", D.bu.abs() <= 0.01)):
    sub = D[f]
    if len(sub) > 30: print(f"{lab}: 표본 {len(sub)} 다음 12주 가격 변화 평균 {sub.y.mean()*100:+.2f}%  (같은 시점 직전 12주 {sub.w12.mean()*100:+.2f}%)")
for per, a, b in (("2021-08~2023-02 인상기", "2021-08-01", "2023-03-01"), ("2023-03~2024-12 동결·인하 전", "2023-03-01", "2025-01-01")):
    sub = D[(D.date >= a) & (D.date < b)].dropna(subset=["base_c6"])
    print(f"{per}: 지난 6개월 기준금리 변화 ↔ 다음 12주 가격 변화 상관 {sub.base_c6.corr(sub.y):+.3f} · 지난 12주 가격 ↔ 다음 12주 {sub.w12.corr(sub.y):+.3f} · 표본 {len(sub)}")
