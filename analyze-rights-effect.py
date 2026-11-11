"""
⚖️ 권리분석이 진행되면 입찰자 수·낙찰가 예측이 얼마나 나아지나 (2026-11-11, 사용자: 입찰자 수 예측은 권리분석 영역 - 권리분석이 되면 어떨지 계산)
과거 사례에 기록된 권리 정보 = 낙찰사례의 '특이사항' 글(임차권등기·HUG 인수조건변경·대항력 있는 임차인·토지별도등기·대출 불리·미등기 등)뿐이라, 이걸 권리 태그로 바꿔
 A. 입찰자 수 예측(입찰 전 정보만): 권리 태그 없이 vs 있이 - 시간순 분리(2025-10-30 이전 학습 → 이후 시험)
 B. 낙찰가: 모델 잔차를 입찰자 수 예측값으로 설명 - (현재) / (+예측 입찰자 수, 권리 없이) / (+예측 입찰자 수, 권리 있이) / (실제 입찰자 수를 안다면 = 권리분석이 입찰자 수를 완벽히 맞히는 한계)
측정 전용. 감정가는 쓰지 않음(앱 원칙). 입력: bidCases 전체(JSON), 채점 사례 rows.json.
"""
import os, sys, json, glob, re
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
OOS = "2025-10-30"
cs = [c for c in json.load(open(sys.argv[1])) if isinstance(c, dict) and c.get("saleDate")]
TAGS = {"임차권등기": "임차권등기", "HUG인수조건": "인수조건변경", "대항력임차인": "대항력", "토지별도등기": "토지별도등기", "대출불리": "불리", "미등기": "미등기", "일괄매각": "일괄매각", "NPL": "NPL", "대지권미등기": "대지권미등기"}
def feat(c):
    sc = c.get("specialConditions") or ""; a = c.get("addrJibun") or ""
    f = {"area": c.get("areaM2"), "floor": c.get("floor"), "mon": int(c["saleDate"][5:7]), "court": c.get("court"), "sido": a.split()[0] if a else None, "ptype": c.get("propertyType"), "minRate": c.get("minBidRate")}
    t = {k: int(p in sc) for k, p in TAGS.items()}; t["hasSC"] = int(bool(sc))
    return f, t
rows = []
for c in cs:
    if not c.get("bidders") or c.get("status") != "매각" or c["propertyType"] not in ("아파트",): continue
    f, t = feat(c); rows.append({"id": c["id"], "sale": c["saleDate"], "bid": float(c["bidders"]), **f, **t})
A = pd.DataFrame(rows).sort_values("sale").reset_index(drop=True)
for col in ("court", "sido", "ptype"): A[col] = A[col].astype("category").cat.codes
A["lb"] = np.log(A["bid"])
print("아파트 입찰자 수 사례", len(A), "특이사항 있는 비율", round(A.hasSC.mean(), 2), {k: round(float(A[k].mean()), 3) for k in list(TAGS)})
base_cols = ["area", "floor", "mon", "court", "sido", "minRate"]; tag_cols = list(TAGS) + ["hasSC"]
P = dict(loss="absolute_error", max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=40, l2_regularization=1.0, random_state=0)
tr = A[A.sale < OOS]; te = A[A.sale >= OOS]
out = {"학습 n": int(len(tr)), "시험 n": int(len(te))}
pred = {}
for nm, cols in (("권리 없이", base_cols), ("권리 태그 포함", base_cols + tag_cols)):
    m = HistGradientBoostingRegressor(**P).fit(tr[cols], tr["lb"]); p = m.predict(te[cols]); pred[nm] = (m, p, cols)
    out["입찰자 수 예측 - " + nm] = {"순위상관": round(float(spearmanr(p, te["lb"])[0]), 3), "로그오차 중앙": round(float(np.median(np.abs(p - te["lb"]))), 3)}
print(json.dumps(out, ensure_ascii=False, indent=1))
# B. 낙찰가 잔차
rows2 = []
for f in glob.glob(os.path.join(sys.argv[2], "**", "rows.json"), recursive=True): rows2 += json.load(open(f))
R = [r for r in rows2 if not r.get("err") and r["saleDate"] >= OOS and r.get("wbP") and r.get("saleFinal") and r.get("act") and r["act"] > 0]
Rd = pd.DataFrame([{"id": r["id"], "sale": r["saleDate"], "act": r["act"], "wbP": r["wbP"], "est": r["saleFinal"], "fails": r.get("fails"), "n6": r.get("n6")} for r in R])
Ad = A.set_index("id")
Rd = Rd[Rd["id"].isin(Ad.index)].reset_index(drop=True)
for nm, (m, _, cols) in pred.items():
    Rd["pb_" + nm] = m.predict(Ad.loc[Rd["id"], cols])
Rd["bid"] = Ad.loc[Rd["id"], "lb"].values; Rd["res"] = np.log(Rd.act / Rd.wbP); Rd = Rd.sort_values("sale").reset_index(drop=True)
for k, p in TAGS.items(): Rd[k] = Ad.loc[Rd["id"], k].values
k = int(len(Rd) * 0.6); t1, t2 = Rd.iloc[:k], Rd.iloc[k:]
mae = lambda x: round(float(np.median(np.abs(x))) * 100, 2)
P2 = dict(loss="absolute_error", max_iter=200, learning_rate=0.05, max_depth=4, min_samples_leaf=60, l2_regularization=1.0, random_state=0)
def base_f(X): return pd.DataFrame({"fails": X["fails"], "n6": X["n6"], "lest": np.log(X["est"]), "lwb": np.log(X["wbP"] / X["est"])})
def run(extra):
    F1 = pd.concat([base_f(t1), t1[extra]], axis=1) if extra else base_f(t1); F2 = pd.concat([base_f(t2), t2[extra]], axis=1) if extra else base_f(t2)
    m = HistGradientBoostingRegressor(**P2).fit(F1, t1["res"]); r = t2["res"].values - m.predict(F2); lo = t2["fails"] >= 3
    return {"전체": mae(r), "유찰 3회+": mae(r[lo.values]), "n(전체/유찰3+)": [int(len(t2)), int(lo.sum())]}
b = {"현재 모델(추가 학습 없음)": {"전체": mae(t2["res"]), "유찰 3회+": mae(t2["res"][t2["fails"] >= 3])}, "입찰 전 정보로 잔차 학습": run([]),
     "+ 권리 태그만": run(list(TAGS)), "+ 예측 입찰자 수(권리 없이)": run(["pb_권리 없이"]), "+ 예측 입찰자 수(권리 포함)": run(["pb_권리 태그 포함"]),
     "+ 실제 입찰자 수(권리분석이 입찰자 수를 완벽히 맞힐 때의 한계)": run(["bid"])}
out["낙찰가 오차%(시험 구간)"] = b
# 태그별 입찰자 수·잔차 차이(요약)
tg = {}
for k2 in TAGS:
    m1 = A[k2] == 1
    if m1.sum() >= 80: tg[k2] = {"n": int(m1.sum()), "입찰자 수 중앙(있음/없음)": [float(A[m1].bid.median()), float(A[~m1].bid.median())]}
out["권리 태그별 입찰자 수"] = tg
print(json.dumps(b, ensure_ascii=False, indent=1)); print(json.dumps(tg, ensure_ascii=False))
json.dump(out, open("rights-effect.json", "w"), ensure_ascii=False, indent=1)
