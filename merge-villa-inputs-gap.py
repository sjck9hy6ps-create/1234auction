"""
🏘️ 빌라 시세 입력 자료 부족 진단 (2026-11-11, 사용자: 입력자료를 늘리는 쪽) - 오차 큰 곳(시군구·동1~4건 단계, 저가)에서 어떤 입력이 비어 있고, 채우면 얼마나 나아질지 측정(측정 전용)
같은 조각 파일(시험 거래 23,976건, 각 거래 30일 전 기준)과 직전 24개월 종합 모델(시간순 6구간)로 계산.
 ① 대장 연결(승강기·세대수·지상층 등 건물 정보)이 있는/없는 거래의 오차 차이 → 연결률을 높이면 기대되는 개선
 ② 반경 근거(700m 안 면적 ±15㎡ 거래 3건 이상)가 있는/없는 거래의 오차 차이 → 반경을 더 넓히거나 생활권을 보완하면 기대되는 개선
 ③ 근거 단계가 약한 거래에서 반경 근거만으로 낸 값(e_rad)과 기준값·종합 모델의 오차 비교
"""
import glob, json, os
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from merge_cols import cols1
P = dict(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=60, l2_regularization=1.0, random_state=1)
FOLDS = [(20240101, 20240701), (20240701, 20250101), (20250101, 20250701), (20250701, 20260101), (20260101, 20260701), (20260701, 99999999)]


def mb(d, k):
    t = (d // 10000) * 12 + ((d // 100) % 100 - 1) - k; return (t // 12) * 10000 + (t % 12 + 1) * 100 + 1


def med(x): return round(float(np.median(x)) * 100, 2) if len(x) else None


def main():
    files = sorted(glob.glob(os.environ.get("SHARD_GLOB", "shards/**/feat-shard-*.pkl"), recursive=True))
    D = pd.concat([pd.read_pickle(f) for f in files], ignore_index=True)
    outs = []
    for a_, b_ in FOLDS:
        TE = D[D["istest"] & (D["deal_date"] >= a_) & (D["deal_date"] < b_)].copy(); TR = D[(~D["istest"]) & (D["deal_date"] < a_) & (D["deal_date"] >= mb(a_, 24))]
        if len(TE) < 300 or len(TR) < 3000: continue
        m = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(TR[cols1], TR["y"])
        TE["stack"] = np.abs(TE["base"].values * np.exp(m.predict(TE[cols1])) / TE["actual"].values - 1); outs.append(TE)
    T = pd.concat(outs); T["base_e"] = np.abs(T["base"] / T["actual"] - 1)
    T["rad_est"] = T["base"] * np.exp(T["r_e_rad700"]); T["rad_e"] = np.abs(T["rad_est"] / T["actual"] - 1)
    T["rad1500_est"] = T["base"] * np.exp(T["r_e_rad1500"]); T["rad1500_e"] = np.abs(T["rad1500_est"] / T["actual"] - 1)
    T["linked"] = T["elv"].notna(); T["hh_ok"] = T["hh"].notna(); T["rad"] = T["n_rad700"].fillna(0) >= 3; T["rad15"] = T["n_rad1500"].fillna(0) >= 3
    T["pb"] = pd.cut(T["base"], [0, 8000, 15000, 1e9], labels=["8천만 미만", "8천~1.5억", "1.5억 이상"]).astype(str)
    res = {"n": int(len(T)), "전체 연결률%": round(T["linked"].mean() * 100, 1), "전체 반경700 근거%": round(T["rad"].mean() * 100, 1), "전체 반경1.5km 근거%": round(T["rad15"].mean() * 100, 1)}
    def grp(G):
        o = {"n": int(len(G)), "기준값 오차%": med(G["base_e"]), "종합모델 오차%": med(G["stack"]), "대장 연결%": round(G["linked"].mean() * 100, 1), "반경700 근거%": round(G["rad"].mean() * 100, 1)}
        for nm, col in (("대장 연결", "linked"), ("반경700 근거", "rad"), ("반경1.5km 근거", "rad15")):
            for v, lab in ((True, "있음"), (False, "없음")):
                H = G[G[col] == v]
                if len(H) >= 40: o[f"{nm} {lab}(n={len(H)}) 종합오차%"] = med(H["stack"])
        H = G[G["rad"]]
        if len(H) >= 40: o["반경만으로 낸 값 오차%(반경O만)"] = med(H["rad_e"]); o["같은 거래 기준값 오차%"] = med(H["base_e"]); o["같은 거래 종합오차%"] = med(H["stack"])
        return o
    res["단계별"] = {l: grp(G) for l, G in T.groupby("lvl") if len(G) >= 200}
    res["가격대별"] = {l: grp(G) for l, G in T.groupby("pb")}
    res["전체"] = grp(T)
    # 연결 안 된 거래의 지역 분포(어디가 비는가)
    res["대장 미연결 시군구 상위"] = {str(k): int(v) for k, v in T[~T["linked"]]["region"].value_counts().head(12).items()}
    res["시군구별 대장 연결률 하위(거래 100건+)"] = {str(k): round(float(v) * 100, 1) for k, v in T.groupby("region")["linked"].agg(lambda s: s.mean() if len(s) >= 100 else np.nan).dropna().sort_values().head(12).items()}
    print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("villa-inputs-gap.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
