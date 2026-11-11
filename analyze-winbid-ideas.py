"""
🧪 낙찰가 개선 시도 4·5 (2026-11-11, 측정 전용) - 입력은 앱이 가진 객관 자료(과거 낙찰사례의 입찰자 수·결과)만
4. 같은 단지·동·시도의 '그 입찰일 이전' 낙찰 흐름(입찰자 수 수준·최근 변화·낙찰 건수·1·2등 가격 벌어짐)을 입력으로 → 입찰자 수 예측과 낙찰가 잔차가 나아지나
5. 후보(앱이 입찰 후보로 본 사건)에 가중을 줘서 학습하면 후보 정확도가 나아지나
시간순 분리: 입찰자 수 예측은 2025-10-30 이전 학습→이후 시험, 낙찰가 잔차는 시험 구간 안 앞 60%→뒤 40%. 감정가·최저가 미사용.
사용: python analyze-winbid-ideas.py <bidCases.json> <rows 폴더>
"""
import sys, json, glob, os, bisect
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
OOS = "2025-10-30"
cs = [c for c in json.load(open(sys.argv[1])) if isinstance(c, dict) and c.get("saleDate") and c.get("status") == "매각" and c.get("bidders") and c.get("propertyType") == "아파트"]
C = pd.DataFrame([{"id": c["id"], "sale": c["saleDate"], "bid": float(c["bidders"]), "court": c.get("court"), "dong": (c.get("addrJibun") or "").rsplit(" ", 1)[0] + "|" + str(c.get("dong") or ""), "cx": (c.get("addrJibun") or "") + "|" + str(c.get("bunji") or ""),
                   "gap": (np.log(c["finalBidPrice"] / c["secondBidPrice"]) if c.get("secondBidPrice") and c.get("finalBidPrice") and c["secondBidPrice"] > 0 else np.nan),
                   "area": c.get("areaM2"), "floor": c.get("floor"), "mon": int(c["saleDate"][5:7]), "sido": (c.get("addrJibun") or " ").split()[0], "minRate": c.get("minBidRate")} for c in cs])
C["lb"] = np.log(C["bid"]); C["d"] = pd.to_datetime(C["sale"]).map(pd.Timestamp.toordinal)
C = C.sort_values("d").reset_index(drop=True); print("아파트 낙찰 사례(입찰자 수 있음)", len(C))
# ── 과거 흐름 특징(그 사건 입찰일 '이전' 사건만) ──
def hist(key, win_days, name):
    n_a = np.full(len(C), np.nan); m_a = np.full(len(C), np.nan); t_a = np.full(len(C), np.nan); g_a = np.full(len(C), np.nan)
    for k, G in C.groupby(key):
        d = G["d"].values; lb = G["lb"].values; gp = G["gap"].values; idx = G.index.values
        for j in range(len(G)):
            lo = np.searchsorted(d, d[j] - win_days, side="left"); hi = np.searchsorted(d, d[j], side="left")   # 같은 날 제외(이전만)
            if hi > lo:
                n_a[idx[j]] = hi - lo; m_a[idx[j]] = lb[lo:hi].mean()
                mid = np.searchsorted(d, d[j] - win_days // 2, side="left")
                if hi > mid and mid > lo: t_a[idx[j]] = lb[mid:hi].mean() - lb[lo:mid].mean()
                g = gp[lo:hi]; g = g[~np.isnan(g)]
                if len(g): g_a[idx[j]] = g.mean()
            else: n_a[idx[j]] = 0
    C[name + "_n"] = n_a; C[name + "_lb"] = m_a; C[name + "_trend"] = t_a; C[name + "_gap"] = g_a
hist("cx", 730, "cx"); hist("dong", 365, "dn"); hist("sido", 90, "sd")   # 법원 열은 아파트 사례에 모두 비어 있어 시도 단위로 대신함
for col in ("court", "sido"): C[col + "_c"] = C[col].astype("category").cat.codes
flow = [c for c in C.columns if c.startswith(("cx_", "dn_", "sd_"))]
base = ["area", "floor", "mon", "court_c", "sido_c", "minRate"]
P = dict(loss="absolute_error", max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=40, l2_regularization=1.0, random_state=0)
tr = C[C.sale < OOS]; te = C[C.sale >= OOS]; out = {"학습 n": int(len(tr)), "시험 n": int(len(te))}
pred = {}
for nm, cols in (("기본 정보만", base), ("+ 낙찰 흐름(단지·동·시도)", base + flow)):
    m = HistGradientBoostingRegressor(**P).fit(tr[cols], tr["lb"]); p = m.predict(te[cols]); pred[nm] = (m, cols)
    out["입찰자 수 예측 - " + nm] = {"순위상관": round(float(spearmanr(p, te["lb"])[0]), 3), "로그오차 중앙": round(float(np.median(np.abs(p - te["lb"]))), 3)}
print(json.dumps(out, ensure_ascii=False, indent=1))
# ── 낙찰가 잔차 ──
rows = []
for f in glob.glob(os.path.join(sys.argv[2], "**", "rows.json"), recursive=True): rows += json.load(open(f))
R = pd.DataFrame([{"id": r["id"], "sale": r["saleDate"], "act": r["act"], "wbP": r["wbP"], "est": r["saleFinal"], "fails": r.get("fails"), "n6": r.get("n6"), "go": bool(r.get("go"))} for r in rows if not r.get("err") and r["saleDate"] >= OOS and r.get("wbP") and r.get("saleFinal") and r.get("act") and r["act"] > 0])
Ci = C.set_index("id"); R = R[R["id"].isin(Ci.index)].sort_values("sale").reset_index(drop=True)
for nm, (m, cols) in pred.items(): R["pb_" + nm] = m.predict(Ci.loc[R["id"], cols])
for c in flow: R[c] = Ci.loc[R["id"], c].values
R["res"] = np.log(R.act / R.wbP); k = int(len(R) * 0.6); t1, t2 = R.iloc[:k], R.iloc[k:]
mae = lambda x: round(float(np.median(np.abs(x))) * 100, 2)
P2 = dict(loss="absolute_error", max_iter=200, learning_rate=0.05, max_depth=4, min_samples_leaf=60, l2_regularization=1.0, random_state=0)
def bf(X): return pd.DataFrame({"fails": X["fails"], "n6": X["n6"], "lest": np.log(X["est"]), "lwb": np.log(X["wbP"] / X["est"])})
def run(extra, wgt=None, subset=None):
    F1 = pd.concat([bf(t1), t1[extra]], axis=1) if extra else bf(t1); F2 = pd.concat([bf(t2), t2[extra]], axis=1) if extra else bf(t2)
    m = HistGradientBoostingRegressor(**P2).fit(F1, t1["res"], sample_weight=(None if wgt is None else wgt(t1))); r = t2["res"].values - m.predict(F2)
    o = {"전체": mae(r), "유찰 3회+": mae(r[(t2["fails"] >= 3).values])}
    if subset is not None: o["후보"] = mae(r[subset(t2).values])
    return o
cand = lambda X: X["go"]
res = {"n(학습/시험)": [int(len(t1)), int(len(t2))], "후보 수(시험)": int(t2["go"].sum()), "현재 모델": {"전체": mae(t2["res"]), "유찰 3회+": mae(t2["res"][t2["fails"] >= 3]), "후보": mae(t2["res"][t2["go"]])},
       "잔차 학습(기본)": run([], subset=cand), "4. + 낙찰 흐름": run(flow, subset=cand), "4. + 예측 입찰자 수(흐름 포함)": run(["pb_+ 낙찰 흐름(단지·동·시도)"], subset=cand),
       "5. 후보 가중 3배(기본 입력)": run([], wgt=lambda X: np.where(X["go"], 3.0, 1.0), subset=cand), "5. 후보 가중 3배 + 낙찰 흐름": run(flow, wgt=lambda X: np.where(X["go"], 3.0, 1.0), subset=cand)}
out["낙찰가 오차%(시험 구간)"] = res; print(json.dumps(res, ensure_ascii=False, indent=1))
cov = {c: round(float(C.loc[C.sale >= OOS, c].notna().mean()), 2) for c in ("cx_lb", "dn_lb", "sd_lb")}; out["흐름 특징 채움 비율(시험)"] = cov; print(cov)
json.dump(out, open("winbid-ideas.json", "w"), ensure_ascii=False, indent=1)
