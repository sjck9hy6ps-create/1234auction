"""지방 아파트 '단지별 쉬어가는 국면' 시험(2026-11-28, 측정 전용·앱 불변) - 실거래만으로 정답·입력.
정답: 단지 ㎡당 매매가(최근 3개월 거래 중앙)가 4~6개월 뒤(그 3개월 거래 중앙) 3% 이상 하락하면 '쉬어갈 국면'.
입력(그 달 말까지): 단지 3·6·12개월 가격 변화, 단지 거래량 변화, 단지 전세 6개월 변화·전세가율, 시군구 같은 지표.
평가: 연도별 하락 비율(신호 있음/없음), 시간순 모델(학습은 정답이 시험 시작 전에 확정된 달만) - 오늘 기준 3·6·9·12개월 구간."""
import os, re, json, importlib.util
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(s); s.loader.exec_module(bv); avm = bv.avm
NOT_METRO = "&and=(region.not.like.서울*,region.not.like.경기*,region.not.like.인천*)"
def nm(x): return re.sub(r"[^0-9A-Za-z가-힣]", "", avm.normalize_complex_name(x or "")).replace("아파트", "")
raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter="&deal_date=gte.20190101" + NOT_METRO)
T = bv.prep(raw); T["ym"] = pd.to_numeric(T["deal_date"]) // 100; T["mi"] = (T["ym"] // 100) * 12 + T["ym"] % 100 - 1
T["cx"] = T["region"].astype(str) + "|" + T["dong"].astype(str) + "|" + T["bunji"].astype(str); T["nmk"] = T["region"].astype(str) + "|" + T["dong"].astype(str).str.split().str[-1] + "|" + T["danji"].map(nm)
rr = avm.fetch_all_rows("house_rent", cols="region,dong,danji,deposit,size,deal_date", extra_filter="&deal_date=gte.20190101&monthly_rent=eq.0" + NOT_METRO)
for c in ("deposit", "size", "deal_date"): rr[c] = pd.to_numeric(rr[c], errors="coerce")
rr = rr.dropna(); rr = rr[rr["size"] > 10]; rr["jppm"] = rr["deposit"] / rr["size"]; rr["mi"] = (rr["deal_date"] // 10000) * 12 + (rr["deal_date"] // 100 % 100) - 1
rr["nmk"] = rr["region"].astype(str) + "|" + rr["dong"].astype(str).str.split().str[-1] + "|" + rr["danji"].map(nm)
cx2nm = T.groupby("cx")["nmk"].agg(lambda v: v.mode()[0]); rr["cx"] = rr["nmk"].map({v: k for k, v in cx2nm.items()})
print("매매", len(T), "전세", len(rr), "단지", T["cx"].nunique(), flush=True)
m0, m1 = int(T["mi"].min()), int(T["mi"].max())
L = m1 - m0 + 1
def panel(df, key, val):
    keys = df[key].dropna().unique(); kid = {k: i for i, k in enumerate(keys)}
    g = df.dropna(subset=[key]).groupby([key, "mi"])[val]
    S = np.zeros((len(keys), L)); N = np.zeros((len(keys), L))
    for (k, m), v in g: S[kid[k], m - m0] = np.median(v.values); N[kid[k], m - m0] = len(v)
    return keys, kid, S, N, g
def roll_med(df, key, val, keys, kid, w=3):
    """각 단지·달: 최근 w개월 거래 전체의 중앙값(거래 2건 미만이면 nan)"""
    out = np.full((len(keys), L), np.nan); cnt = np.zeros((len(keys), L))
    d = df.dropna(subset=[key])[[key, "mi", val]].copy(); d["i"] = d[key].map(kid); d = d.dropna(subset=["i"])
    for i, gg in d.groupby("i"):
        mi = gg["mi"].values - m0; v = gg[val].values; o = np.argsort(mi); mi = mi[o]; v = v[o]
        for t in range(L):
            lo = np.searchsorted(mi, t - w + 1); hi = np.searchsorted(mi, t, side="right")
            cnt[int(i), t] = hi - lo
            if hi - lo >= 2: out[int(i), t] = np.median(v[lo:hi])
    return out, cnt
keys = T["cx"].unique(); kid = {k: i for i, k in enumerate(keys)}
P, C = roll_med(T, "cx", "ppm", keys, kid, 3)
J, JC = roll_med(rr, "cx", "jppm", keys, kid, 3)
reg_of = T.groupby("cx")["region"].first().reindex(keys).values
regs = pd.unique(reg_of); rid = {r: i for i, r in enumerate(regs)}
T["rg"] = T["region"]; RP, RC = roll_med(T, "rg", "ppm", regs, rid, 3)
rr2 = rr.copy(); rr2["rg"] = rr2["region"]; RJ, _ = roll_med(rr2, "rg", "jppm", regs, rid, 3)
print("패널 완료", flush=True)
def chg(A, t, k): return A[:, t] / A[:, t - k] - 1
rows = []
for t in range(15, L - 6):
    fut = P[:, t + 6] / P[:, t] - 1
    ok = ~np.isnan(fut) & ~np.isnan(P[:, t])
    ri = np.array([rid[r] for r in reg_of])
    f = {"c3": chg(P, t, 3), "c6": chg(P, t, 6), "c12": chg(P, t, 12), "cv": C[:, t] / np.maximum(C[:, t - 6], 1) - 1, "cj6": chg(J, t, 6), "cjr": J[:, t] / P[:, t],
         "r6": (RP[:, t] / RP[:, t - 6] - 1)[ri], "r12": (RP[:, t] / RP[:, t - 12] - 1)[ri], "rj6": (RJ[:, t] / RJ[:, t - 6] - 1)[ri], "rjr": (RJ[:, t] / RP[:, t])[ri]}
    for i in np.where(ok)[0]:
        rows.append([t + m0, i] + [f[k][i] for k in ("c3", "c6", "c12", "cv", "cj6", "cjr", "r6", "r12", "rj6", "rjr")] + [fut[i]])
D = pd.DataFrame(rows, columns=["mi", "i", "c3", "c6", "c12", "cv", "cj6", "cjr", "r6", "r12", "rj6", "rjr", "fut"])
D["down"] = (D["fut"] <= -0.03).astype(int); D["yr"] = D["mi"] // 12
print("행", len(D), "하락(3%↓) 비율", round(D["down"].mean() * 100, 1), flush=True)
FE = ["c3", "c6", "c12", "cv", "cj6", "cjr", "r6", "r12", "rj6", "rjr"]
out = {"n": int(len(D)), "baseDown": float(D["down"].mean()), "byYearBase": D.groupby("yr")["down"].mean().round(3).to_dict()}
# ① 단일 신호: 연도별 하락 비율 (신호 칸별)
uni = {}
for k, cuts in (("c6", [-.03, 0, .03]), ("c12", [-.05, 0, .05]), ("cj6", [-.03, 0, .03]), ("cv", [-.3, 0, .3]), ("cjr", [.6, .7, .8]), ("r6", [-.02, 0, .02]), ("rj6", [-.02, 0, .02]), ("c3", [-.03, 0, .03])):
    b = pd.cut(D[k], [-np.inf] + cuts + [np.inf]); tab = D.groupby([b, "yr"], observed=True)["down"].agg(["mean", "size"])
    uni[k] = {f"{iv}": {str(int(y)): [round(float(r["mean"]), 3), int(r["size"])] for (iv2, y), r in tab.iterrows() if iv2 == iv} for iv in b.cat.categories}
out["single"] = uni
# ② 시간순 모델: 오늘 기준 3·6·9·12개월(정답이 확정되는 마지막 달 기준)
last = int(D["mi"].max()); res = {}
for k in (3, 6, 9, 12):
    cut = last - k + 1; tr = D[D["mi"] <= cut - 7]; te = D[D["mi"] >= cut]
    m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, random_state=0).fit(tr[FE], tr["down"])
    p = m.predict_proba(te[FE])[:, 1]; y = te["down"].values
    q80 = np.quantile(p, .8); q20 = np.quantile(p, .2)
    res[f"{k}개월"] = {"학습": int(len(tr)), "시험": int(len(te)), "AUC": round(float(roc_auc_score(y, p)), 3), "기본하락%": round(float(y.mean() * 100), 1),
                      "모델상위20%하락%": round(float(y[p >= q80].mean() * 100), 1), "모델하위20%하락%": round(float(y[p <= q20].mean() * 100), 1),
                      "상위20%평균변화%": round(float(te["fut"].values[p >= q80].mean() * 100), 2), "하위20%평균변화%": round(float(te["fut"].values[p <= q20].mean() * 100), 2)}
    print(k, res[f"{k}개월"], flush=True)
out["model"] = res
# ③ 연도별 시간순(전년까지 학습 → 그해 시험)
yr = {}
for y in sorted(D["yr"].unique())[2:]:
    tr = D[D["mi"] <= y * 12 - 7]; te = D[D["yr"] == y]
    if len(tr) < 5000 or len(te) < 1000: continue
    m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, random_state=0).fit(tr[FE], tr["down"])
    p = m.predict_proba(te[FE])[:, 1]; yv = te["down"].values; q80 = np.quantile(p, .8); q20 = np.quantile(p, .2)
    yr[str(int(y))] = {"AUC": round(float(roc_auc_score(yv, p)), 3), "기본": round(float(yv.mean() * 100), 1), "상위20%": round(float(yv[p >= q80].mean() * 100), 1), "하위20%": round(float(yv[p <= q20].mean() * 100), 1)}
    print(y, yr[str(int(y))], flush=True)
out["byYear"] = yr
json.dump(out, open("jibang-cxphase.json", "w"), ensure_ascii=False, indent=1)
print("완료", flush=True)
