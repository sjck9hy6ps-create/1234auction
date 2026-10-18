"""
🔬 아파트 예상매도가에 '전세가'를 쓰면 정확해지나 (2026-10-18, 사용자: 전세가격을 반영해서 정확도를 높여줘)
정답 = 시험 거래의 실제 가격. 직전 정보(같은 단지·같은 평형 ±3㎡의 중개 매매·순수 전세(월세 0))만 사용. 2025년~ 거래.
 E0  기준: 같은 단지·같은 평형 36개월 매매, 반감 3개월 가중 중위값(시세 지수 없음)
 EJ  전세 추정: 최근 6개월 같은 평형 전세 보증금 중위값 × 이 단지의 과거 '매매÷전세' 비율(6~30개월 전, 6개월 창별 비율의 중위값)
 EB25/EB50  E0와 EJ 가중 평균(전세 비중 25%·50%)
 ET  추세: E0 × (최근 6개월 전세 ÷ 그 전 6개월 전세)^β, 변화 ±10%로 제한(β=0.3·0.5) - 매매가 뜸할 때 전세 변화로 오래된 매매가를 움직임
결과: 지역(서울·경기인천·지방) × 최근 6개월 매매 건수(0~2 / 3+) 구간별 오차·치우침
"""
import os, re, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
rng = np.random.default_rng(3)
MAX_TEST = int(os.environ.get("MAX_TEST", "30000"))


def cls_of(region):
    s = str(region or "").split(" ")[0]
    if s.startswith("서울"): return "서울"
    if s[:2] in ("경기", "인천"): return "경기·인천"
    return "지방"


def wmed(vals, w):
    o = np.argsort(vals); v = np.asarray(vals)[o]; ww = np.asarray(w)[o]
    c = (np.cumsum(ww) - 0.5 * ww) / ww.sum()
    return float(np.interp(0.5, c, v))


def main():
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20220101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10) & (tr["dealing_type"] != "직거래")]
    rt = avm.fetch_all_rows("house_rent", cols="region,dong,danji,deposit,monthly_rent,size,deal_date", extra_filter="&deal_date=gte.20211001")
    for c in ("deposit", "monthly_rent", "size", "deal_date"): rt[c] = pd.to_numeric(rt[c], errors="coerce")
    rt = rt.dropna(subset=["deposit", "size", "deal_date"]); rt = rt[(rt["monthly_rent"].fillna(0) == 0) & (rt["deposit"] > 0) & (rt["size"] > 10)]
    print(f"  매매 {len(tr):,}건 / 순수 전세 {len(rt):,}건")

    def prep(df):
        df["dk"] = df["dong"].map(ab.dong_key); df["rg"] = df["region"].map(ab.region_norm); df["dj"] = df["danji"].astype(str).str.strip()
        df["ts"] = pd.to_datetime(df["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); df = df.dropna(subset=["ts", "rg"])
        df["t"] = (df["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
        return df
    tr = prep(tr); rt = prep(rt)
    tr["cls"] = tr["region"].map(cls_of)
    rent_g = {k: (g["t"].values, g["size"].values, g["deposit"].values.astype(float)) for k, g in rt.sort_values("t").groupby(["rg", "dk", "dj"])}
    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "dj"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    test = []
    for k, g in groups.items():
        if k not in rent_g: continue
        for i in np.where(g["t"].values >= t_start)[0]: test.append((k, i))
    print(f"  전세 자료가 있는 단지의 시험 후보 {len(test):,}건")
    sel = rng.choice(len(test), min(len(test), MAX_TEST), replace=False); test = [test[i] for i in sel]
    rows = []
    for k, i in test:
        g = groups[k]; T = g.iloc[i]
        H = g.iloc[:i]; H = H[H["t"] < T["t"]]
        sm = H[(H["size"] - T["size"]).abs() <= 3]
        if not len(sm): continue
        ag = (T["t"] - sm["t"].values) / 30.4; m36 = ag <= 36
        if m36.sum() < 1: continue
        price = sm["price"].values.astype(float)
        n6 = int((ag <= 6).sum())
        rec = dict(cls=T["cls"], n6=n6, actual=float(T["price"]))
        rec["E0"] = wmed(price[m36], 0.5 ** (ag[m36] / 3.0))
        # 앱의 현재 규칙(6개월 3건+): 서울 최근 3건 중위 / 경기·인천 반감 1개월 / 지방 반감 2개월 가중 중위
        m6 = ag <= 6
        if m6.sum() >= 3:
            p6 = price[m6]; a6 = ag[m6]
            if T["cls"] == "서울": rec["EA"] = float(np.median(p6[np.argsort(a6)[:3]]))
            elif T["cls"] == "경기·인천": rec["EA"] = wmed(p6, 0.5 ** (a6 / 1.0))
            else: rec["EA"] = wmed(p6, 0.5 ** (a6 / 2.0))
        rt_t, rt_s, rt_d = rent_g[k]
        keep = (np.abs(rt_s - T["size"]) <= 3) & (rt_t < T["t"])
        rag = (T["t"] - rt_t[keep]) / 30.4; rd = rt_d[keep]
        j6 = rd[rag <= 6]; jprev = rd[(rag > 6) & (rag <= 12)]
        if len(j6) >= 2:
            J = float(np.median(j6)); rec["J"] = J
            # 과거 매매÷전세 비율: 6~30개월 전 6개월 창
            ratios = []
            for lo in (6, 12, 18, 24):
                ps = price[(ag > lo) & (ag <= lo + 6)]; js = rd[(rag > lo) & (rag <= lo + 6)]
                if len(ps) >= 1 and len(js) >= 1: ratios.append(np.median(ps) / np.median(js))
            if ratios:
                rec["EJ"] = J * float(np.median(ratios)); rec["nr"] = len(ratios)
                rec["EB25"] = 0.75 * rec["E0"] + 0.25 * rec["EJ"]; rec["EB50"] = 0.5 * rec["E0"] + 0.5 * rec["EJ"]
            if len(jprev) >= 2:
                ch = float(np.clip(J / np.median(jprev) - 1, -0.10, 0.10)); rec["jch"] = ch
                rec["ET3"] = rec["E0"] * (1 + 0.3 * ch); rec["ET5"] = rec["E0"] * (1 + 0.5 * ch)
        rows.append(rec)
    D = pd.DataFrame(rows)
    D.to_json("backtest-sale-jeonse.json", orient="records", force_ascii=False)
    print(f"  시험 {len(D):,}건")
    report(D)
    write_params(D)


def line(d, c, base="E0"):
    x = d[d[c].notna() & d[base].notna()]
    if len(x) < 100: return None
    r = x["actual"] / x[c]
    return f"n{len(x):6,} 오차{np.median(np.abs(r - 1)) * 100:5.2f}% 치우침{(np.median(r) - 1) * 100:+6.2f}% 하방p25 {(r.quantile(.25) - 1) * 100:+6.1f}%"


def report(D):
    V = ["E0", "EJ", "EB25", "EB50", "ET3", "ET5"]
    # 같은 표본(전세 추정이 모두 있는 건)에서 비교
    for nm, m in (("전체", D.n6 >= 0), ("6개월 매매 0~2건", D.n6 < 3), ("6개월 매매 3건+", D.n6 >= 3)):
        for cls in ("서울", "경기·인천", "지방", None):
            d = D[m & ((D.cls == cls) if cls else True)]
            d = d[d["EJ"].notna() & d["ET3"].notna()]
            if len(d) < 200: continue
            print(f"\n[{cls or '전국'} · {nm}] 전세 자료 있는 표본 n{len(d):,}")
            for c in V:
                s = line(d, c)
                if s: print(f"   {c:5} {s}")


def build_params(D):
    """앱 현재 규칙(EA) 기준 - 같은 단지·같은 평형 최근 6개월 전세 보증금 중위값 ÷ 예상매도가(전세가율) 구간별 보정(bias)·하방(p25) 표"""
    X = D[D["J"].notna() & D["EA"].notna()].copy()
    if len(X) < 3000: return None
    X["ratio"] = X["J"] / X["EA"] * 100; X["r"] = X["actual"] / X["EA"] - 1
    cuts = [50, 60, 70, 80]
    X["rb"] = pd.cut(X["ratio"], [0] + cuts + [1000], labels=["0", "1", "2", "3", "4"])
    out = {"cuts": cuts, "n": int(len(X)), "table": {}}
    for cls in ("서울", "경기·인천", "지방"):
        out["table"][cls] = {}
        for b in ("0", "1", "2", "3", "4"):
            d = X[(X.cls == cls) & (X.rb == b)]
            if len(d) < 150: continue
            out["table"][cls][b] = {"bias": round(float(np.median(d["r"])), 4), "p25": round(float(d["r"].quantile(.25)), 4), "n": int(len(d))}
    return out


def write_params(D):
    if not os.environ.get("WRITE_PARAMS"): return
    from datetime import datetime, timezone
    P = build_params(D)
    if not P:
        print("  전세가율 표 만들기엔 표본이 부족해요 - 저장 안 함"); return
    P["generatedAt"] = datetime.now(timezone.utc).isoformat()
    P["basis"] = "앱 규칙 예상 대비 실제 거래가를 전세가율(최근 6개월 전세 보증금 중위값÷예상매도가) 구간별로 - 2025년~ 아파트, 직전 정보만"
    ab.cyc.upsert_rows([{"id": "signal|__salerule_jr__", "payload": ab.cyc.clean_json(P), "fetched_at": P["generatedAt"]}])
    print("  전세가율 표 저장:", P["cuts"], {c: list(v.keys()) for c, v in P["table"].items()})


if __name__ == "__main__":
    main()
