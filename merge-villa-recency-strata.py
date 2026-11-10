"""
🏘️ 빌라 시세(예상 매도가) 학습 시험 2: 최근 기간 집중 + 약한 구간 표본 넓히기 (2026-11-11, 사용자 질문: 표본 분포를 넓히고 기간을 최근으로 당기는 건 의미 없나)
이미 계산된 조각(feat-shard-*.pkl, 각 거래의 '30일 전 기준' 입력)을 그대로 써서 DB·외부 호출 없이 학습 방식만 바꿔 비교한다. 목표는 시세 정확도(거래 가격 맞히기) - 낙찰가 아님.
시험: 시간순 6개 구간(2024 상/하, 2025 상/하, 2026 상/하) - 각 구간은 그 이전 거래만으로 학습.
 A 기준: 2023년 이후 전부 / 5만 무작위(지난 시험과 같은 방식)
 B 기간: 시험 직전 12·24·36개월만 / 최근일수록 가중(반감기 12·24개월)
 C 분포: 근거 단계별 균등 표본 5만 / 근거 단계×가격대 균등 5만(가격대는 모델 기준가 사용 - 정답 가격으로 뽑지 않음) / 역빈도 가중(전부 사용)
 D 결합: 직전 24개월 + 근거 단계별 균등
평가: 전체·근거 단계별·가격대별 중앙오차, ±10%, 쏠림. 측정 전용.
"""
import glob, json, os
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from merge_cols import cols1
P = dict(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=60, l2_regularization=1.0, random_state=1)
FOLDS = [(20240101, 20240701), (20240701, 20250101), (20250101, 20250701), (20250701, 20260101), (20260101, 20260701), (20260701, 99999999)]
PB = [0, 8000, 15000, 1e9]; PL = ["8천만 미만", "8천~1.5억", "1.5억 이상"]


def pstat(e):
    a = np.abs(e); return {"n": int(len(e)), "오차%": round(float(np.median(a)) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "±20%": round(float((a <= .2).mean()) * 100, 1), "쏠림%": round(float(np.median(e)) * 100, 1)}


def months_before(d, k):
    y, m = d // 10000, (d // 100) % 100
    t = y * 12 + (m - 1) - k
    return (t // 12) * 10000 + (t % 12 + 1) * 100 + 1


def age_months(d, ref):
    return (ref // 10000 - d // 10000) * 12 + ((ref // 100) % 100 - (d // 100) % 100)


def main():
    files = sorted(glob.glob(os.environ.get("SHARD_GLOB", "shards/**/feat-shard-*.pkl"), recursive=True)); print("조각 파일", len(files))
    D = pd.concat([pd.read_pickle(f) for f in files], ignore_index=True)
    D["pb"] = pd.cut(D["base"], PB, labels=PL).astype(str)
    print(f"행 {len(D):,}, 시험 표본 {int(D['istest'].sum()):,}")
    rng = np.random.RandomState(5)

    def strat_sample(TR, keys, n):
        g = TR.groupby(keys); k = max(1, n // max(1, g.ngroups)); parts = []
        for _, G in g:
            parts.append(G.sample(min(len(G), k), random_state=5))
        S = pd.concat(parts)
        if len(S) < n:   # 작은 층이 모자란 만큼 나머지 층에서 균등 보충
            rest = TR.drop(S.index); S = pd.concat([S, rest.sample(min(len(rest), n - len(S)), random_state=6)])
        return S

    def cfg_all(TR, a):   # 2023~ 전부
        return TR[TR["deal_date"] >= 20230101], None

    def cfg_rand5(TR, a):
        T = TR[TR["deal_date"] >= 20230101]; return (T.sample(50000, random_state=3) if len(T) > 50000 else T), None

    def win(k):
        return lambda TR, a: (TR[TR["deal_date"] >= months_before(a, k)], None)

    def decay(h):
        def f(TR, a):
            T = TR[TR["deal_date"] >= 20230101]; w = 0.5 ** (age_months(T["deal_date"].values, a) / h); return T, w
        return f
    cfg_lvl = lambda TR, a: (strat_sample(TR[TR["deal_date"] >= 20230101], ["lvl"], 50000), None)
    cfg_lvlp = lambda TR, a: (strat_sample(TR[TR["deal_date"] >= 20230101], ["lvl", "pb"], 50000), None)

    def cfg_invw(TR, a):
        T = TR[TR["deal_date"] >= 20230101]; c = T.groupby(["lvl", "pb"])["y"].transform("size").values.astype(float); w = 1.0 / np.sqrt(c); return T, w / w.mean()

    def cfg_comb(TR, a):
        T = TR[TR["deal_date"] >= months_before(a, 24)]; return strat_sample(T, ["lvl"], 50000), None
    cfgs = [("A1 2023~ 전부", cfg_all), ("A2 2023~ 무작위 5만(지난 방식)", cfg_rand5), ("B1 직전 12개월", win(12)), ("B2 직전 24개월", win(24)), ("B3 직전 36개월", win(36)),
            ("B4 최근 가중(반감기 12개월)", decay(12)), ("B5 최근 가중(반감기 24개월)", decay(24)),
            ("C1 근거 단계별 균등 5만", cfg_lvl), ("C2 근거 단계×가격대 균등 5만", cfg_lvlp), ("C3 단계×가격대 역빈도 가중(전부)", cfg_invw), ("D 직전 24개월+단계별 균등", cfg_comb)]
    res = {}; basee = []
    for name, f in cfgs:
        es = []; lv = {}; pr = {}; used = []; meta = []
        for a_, b_ in FOLDS:
            TE = D[D["istest"] & (D["deal_date"] >= a_) & (D["deal_date"] < b_)]
            TR0 = D[(~D["istest"]) & (D["deal_date"] < a_)]
            if len(TE) < 300 or len(TR0) < 3000: continue
            TR, w = f(TR0, a_)
            if len(TR) < 3000: continue
            m = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(TR[cols1], TR["y"], sample_weight=w)
            e = TE["base"].values * np.exp(m.predict(TE[cols1])) / TE["actual"].values - 1; es.append(e); used.append(len(TR))
            if name.startswith("A1"): basee.append(TE["base"].values / TE["actual"].values - 1)
            for l, G in TE.assign(e=e).groupby("lvl"): lv.setdefault(l, []).append(G["e"].values)
            for l, G in TE.assign(e=e).groupby(TE["pb"]): pr.setdefault(l, []).append(G["e"].values)
        o = {"학습 표본(구간별)": used, "전체": pstat(np.concatenate(es)),
             "단계별": {l: pstat(np.concatenate(v)) for l, v in lv.items() if sum(map(len, v)) >= 200},
             "가격대별": {l: pstat(np.concatenate(v)) for l, v in pr.items() if sum(map(len, v)) >= 200}}
        res[name] = o
        print(name, json.dumps({"학습": used, **o["전체"]}, ensure_ascii=False), flush=True)
    out = {"시험": int(D["istest"].sum()), "모델 도입 전(근거 거래 중앙값 그대로)": pstat(np.concatenate(basee)) if basee else None, "방식별": res}
    json.dump(out, open("villa-recency-strata.json", "w"), ensure_ascii=False, indent=1)
    print("요약(전체 / 가격대별 오차% / 단계별 오차%)")
    for k, o in res.items():
        print(k, o["전체"]["오차%"], o["전체"]["±10%"], o["전체"]["쏠림%"], "| 가격대", {a: b["오차%"] for a, b in o["가격대별"].items()}, "| 단계", {a: b["오차%"] for a, b in o["단계별"].items()})


if __name__ == "__main__":
    main()
