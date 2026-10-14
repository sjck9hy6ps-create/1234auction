"""
🏗️ 신축 제외 시험 (2026-10-14, 사용자: "빌라 시세 측정에서 가장 중요한 건 신축 제외 - 신축은 입찰 안 하고, 포함되면 거래가격 전체에 오차가 쌓임. 시장은 3년 이내를 신축으로 보지만 나는 4년 이내")
비교 거래에서 '거래 시점 건물 나이 ≤ N년(사용승인연도 기준)'인 신축 거래를 빼면, 신축이 아닌 물건(입찰 대상)의 예상매도가 오차가 얼마나 줄어드는지.
시험 대상: 2025년 이후 거래 중 신축이 아닌 것(건물 나이 5년+, 또는 나이를 모르는 것은 따로) · 기존 예상 방식(backtest-villa.estimate) 그대로, 비교 거래 풀만 바꿈.
"""
import os, json, importlib.util
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); avm = bv.avm
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
N_TEST = int(os.environ.get("N_TEST", "8000"))

def stat(E):
    if E is None or not len(E): return None
    e = E["est"] / E["actual"] - 1; a = e.abs()
    return {"n": int(len(E)), "medAbsErrPct": round(float(a.median()) * 100, 2), "within10Pct": round(float((a <= .10).mean()) * 100, 1), "within20Pct": round(float((a <= .20).mean()) * 100, 1),
            "p10": round(float(e.quantile(.1)) * 100, 1), "p90": round(float(e.quantile(.9)) * 100, 1), "biasPct": round(float(e.median()) * 100, 2)}

def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
    df = bv.prep(raw)
    df["age"] = (df["deal_date"] // 10000) - df["build_year"].where(df["build_year"].between(1960, 2027))
    print(f"거래 {len(df):,}건 · 건물 나이 아는 비율 {df['age'].notna().mean() * 100:.1f}% · 4년 이하(신축) 비율 {(df['age'] <= 4).mean() * 100:.1f}%")
    te_all = df[df["deal_date"] >= 20250101]
    groups = {"신축 아닌 물건(나이 5년+)": te_all[te_all["age"] >= 5], "신축(4년 이하) 물건": te_all[te_all["age"] <= 4], "나이 모르는 물건": te_all[te_all["age"].isna()]}
    out = {"신축 비율%": round(float((df["age"] <= 4).mean()) * 100, 1), "나이 아는 비율%": round(float(df["age"].notna().mean()) * 100, 1)}
    samples = {k: (G.sample(min(N_TEST, len(G)), random_state=7) if len(G) > N_TEST else G) for k, G in groups.items()}
    pools = {"기존(신축 포함)": df}
    for n in (3, 4, 5): pools[f"신축 {n}년 이하 제외"] = df[~(df["age"] <= n)]
    print({k: len(v) for k, v in samples.items()}, flush=True)
    for gname, T in samples.items():
        out[gname] = {}
        for pname, pool in pools.items():
            if len(T) == 0: continue
            E = bv.estimate(pool, T)
            if E is None or len(E) == 0 or "tadj" not in E.columns: print(f"[{gname}] {pname}: 예상 결과 없음(대상 {len(T)}건)", flush=True); continue
            E = E[(E["tadj"] == 0) & (E["q"] == 0.5)]
            r = {"전체": stat(E)}
            for lvl, G in E.groupby("lvl"):
                if len(G) >= 80: r["단계 " + lvl] = stat(G)
            out[gname][pname] = r
            print(f"[{gname}] {pname}: {json.dumps(r['전체'], ensure_ascii=False)}", flush=True)
    txt = json.dumps(out, ensure_ascii=False, indent=1); json.dump(out, open("backtest-villa-newbuild.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")

if __name__ == "__main__":
    main()
