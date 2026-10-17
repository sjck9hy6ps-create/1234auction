"""
🔬 예상매도가 규칙 비교 - 지역(서울·경기인천·지방) × 회전율 × 거래량 (2026-10-17, 사용자: "서울은 3개월 3건 이상이 거의 모든 아파트 / 거래량·회전율로 최근거래 비중을 달리")
낙찰 되팔기 표본(3,284건)은 거의 전부 지방이라 서울·수도권은 검증된 적이 없었음 → 전체 아파트 실거래로 비교함:
 각 거래(정답 = 그 거래의 실제 가격)에 대해 "그 거래 직전까지의" 같은 단지·같은 평형(±3㎡) 중개거래만으로 규칙별 예상가를 만들어 비교.
 (정답이 낙찰 후 되판 값이 아니라 시장 일반 거래값이라 '보수적으로 낮게 잡기'의 효과는 치우침(음수=예상이 높음)·과대(예상이 정답의 110% 넘는 비율)로 봄)
 회전율 = (직전 1년 같은 단지 전체 평형 거래 수) ÷ 세대수(kapt_complex_info, 법정동+단지명 연결).
결과는 로그로 출력.
"""
import os, re, math, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)
avm = ab.avm
rng = np.random.default_rng(7)
MAX_TEST = int(os.environ.get("MAX_TEST", "40000"))  # 지역 구분마다 최대 시험 거래 수


def nrm(x):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(x or "")).replace("아파트", "")


def cls_of(region):
    s = str(region or "").split(" ")[0]
    if s.startswith("서울"): return "서울"
    if s[:2] in ("경기", "인천"): return "경기·인천"
    return "지방"


def qt(a, q): return float(np.quantile(a, q))


def wq(vals, w, q):
    o = np.argsort(vals); v = np.asarray(vals)[o]; ww = np.asarray(w)[o]
    c = (np.cumsum(ww) - 0.5 * ww) / ww.sum()
    return float(np.interp(q, c, v))


def main():
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20220101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10)]
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["rg"] = tr["region"].map(ab.region_norm); tr["bj"] = tr["bunji"].astype(str).str.strip()
    tr["direct"] = (tr["dealing_type"] == "직거래")
    tr["ts"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); tr = tr.dropna(subset=["ts", "rg"])
    tr["t"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
    tr["cls"] = tr["region"].map(cls_of)
    print(f"  거래 {len(tr):,}건", tr["cls"].value_counts().to_dict())

    hh = {}
    try:
        kp = avm.fetch_all_rows("kapt_complex_info", cols="kapt_name,as3,households", order_col="kapt_code", extra_filter="&households=gt.0")
        for r in kp.itertuples():
            k = (ab.dong_key(str(r.as3).strip().split()[-1] if r.as3 else ""), nrm(r.kapt_name))
            hh[k] = max(hh.get(k, 0), int(r.households))
    except Exception as e:
        print("  세대수 조회 실패:", e)
    print(f"  세대수 자료 {len(hh):,}단지")

    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "bj"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    rows = []
    for cls in ("서울", "경기·인천", "지방"):
        keys = [k for k, g in groups.items() if g["cls"].iloc[0] == cls]
        test = []
        for k in keys:
            g = groups[k]
            idx = np.where((g["t"].values >= t_start) & (~g["direct"].values))[0]
            for i in idx: test.append((k, i))
        if len(test) > MAX_TEST:
            sel = rng.choice(len(test), MAX_TEST, replace=False); test = [test[i] for i in sel]
        print(f"  {cls}: 시험 거래 {len(test):,}건 (단지 {len(keys):,}곳)")
        for k, i in test:
            g = groups[k]; T = g.iloc[i]
            H = g.iloc[:i]; H = H[H["t"] < T["t"]]
            if not len(H): continue
            Hn = H[~H["direct"]]
            S = Hn[(Hn["size"] - T["size"]).abs() <= 3]
            ag = (T["t"] - S["t"].values) / 30.4
            pr = S["price"].values
            p3 = pr[ag <= 3]; p6 = pr[ag <= 6]
            if len(p6) < 3: continue
            a6 = ag[ag <= 6]
            tr12 = int((((T["t"] - Hn["t"]) <= 365)).sum())
            dn = g["dk"].iloc[0]
            nms = {nrm(g["danji"].mode().iloc[0])} if len(g) else set()
            h = None
            for nm in nms:
                if (dn, nm) in hh: h = hh[(dn, nm)]; break
            ests = {}
            ests["A현재"] = np.median(p3) if len(p3) >= 5 else qt(p6, 0.4)
            ests["중위6m"] = np.median(p6)
            ests["하위40"] = qt(p6, 0.4)
            ests["하위30"] = qt(p6, 0.3)
            ests["3m중위(3건+)"] = np.median(p3) if len(p3) >= 3 else qt(p6, 0.4)
            ests["3m중위(3건+)/없으면중위6m"] = np.median(p3) if len(p3) >= 3 else np.median(p6)
            ests["최근가중(반감2m)중위"] = wq(p6, [0.5 ** (a / 2.0) for a in a6], 0.5)
            ests["최근가중(반감1m)중위"] = wq(p6, [0.5 ** (a / 1.0) for a in a6], 0.5)
            ests["최근3건중위"] = float(np.median(pr[np.argsort(ag)[:3]])) if len(pr) >= 3 else np.nan
            rows.append(dict(cls=cls, n3=len(p3), n6=len(p6), tr12=tr12, hh=h, actual=float(T["price"]), **{"e_" + k2: v for k2, v in ests.items()}))
    D = pd.DataFrame(rows)
    D.to_json("backtest-sale-rule.json", orient="records", force_ascii=False)
    print(f"  시험 가능 {len(D):,}건, 세대수 연결 {D['hh'].notna().sum():,}건({D['hh'].notna().mean() * 100:.0f}%)")
    report(D)


def report(D):
    ecols = [c for c in D.columns if c.startswith("e_")]
    def line(d):
        out = []
        for c in ecols:
            r = d["actual"] / d[c]
            out.append(f"{c[2:]:<22} 오차{np.nanmedian(np.abs(r - 1)) * 100:4.1f}% 치우침{(np.nanmedian(r) - 1) * 100:+5.1f}% 과대{(r < 0.9).mean() * 100:3.0f}%")
        return out
    print("\n==== 지역별 ====")
    for cls in ("서울", "경기·인천", "지방"):
        d = D[D.cls == cls]
        print(f"\n[{cls}] n{len(d):,} (3개월 거래 중앙 {d.n3.median():.0f}건, 3건+ {np.mean(d.n3 >= 3) * 100:.0f}%, 5건+ {np.mean(d.n3 >= 5) * 100:.0f}%)")
        for l in line(d): print("  ", l)
    print("\n==== 거래량(6개월) 구간 × 지역: 오차 비교 ====")
    for cls in ("서울", "경기·인천", "지방"):
        for nm, lo, hi in (("6m 3~4건", 3, 5), ("5~9건", 5, 10), ("10건+", 10, 999)):
            d = D[(D.cls == cls) & (D.n6 >= lo) & (D.n6 < hi)]
            if len(d) < 200: continue
            print(f"\n[{cls}·{nm}] n{len(d):,}")
            for l in line(d): print("  ", l)
    X = D[D.hh.notna() & (D.hh > 0)].copy(); X["turn"] = X.tr12 / X.hh * 100
    if len(X) > 500:
        print("\n==== 회전율(연 거래수÷세대수) ====")
        qs = X.turn.quantile([1 / 3, 2 / 3]).values
        print(f"회전율 3분위 경계 {qs.round(1)}  (중앙 {X.turn.median():.1f}%)")
        X["tb"] = pd.cut(X.turn, [-1, qs[0], qs[1], 1e9], labels=["낮음", "중간", "높음"])
        for cls in ("서울", "경기·인천", "지방"):
            for b in ("낮음", "중간", "높음"):
                d = X[(X.cls == cls) & (X.tb == b)]
                if len(d) < 200: continue
                print(f"\n[{cls}·회전율 {b}] n{len(d):,} (평균 {d.turn.mean():.1f}%, 6개월 거래 중앙 {d.n6.median():.0f}건)")
                for l in line(d): print("  ", l)


if __name__ == "__main__":
    main()
