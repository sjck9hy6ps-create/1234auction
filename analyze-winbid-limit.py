"""
🎯 예상 낙찰가 한계 진단 (2026-11-11, 사용자: 낙찰가도 천장인가) - 측정 전용
입력: 채점 사례 rows.json(앱이 입찰 35일 전 자료로 낸 예상 낙찰가 wbP, 예상 매도가 saleFinal, 실제 낙찰가 act), 낙찰사례 API(입찰자 수 등). 학습에 안 쓴 2025-10-30 이후 사례만.
① 오차가 어디서 생기나: 낙찰가÷예상매도가(낙찰 비율)의 흩어짐 vs 모델이 설명하고 남은 흩어짐 - 입찰자 수·유찰·지역·시점별
② 사후 정보를 넣으면 얼마나 줄어드나(한계 추정): 입찰자 수(입찰 전엔 모름)를 알면 오차가 얼마나 줄어드는지 = 입찰자 수가 오차의 몇 %를 설명하는지
③ 입찰 전에 아는 정보(유찰 횟수, 시세 근거 건수, 지역, 시점, 시세 수준)만으로 잔차를 더 줄일 수 있는지: 시간순 분리로 잔차 학습 시험
감정가·최저가는 쓰지 않음(앱 원칙).
"""
import os, json, glob
import numpy as np, pandas as pd, requests
from sklearn.ensemble import HistGradientBoostingRegressor
OOS = "2025-10-30"
rows = []
for f in glob.glob(os.path.join(os.environ.get("ROWS_DIR", "."), "**", "rows.json"), recursive=True): rows += json.load(open(f))
cases = {c["id"]: c for c in requests.get(os.environ.get("SITE_URL", "https://1234auction.vercel.app") + "/api/auction?kind=bidCases", timeout=180).json() if isinstance(c, dict) and c.get("id")}
R = []
for r in rows:
    if r.get("err") or r["saleDate"] < OOS or not r.get("wbP") or not r.get("saleFinal") or not r.get("act") or r["act"] <= 0: continue
    c = cases.get(r["id"], {})
    R.append({"id": r["id"], "sale": r["saleDate"], "act": r["act"], "wbP": r["wbP"], "est": r["saleFinal"], "fails": r.get("fails"), "n6": r.get("n6"), "lawd": str(r["lawd"]), "bidders": c.get("bidders"), "mktN": r.get("mktN")})
D = pd.DataFrame(R).sort_values("sale").reset_index(drop=True)
D["lr"] = np.log(D["act"] / D["est"]); D["res"] = np.log(D["act"] / D["wbP"])
D["cls"] = np.where(D["lawd"].str[:2] == "11", "서울", np.where(D["lawd"].str[:2].isin(["28", "41"]), "경기·인천", "지방"))
D["month"] = D["sale"].str[:7]; D["sido"] = D["lawd"].str[:2].astype(int)
print("사례", len(D), "입찰자 수 있는 것", int(D["bidders"].notna().sum()))
mad = lambda x: round(float(np.median(np.abs(np.asarray(x) - np.median(x)))) * 100, 2)
mae = lambda x: round(float(np.median(np.abs(x))) * 100, 2)
out = {"n": int(len(D)), "낙찰 비율(낙찰가÷예상매도가) 흩어짐(중앙 절대편차%)": mad(D["lr"]), "모델 잔차 중앙 오차%": mae(D["res"]), "모델 잔차 쏠림%": round(float(np.median(D["res"])) * 100, 2)}
out["설명한 비율%"] = round((1 - out["모델 잔차 중앙 오차%"] / out["낙찰 비율(낙찰가÷예상매도가) 흩어짐(중앙 절대편차%)"]) * 100, 1)
def grp(col, bins=None, labels=None, minn=40):
    S = D[D[col].notna()].copy()
    if bins is not None: S["g"] = pd.cut(S[col], bins, labels=labels)
    else: S["g"] = S[col]
    return {str(k): {"n": int(len(G)), "낙찰비율 흩어짐%": mad(G["lr"]), "잔차 오차%": mae(G["res"]), "잔차 쏠림%": round(float(np.median(G["res"])) * 100, 1)} for k, G in S.groupby("g", observed=True) if len(G) >= minn}
out["입찰자 수별"] = grp("bidders", [0, 1, 3, 5, 8, 12, 999], ["1명", "2~3명", "4~5명", "6~8명", "9~12명", "13명+"])
out["유찰 횟수별"] = grp("fails", [-1, 0, 1, 2, 99], ["신건", "1회", "2회", "3회+"])
out["지역별"] = grp("cls"); out["월별"] = grp("month", minn=80)
out["시세 근거(6개월 동일평형 거래) 건수별"] = grp("n6", [-1, 0, 2, 5, 999], ["0건", "1~2건", "3~5건", "6건+"])
# ② 입찰자 수를 알면 (사후 정보 - 한계 추정): 시간순 앞 60% 학습, 뒤 40% 시험
S = D[D["bidders"].notna()].reset_index(drop=True); k = int(len(S) * 0.6); tr, te = S.iloc[:k], S.iloc[k:]
P = dict(loss="absolute_error", max_iter=200, learning_rate=0.05, max_depth=4, min_samples_leaf=60, l2_regularization=1.0, random_state=0)
def feats(X, with_bid):
    F = pd.DataFrame({"fails": X["fails"], "n6": X["n6"], "sido": X["sido"], "lest": np.log(X["est"]), "lwb": np.log(X["wbP"] / X["est"]), "mon": pd.to_datetime(X["sale"]).dt.month})
    if with_bid: F["bidders"] = X["bidders"]
    return F
def test(with_bid):
    m = HistGradientBoostingRegressor(**P).fit(feats(tr, with_bid), tr["res"]); r2 = te["res"].values - m.predict(feats(te, with_bid)); return mae(r2)
out["잔차 학습 시험(시간순)"] = {"학습 n": int(len(tr)), "시험 n": int(len(te)), "현재 모델 잔차 오차%(시험 구간)": mae(te["res"]),
    "입찰 전 정보로 잔차를 더 학습": test(False), "입찰자 수(사후 정보)까지 넣으면": test(True)}
b = out["잔차 학습 시험(시간순)"]
b["입찰자 수가 설명하는 오차%"] = round((1 - b["입찰자 수(사후 정보)까지 넣으면"] / b["입찰 전 정보로 잔차를 더 학습"]) * 100, 1)
b["입찰 전 정보로 추가로 줄어드는 오차%"] = round((1 - b["입찰 전 정보로 잔차를 더 학습"] / b["현재 모델 잔차 오차%(시험 구간)"]) * 100, 1)
print(json.dumps(out, ensure_ascii=False, indent=1)); json.dump(out, open("winbid-limit.json", "w"), ensure_ascii=False, indent=1)
