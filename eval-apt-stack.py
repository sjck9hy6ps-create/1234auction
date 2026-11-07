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
json.dump(out, open("apt-stack-eval.json", "w"), ensure_ascii=False)
if os.environ.get("SUPABASE_URL"):
    import importlib.util
    s = importlib.util.spec_from_file_location("cyc", os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyze-cycle.py")); cyc = importlib.util.module_from_spec(s); s.loader.exec_module(cyc)
    cyc.upsert_rows([{"id": "signal|__apt_stack_eval__", "payload": cyc.clean_json(out), "fetched_at": out["at"]}]); print("저장")
