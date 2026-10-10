"""
🏘️ 빌라 예상매도가: 같은 집 중복 거래 정리 + 건물 거래가 적을 때 동 평균과 섞기 (2026-10-10, 사용자: 미영팰리스 - 같은 호실이 8일 간격 같은 값으로 2번 잡혀 시세가 터무니없이 높게 나옴)
변형: A 기존 / B 같은 건물·같은 층·같은 면적·가격 3% 이내 45일 안 중복을 1건으로 / C B + 같은 건물 거래 5건 미만이면 같은 동 값과 50:50 / D B + 4건 미만이면 50:50
같은 시험 표본(중복 제거 후 거래)으로 비교. 결과: 보통 오차·±10%·±20%·상하위 10%, '건물 거래 3~4건' 하위집단
"""
import os, json, re, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "backtest-villa.py"), encoding="utf-8").read()
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm

def make_estimate(n_strong):
    code = src.replace("if n1 >= 3: p, lvl = v1, \"건물3+\"", f"if n1 >= {n_strong}: p, lvl = v1, \"건물3+\"")
    code = code.replace("elif n1 >= 1 and v2 is not None: p, lvl = 0.5 * v1 + 0.5 * v2, \"건물1~2+동\"", "elif n1 >= 1 and v2 is not None: p, lvl = 0.5 * v1 + 0.5 * v2, \"건물1~2+동\"")
    ns = {}
    exec(compile(code.split("def main():")[0], "bvmod", "exec"), {"__name__": "bvmod", "__file__": os.path.join(HERE, "backtest-villa.py")}, ns)
    return ns["estimate"]

FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
def dedupe(df):
    d = df.sort_values(["bld", "floor", "size", "day"]).copy()
    prev = d.groupby(["bld", "floor", "size"])
    d["pday"] = prev["day"].shift(1); d["pp"] = prev["price"].shift(1)
    dup = (d["day"] - d["pday"] <= 45) & ((d["price"] / d["pp"] - 1).abs() <= 0.03)
    print(f"중복 거래 {int(dup.sum()):,}건 ({dup.mean() * 100:.2f}%)")
    return df.loc[d.index[~dup.fillna(False)]].sort_values("day").reset_index(drop=True)

def stat(G):
    e = G["est"] / G["actual"] - 1; a = e.abs()
    return {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 1), "within10Pct": round(float((a <= .1).mean()) * 100, 1), "within20Pct": round(float((a <= .2).mean()) * 100, 1),
            "p10": round(float(e.quantile(.1)) * 100, 1), "p90": round(float(e.quantile(.9)) * 100, 1), "biasPct": round(float(e.median()) * 100, 1)}

def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
    df = bv.prep(raw); dd = dedupe(df)
    T = dd[dd["deal_date"] >= bv.TEST_FROM]
    if len(T) > 15000: T = T.sample(15000, random_state=7)
    print(f"시험 {len(T):,}건")
    res = {}
    def run(name, d, T_, n_strong=3, blend=False):
        est = make_estimate(n_strong)
        E = est(d, T_); E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].copy()
        E["actual"] = d.loc[E["i"].values, "price"].values
        res[name] = {"전체": stat(E)}
        for l, G in E.groupby("lvl"):
            if len(G) >= 50: res[name][l] = stat(G)
        return E
    # 시험 표본이 중복 제거 데이터의 부분집합이라 원본 인덱스가 다름 → 원본에서 같은 행을 찾아 비교하려면 키로 맞춤
    keyc = ["bld", "floor", "size", "day", "price"]
    Tk = T[keyc].copy(); Tk["k"] = 1
    Tori = df.merge(Tk, on=keyc, how="inner")
    Tori = Tori.drop_duplicates(keyc)
    run("A 기존(중복 포함 자료)", df, df[df.set_index(keyc).index.isin(Tk.set_index(keyc).index)])
    run("B 중복 정리", dd, T)
    run("C 중복 정리 + 건물 5건 미만은 동 값과 섞기", dd, T, n_strong=5)
    run("D 중복 정리 + 건물 4건 미만은 동 값과 섞기", dd, T, n_strong=4)
    txt = json.dumps(res, ensure_ascii=False, indent=1); print(txt)
    json.dump(res, open("backtest-villa-dedupe.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")

if __name__ == "__main__":
    main()
