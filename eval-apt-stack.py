"""
🏢 아파트 예상매도가 종합 평가 채점 (2026-11-07, 사용자: 아파트 예상매도가 개선)
입력: apt-stack-data 워크플로가 만든 rows-*.json (앱 실제 계산으로 시점별 예상매도가+특징, 정답=그 뒤 40일 안 실제 거래가).
방법: 시간순 분리(앞 구간 학습 → 뒤 구간 채점) 2가지, 정답 ÷ 앱 예상 의 로그 차이를 HistGradientBoosting(절대오차)로 보정. 앱 값과 보정 값을 같은 거래로 비교.
"""
import os, sys, json, glob, math
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

D = sys.argv[1] if len(sys.argv) > 1 else "rows"
files = sorted(glob.glob(os.path.join(D, "**", "rows.json"), recursive=True))
rows = []
for f in files:
    rows += json.load(open(f))
print("파일", len(files), "행", len(rows))
R = []
for r in rows:
    if r.get("err") or not r.get("sale") or not r.get("truth") or not r.get("f"): continue
    f = r["f"]; d = dict(f)
    d.update(cutoff=r["cutoff"], lawd=r["lawd"], cls=r["cls"], sale=float(r["sale"]), truth=float(r["truth"][0]), pyung=r["pyung"], floor=r["floor"], n6=r["n6"], weak=1 if r["weak"] else 0, byt=r["by"] or "")
    R.append(d)
df = pd.DataFrame(R)
print("유효", len(df), df.cutoff.value_counts().sort_index().to_dict())

def tier(r):
    b = r["byt"]
    if "가중 중위값" in b or "가장 최근 3건" in b: return "A"
    if "3건 미만" in b: return "B"
    if "같은 단지 거래" in b or r["weak"]: return "C"
    return "D"
df["tier"] = df.apply(tier, axis=1)
df["floor"] = pd.to_numeric(df["floor"], errors="coerce")
df["y"] = np.log(df.truth / df.sale)

def lr(c):
    return np.log(pd.to_numeric(df[c], errors="coerce").where(lambda s: s > 0) / df.sale)
X = pd.DataFrame(index=df.index)
for c in ["base", "l3", "pw1", "pw2", "pw2f", "p3m", "q40", "m12", "m36", "lp", "wb"]:
    X["r_" + c] = lr(c)
for c in ["sfl", "sfc", "tur", "jrf", "fl"]:
    X["f_" + c] = np.log(pd.to_numeric(df[c], errors="coerce").where(lambda s: s > 0))
for c in ["n3", "n12", "n36", "lag", "dsp", "v6", "vp6", "mxF", "tr", "jm", "jrr", "lm3", "lm6", "lv3", "lv12", "dm3", "dm6", "dv3", "dv12", "n6", "pyung", "floor", "weak", "cap", "fbN"]:
    X[c] = pd.to_numeric(df[c], errors="coerce")
X["lsale"] = np.log(df.sale)
X["cutoff_m"] = (pd.to_datetime(df.cutoff).dt.month)  # 계절(연도 아님)
X["age"] = (pd.to_datetime(df.cutoff).dt.year - pd.to_numeric(df["by"], errors="coerce")).where(lambda s: s >= 0)
X["cls_c"] = df.cls.map({"서울": 0, "경기·인천": 1, "지방": 2})
X["sido"] = df.lawd.str[:2].astype(int)
X["tier_c"] = df.tier.map({"A": 0, "B": 1, "C": 2, "D": 3})
X["hi_floor_share"] = (X.floor / X.mxF.replace(0, np.nan))

if os.environ.get("MACRO"):   # 금리·주간 시장 흐름 특징(시점 기준으로 그때까지 공개된 값만)
    mac = json.load(open(os.environ["MACRO"]))
    SIDO_R = {"11": ["서울"], "26": ["부산"], "27": ["대구"], "28": ["인천"], "29": ["전남광주>광주"], "30": ["대전"], "31": ["울산"], "36": ["세종"], "41": ["경기"], "42": ["강원"], "51": ["강원"], "43": ["충북"], "44": ["충남"], "45": ["전북"], "52": ["전북"], "46": ["전남광주>전남"], "47": ["경북"], "48": ["경남"], "50": ["제주"]}
    wk = mac["rone"]["saleIdx"]["weeks"]; wdate = mac["rone"]["saleIdx"]["dates"]
    def widx(cut):
        k = -1
        for i, d in enumerate(wdate):
            if d and d <= cut: k = i
        return k
    def ser(tbl, name): return (mac["rone"][tbl]["reg"].get(name) if mac["rone"].get(tbl) else None)
    def chg(a, k, n):
        if a is None or k - n < 0 or a[k] is None or a[k - n] is None: return np.nan
        return float(np.log(a[k] / a[k - n]))
    def lvl(a, k):
        if a is None or k < 0 or a[k] is None: return np.nan
        return float(a[k])
    def mavg(a, k, n):
        if a is None or k - n + 1 < 0: return np.nan
        v = [x for x in a[k - n + 1:k + 1] if x is not None]; return float(np.mean(v)) if v else np.nan
    def monthly(arr):
        o = {}
        for t, v in arr: o[str(t)[:6]] = v
        return o
    base = monthly(mac["ecos"]["baseRateD"]); mort = monthly(mac["ecos"]["mortgageM"]); cd = monthly(mac["ecos"]["cd91D"]); kt = monthly(mac["ecos"]["ktb3D"])
    def mval(d, ym, back=0):
        y, m = int(ym[:4]), int(ym[4:6]); m -= back
        while m <= 0: m += 12; y -= 1
        k = f"{y}{m:02d}"
        for _ in range(3):   # 해당 달 값이 없으면 이전 달 값
            if k in d: return d[k]
            m -= 1
            if m <= 0: m += 12; y -= 1
            k = f"{y}{m:02d}"
        return np.nan
    cache = {}
    def macro_row(cut, lawd):
        key = (cut, lawd[:2])
        if key in cache: return cache[key]
        k = widx(cut); ym = cut[:4] + cut[5:7]; r = {}
        nm = SIDO_R.get(lawd[:2], ["전국"])[0]
        for tag, region in (("s", nm), ("n", "전국"), ("g", "서울>강남지역>동남권")):
            a = ser("saleIdx", region); d = ser("saleDemand", region)
            r[f"m_{tag}_w4"] = chg(a, k, 4); r[f"m_{tag}_w12"] = chg(a, k, 12); r[f"m_{tag}_w52"] = chg(a, k, 52)
            r[f"m_{tag}_dem"] = lvl(d, k); r[f"m_{tag}_dem4"] = mavg(d, k, 4); r[f"m_{tag}_dem12"] = mavg(d, k, 13)
        r["m_jw4"] = chg(ser("jeonseIdx", nm), k, 4)
        r["m_base"] = mval(base, ym); r["m_base_c6"] = r["m_base"] - mval(base, ym, 6)
        r["m_mort"] = mval(mort, ym, 1); r["m_mort_c6"] = r["m_mort"] - mval(mort, ym, 7)
        r["m_cd"] = mval(cd, ym); r["m_kt3"] = mval(kt, ym); r["m_kt3_c6"] = r["m_kt3"] - mval(kt, ym, 6)
        cache[key] = r; return r
    M = pd.DataFrame([macro_row(c, l) for c, l in zip(df.cutoff, df.lawd)], index=df.index)
    keep = os.environ.get("MACRO_SET", "all")
    if keep == "rate": M = M[[c for c in M.columns if c.startswith("m_base") or c.startswith("m_mort") or c in ("m_cd", "m_kt3", "m_kt3_c6")]]
    elif keep == "weekly": M = M[[c for c in M.columns if c.startswith("m_s_") or c.startswith("m_n_") or c.startswith("m_g_") or c == "m_jw4"]]
    X = pd.concat([X, M], axis=1)
X = X.drop(columns=[c for c in os.environ.get("DROP", "").split(",") if c])
X = X.loc[:, X.nunique(dropna=True) >= 2]   # 값이 하나뿐인 열은 학습기가 오류를 냄
print("사용 특성", X.shape[1], list(X.columns))

def metr(e):
    e = np.asarray(e)
    if len(e) == 0: return None
    return dict(n=len(e), 오차중앙=round(float(np.median(np.abs(e))) * 100, 2), 오차평균=round(float(np.mean(np.abs(e))) * 100, 2), 치우침=round(float(np.median(e)) * 100, 2), pm10=round(float((np.abs(e) <= .1).mean()) * 100, 1),
                高=round(float((e < -.1).mean()) * 100, 1), 低=round(float((e > .1).mean()) * 100, 1))

out = {"at": pd.Timestamp.utcnow().isoformat(), "n": len(df), "folds": {}}
FOLDS = {"A(학습~2025-12 → 2026-01~)": ("2025-12-31", "2026-01-01"), "B(학습~2026-03 → 2026-04~)": ("2026-03-31", "2026-04-01")}
params = dict(loss="absolute_error", max_iter=300, learning_rate=0.04, max_depth=5, min_samples_leaf=120, l2_regularization=2.0, random_state=0)
for nm, (tr_end, te_start) in FOLDS.items():
    tr = (df.cutoff <= tr_end).values; te = (df.cutoff >= te_start).values
    if tr.sum() < 500 or te.sum() < 200: print(nm, "표본 부족", tr.sum(), te.sum()); continue
    m = HistGradientBoostingRegressor(**params).fit(X[tr], df.y[tr])
    p = m.predict(X[te])
    d2 = df[te].copy(); d2["p"] = p
    res = {"학습": int(tr.sum()), "채점": int(te.sum()), "앱": metr(d2.y), "종합": metr(d2.y - d2.p)}
    for k in (0.5,):
        res["절반반영"] = metr(d2.y - k * d2.p)
    for g in ("cls", "tier"):
        res["by_" + g] = {str(v): {"앱": metr(s.y), "종합": metr(s.y - s.p)} for v, s in d2.groupby(g)}
    res["by_cutoff"] = {str(v): {"앱": metr(s.y), "종합": metr(s.y - s.p)} for v, s in d2.groupby("cutoff")}
    out["folds"][nm] = res
    print("==", nm, res["학습"], res["채점"]); print(" 앱", res["앱"]); print(" 종합", res["종합"]); print(" 절반", res["절반반영"])
    for g in ("cls", "tier", "cutoff"):
        for v, o in res["by_" + g].items(): print("  ", g, v, "앱", o["앱"], "종합", o["종합"])
if os.environ.get("EXPORT") == "1":
    # 전체 자료로 학습한 모델을 앱이 직접 계산할 수 있게 내보냄(트리 노드 배열). 검증: 같은 입력에 파이썬 예측과 같은 값이어야 함
    mm = HistGradientBoostingRegressor(**params).fit(X, df.y)
    trees = []
    for it in mm._predictors:
        nd = it[0].nodes
        trees.append([[-1 if n["is_leaf"] else int(n["feature_idx"]), min(1e30, max(-1e30, float(n["num_threshold"]))), int(n["left"]), int(n["right"]), 1 if n["missing_go_to_left"] else 0, round(float(n["value"]), 6)] for n in nd])
    base = float(mm._baseline_prediction.ravel()[0])
    def walk(row):
        v = base
        for t in trees:
            i = 0
            while t[i][0] >= 0:
                f, th, l, r, ml, _ = t[i]; x = row[f]
                i = (l if ml else r) if x != x else (l if x <= th else r)
            v += t[i][5]
        return v
    smp = X.sample(2000, random_state=1); pyp = mm.predict(smp); myp = np.array([walk(r) for r in smp.values.astype(float)])
    print("내보내기 검증: 최대 차이", float(np.abs(pyp - myp).max()), "0.0005초과 비율", float((np.abs(pyp - myp) > 5e-4).mean()))
    exp = {"ver": 1, "feat": list(X.columns), "base": base, "trees": trees, "trainN": int(len(df)), "cutoffs": sorted(df.cutoff.unique().tolist()), "generatedAt": out["at"], "clip": [-0.3, 0.3],
           "oos": {k: v["종합"] for k, v in out["folds"].items()}, "oosApp": {k: v["앱"] for k, v in out["folds"].items()}}
    json.dump(exp, open("apt-stack.json", "w"), ensure_ascii=False, separators=(",", ":")); print("apt-stack.json", os.path.getsize("apt-stack.json") // 1024, "KB")
json.dump(out, open("apt-stack-eval.json", "w"), ensure_ascii=False)
if os.environ.get("SUPABASE_URL"):
    import importlib.util
    s = importlib.util.spec_from_file_location("cyc", os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyze-cycle.py")); cyc = importlib.util.module_from_spec(s); s.loader.exec_module(cyc)
    cyc.upsert_rows([{"id": "signal|__apt_stack_eval__", "payload": cyc.clean_json(out), "fetched_at": out["at"]}]); print("저장")
