"""
🏘️ 빌라 학습 자료량·기간 시험 - 병합·시험 단계 (2026-11-10): 여러 조각(feat-shard-*.pkl)을 합쳐 같은 시간순 교차 검증으로 비교. 설명은 backtest-villa-data-scale.py 참고.
"""
import glob, json, os
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
cols1 = ["r_e_bld", "r_e_dong", "r_e_dongw", "r_e_reg", "n_bld", "n_dong", "n_reg", "age_bld", "age_dong", "disp", "size", "floor", "age", "elv", "grnd", "hh", "lvl_c", "sido", "reg_code", "lbase", "r_e_rad300", "r_e_rad700", "r_e_rad1500", "n_rad300", "n_rad700", "n_rad1500", "r_lvl300", "r_lvl700", "r_lvl1500", "rad_disp", "rad_dist"]


def main():
    files = sorted(glob.glob(os.environ.get("SHARD_GLOB", "shards/**/feat-shard-*.pkl"), recursive=True)); print("조각 파일", len(files))
    D = pd.concat([pd.read_pickle(f) for f in files], ignore_index=True); print(f"합친 행 {len(D):,}건, 시험 {int(D['istest'].sum()):,}건")
    P = dict(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=60, l2_regularization=1.0, random_state=1)
    def lv(S): return S["lvl"]
    def pstat(e):
        a = np.abs(e); return {"n": int(len(e)), "오차%": round(float(np.median(a)) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "±20%": round(float((a <= .2).mean()) * 100, 1), "쏠림%": round(float(np.median(e)) * 100, 1)}
    folds = [("2024", 20240101, 20250101), ("2025", 20250101, 20260101), ("2026", 20260101, 99999999)]
    def run(name, start, size):
        es = []; byl = {}; byp = {}; used = []
        for fy, a_, b_ in folds:
            TE = D[D["istest"] & (D["deal_date"] >= a_) & (D["deal_date"] < b_)]
            TR = D[(~D["istest"]) & (D["deal_date"] >= start) & (D["deal_date"] < a_)]
            if len(TR) < 3000 or len(TE) < 500: continue
            if size and len(TR) > size: TR = TR.sample(size, random_state=3)
            used.append(len(TR))
            m = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(TR[cols1], TR["y"]); pr = m.predict(TE[cols1])
            e = TE["base"].values * np.exp(pr) / TE["actual"].values - 1; es.append(e)
            for l, G in TE.assign(e=e).groupby("lvl"):
                byl.setdefault(l, []).append(G["e"].values)
            pb = pd.cut(TE["actual"], [0, 8000, 15000, 1e9], labels=["8천만 미만", "8천~1.5억", "1.5억 이상"])
            for l, G in TE.assign(e=e).groupby(pb, observed=True):
                byp.setdefault(str(l), []).append(G["e"].values)
        if not es: return None
        o = {"학습 표본(구간별)": used, "전체": pstat(np.concatenate(es))}
        o["단계별"] = {l: pstat(np.concatenate(v)) for l, v in byl.items() if sum(map(len, v)) >= 200}
        o["가격대별"] = {l: pstat(np.concatenate(v)) for l, v in byp.items() if sum(map(len, v)) >= 200}
        print(name, json.dumps({"학습": used, **o["전체"]}, ensure_ascii=False)); return o
    out = {"시험": int(D["istest"].sum()), "자료량(2023~, 표본 수)": {}, "기간(표본 5만, 시작 연도)": {}}
    for nm, size in (("5만", 50000), ("10만", 100000), ("20만", 200000), ("전부", None)):
        out["자료량(2023~, 표본 수)"][nm] = run("자료량 " + nm, 20230101, size)
    for nm, st in (("2023~", 20230101), ("2021~", 20210101), ("2019~", 20190101), ("2017~", 20170901)):
        out["기간(표본 5만, 시작 연도)"][nm] = run("기간 " + nm, st, 50000)
    print(json.dumps(out, ensure_ascii=False, indent=1)); json.dump(out, open("villa-data-scale.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
