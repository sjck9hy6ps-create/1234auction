"""
🏘️ 빌라 시세 '확실성'(하위 10·25% 값의 포함률·여유폭) 시험 (2026-11-11, 사용자: 최근 2년·전체 거래 학습이면 오차의 확실성을 높일 수 있을 것)
같은 조각 파일로 점 보정 + 하위 10·25% 분위 모델을 학습 방식별로 비교. 포함률 = 실제 거래가가 그 값 이상인 비율(목표 90·75%). 여유폭 = 점 추정 대비 그 값이 얼마나 아래인지(작을수록 좋음 - 같은 포함률일 때).
방식: 2023년 이후 무작위 5만(지난 방식) / 직전 24개월 전부(이번 적용) / 직전 12개월 전부. 시험은 시간순 6구간(그 이전 거래로만 학습).
"""
import glob, json, os
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from merge_cols import cols1
P = dict(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=60, l2_regularization=1.0, random_state=1)
FOLDS = [(20240101, 20240701), (20240701, 20250101), (20250101, 20250701), (20250701, 20260101), (20260101, 20260701), (20260701, 99999999)]
PB = [0, 8000, 15000, 1e9]; PL = ["8천만 미만", "8천~1.5억", "1.5억 이상"]


def mb(d, k):
    t = (d // 10000) * 12 + ((d // 100) % 100 - 1) - k; return (t // 12) * 10000 + (t % 12 + 1) * 100 + 1


def main():
    files = sorted(glob.glob(os.environ.get("SHARD_GLOB", "shards/**/feat-shard-*.pkl"), recursive=True))
    D = pd.concat([pd.read_pickle(f) for f in files], ignore_index=True); D["pb"] = pd.cut(D["base"], PB, labels=PL).astype(str)
    cfgs = {"2023~ 무작위 5만(지난 방식)": lambda TR, a: (lambda T: T.sample(50000, random_state=3) if len(T) > 50000 else T)(TR[TR["deal_date"] >= 20230101]),
            "직전 24개월 전부(적용)": lambda TR, a: TR[TR["deal_date"] >= mb(a, 24)], "직전 12개월 전부": lambda TR, a: TR[TR["deal_date"] >= mb(a, 12)]}
    out = {}
    for name, f in cfgs.items():
        acc = {"pt": [], "q25": [], "q10": [], "pb": [], "lvl": []}; used = []
        for a_, b_ in FOLDS:
            TE = D[D["istest"] & (D["deal_date"] >= a_) & (D["deal_date"] < b_)]; TR = f(D[(~D["istest"]) & (D["deal_date"] < a_)], a_)
            if len(TE) < 300 or len(TR) < 3000: continue
            used.append(len(TR))
            pt = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(TR[cols1], TR["y"]).predict(TE[cols1])
            q25 = HistGradientBoostingRegressor(loss="quantile", quantile=0.25, **P).fit(TR[cols1], TR["y"]).predict(TE[cols1])
            q10 = HistGradientBoostingRegressor(loss="quantile", quantile=0.10, **P).fit(TR[cols1], TR["y"]).predict(TE[cols1])
            y = TE["y"].values
            acc["pt"].append(pt); acc["q25"].append(q25); acc["q10"].append(q10); acc["y"] = acc.get("y", []) + [y]; acc["pb"].append(TE["pb"].values); acc["lvl"].append(TE["lvl"].values)
        pt, q25, q10, y, pb, lv = [np.concatenate(acc[k]) for k in ("pt", "q25", "q10", "y", "pb", "lvl")]
        def st(m):
            return {"n": int(m.sum()), "점 오차%": round(float(np.median(np.abs(np.exp(pt[m] - y[m]) - 1))) * 100, 2), "25% 값 포함률%": round(float((y[m] >= q25[m]).mean()) * 100, 1), "25% 여유폭%": round(float(np.median(np.exp(pt[m]) / np.exp(q25[m]) - 1)) * 100, 1),
                    "10% 값 포함률%": round(float((y[m] >= q10[m]).mean()) * 100, 1), "10% 여유폭%": round(float(np.median(np.exp(pt[m]) / np.exp(q10[m]) - 1)) * 100, 1)}
        o = {"학습 표본(구간별)": used, "전체": st(np.ones(len(y), bool)), "가격대별": {l: st(pb == l) for l in PL}, "단계별": {l: st(lv == l) for l in sorted(set(lv)) if (lv == l).sum() >= 200}}
        out[name] = o; print(name, json.dumps(o["전체"], ensure_ascii=False), flush=True)
        for k in ("가격대별", "단계별"):
            for l, v in o[k].items(): print("   ", k, l, json.dumps(v, ensure_ascii=False), flush=True)
    json.dump(out, open("villa-interval.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
