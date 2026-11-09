"""
🏢 같은 단지 안 '동(棟)별 가격 차이' 실측 (2026-11-09, 사용자: 시세 정답이 동·층·조망 차이로 흔들리는 한계를 줄일 방법 시험)
질문: 같은 단지·같은 평형에서 어느 동이 평소 더 비싸게(또는 싸게) 거래됐는지 과거 거래로 알 수 있고, 그 차이가 다음 거래 가격을 더 잘 맞히게 하나?
방법(미래 정보 없음):
  ① 각 거래 i의 잔차 r_i = ln(거래가 ÷ 같은 단지·평형 직전 6개월 거래 중위값) - 직전 거래만 사용(직전 거래 3건+ 필요)
  ② 같은 동의 이전 거래들 잔차 평균 e_i(이전 24개월, 거래 m건) - 동 정보 있는 거래끼리
  ③ 표본 조정(shrink): e*_i = e_i × m/(m+k), k는 자료에서 구한 '같은 동 안 거래 가격 흩어짐² ÷ 동끼리 평균 차이²'(경험적 베이즈, 고정 숫자 아님)
  ④ 시험: 2026-01-01 이전 거래로 기울기 b를 맞추고 이후 거래에서 |r_i| 와 |r_i − b·e*_i| 를 비교(중앙 오차·10% 넘게 틀린 비율)
출력: dong-effect.json (전체·근거 두께(직전 거래 수)별·권역별). 앱·서버 값은 건드리지 않음(측정만).
"""
import os, json, re, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("avm", os.path.join(HERE, "train-avm.py"))
avm = importlib.util.module_from_spec(_s); _s.loader.exec_module(avm)

TEST_FROM = 20260101


def to_days(d):
    d = np.asarray(d, dtype=np.int64)
    y, m, dd = d // 10000, (d // 100) % 100, d % 100
    return (y - 2000) * 372 + (m - 1) * 31 + (dd - 1)   # 대략적인 일수(순서·간격 비교용)


def main():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,size,price,deal_date,dealing_type,cdeal_type,apt_dong",
                             extra_filter="&deal_date=gte.20230101")
    print(f"받은 거래 {len(raw):,}건")
    df = raw[raw["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    df = df[df["dealing_type"].fillna("") != "직거래"]
    for c in ("size", "price", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["size", "price", "deal_date"])
    df = df[(df["price"] > 0) & (df["size"] >= 20) & (df["size"] <= 250)]
    df["adong"] = df["apt_dong"].map(lambda v: (str(int(re.search(r"(\d{1,4})", str(v)).group(1))) if re.search(r"(\d{1,4})", str(v or "")) else ""))
    df["metro"] = df["region"].astype(str).str.match(r"^(서울|경기|인천)")
    df["cls"] = np.where(df["region"].astype(str).str.startswith("서울"), "서울", np.where(df["region"].astype(str).str.match(r"^(경기|인천)"), "경기·인천", "지방"))
    df["unit"] = df["region"].astype(str) + "|" + df["dong"].astype(str) + "|" + df["bunji"].astype(str) + "|" + df["danji"].astype(str) + "|" + (df["size"] / 3).round().astype(int).astype(str)
    df["day"] = to_days(df["deal_date"].astype(int).values)
    df["lp"] = np.log(df["price"].values)
    df = df.sort_values(["unit", "day"]).reset_index(drop=True)
    print(f"정리 후 {len(df):,}건, 동 정보 있음 {int((df['adong'] != '').sum()):,}건")

    # ① 잔차: 같은 unit의 직전 180일(자기 제외, 같은 날 제외) 거래 중위값
    res = np.full(len(df), np.nan); nprev = np.zeros(len(df), dtype=np.int32)
    unit_start = df.groupby("unit", sort=False).indices
    days = df["day"].values; lp = df["lp"].values
    for u, idx in unit_start.items():
        if len(idx) < 4: continue
        dd = days[idx]; ll = lp[idx]
        for k in range(len(idx)):
            lo = np.searchsorted(dd, dd[k] - 180, side="left"); hi = np.searchsorted(dd, dd[k], side="left")   # 직전(같은 날 제외)
            if hi - lo >= 3:
                res[idx[k]] = ll[k] - np.median(ll[lo:hi]); nprev[idx[k]] = hi - lo
    df["r"] = res; df["nprev"] = nprev
    D = df[np.isfinite(df["r"]) & (df["adong"] != "")].copy()
    D = D[D["r"].abs() < 0.5]   # 입력 오류(±50%↑) 제외
    print(f"잔차 계산된 동 정보 거래 {len(D):,}건")

    # ② 같은 동의 이전(24개월) 거래 잔차 평균 e, 거래 수 m  (잔차는 이미 직전 정보만 사용)
    e = np.full(len(D), np.nan); mcnt = np.zeros(len(D), dtype=np.int32)
    keyg = (D["unit"] + "|" + D["adong"]).values
    D = D.assign(_k=keyg)
    gi = D.groupby("_k", sort=False).indices
    dd_all = D["day"].values; r_all = D["r"].values
    for k_, idx in gi.items():
        if len(idx) < 2: continue
        o = np.argsort(dd_all[idx]); idx = idx[o]; dd = dd_all[idx]; rr = r_all[idx]
        for j in range(1, len(idx)):
            lo = np.searchsorted(dd, dd[j] - 730, side="left"); hi = np.searchsorted(dd, dd[j], side="left")
            if hi - lo >= 1:
                e[idx[j]] = rr[lo:hi].mean(); mcnt[idx[j]] = hi - lo
    D["e"] = e; D["m"] = mcnt
    W = D[np.isfinite(D["e"])].copy()
    print(f"동 효과 추정 가능한 거래 {len(W):,}건 ({len(W) / max(1, len(D)) * 100:.0f}%)")

    # ③ 경험적 베이즈 k = 같은 동 안 흩어짐² ÷ 동끼리 차이²  (학습 구간 기준)
    tr_ = W[W["deal_date"] < TEST_FROM]
    te_ = W[W["deal_date"] >= TEST_FROM]
    if len(tr_) < 2000 or len(te_) < 500:
        print("표본 부족"); json.dump({"error": "표본 부족", "train": len(tr_), "test": len(te_)}, open("dong-effect.json", "w")); return
    gm = tr_.groupby("_k")["r"].agg(["mean", "var", "size"]).dropna()
    gm = gm[gm["size"] >= 3]
    within = float(gm["var"].median()); between = float(max(gm["mean"].var() - within / gm["size"].median(), 1e-6))
    k = within / between
    print(f"within var {within:.5f} between var {between:.5f} → k={k:.2f}")
    W["es"] = W["e"] * W["m"] / (W["m"] + k)
    tr_ = W[W["deal_date"] < TEST_FROM]; te_ = W[W["deal_date"] >= TEST_FROM]
    b = float((tr_["es"] * tr_["r"]).sum() / max((tr_["es"] ** 2).sum(), 1e-9))
    print(f"학습 구간 기울기 b={b:.3f} (1이면 동 차이가 그대로 다음 거래에 반영, 0이면 효과 없음)")

    def rep(S):
        if len(S) < 200: return {"n": int(len(S))}
        a0 = S["r"].abs(); a1 = (S["r"] - b * S["es"]).abs()
        return {"n": int(len(S)), "보정전_중앙오차%": round(float(a0.median()) * 100, 2), "보정후_중앙오차%": round(float(a1.median()) * 100, 2),
                "보정전_10%초과%": round(float((a0 > 0.10).mean()) * 100, 1), "보정후_10%초과%": round(float((a1 > 0.10).mean()) * 100, 1),
                "보정전_5%초과%": round(float((a0 > 0.05).mean()) * 100, 1), "보정후_5%초과%": round(float((a1 > 0.05).mean()) * 100, 1)}
    out = {"k": round(k, 2), "b": round(b, 3), "학습건수": int(len(tr_)), "시험건수": int(len(te_)), "시험시작": TEST_FROM,
           "동정보거래비율%": round(float((df["adong"] != "").mean()) * 100, 1), "전체": rep(te_), "권역별": {}, "직전거래수별": {}, "동거래수별": {}, "동효과크기별": {}}
    for c in ("서울", "경기·인천", "지방"): out["권역별"][c] = rep(te_[te_["cls"] == c])
    for lo, hi, lab in ((3, 4, "직전 3~4건"), (5, 9, "5~9건"), (10, 9999, "10건+")): out["직전거래수별"][lab] = rep(te_[(te_["nprev"] >= lo) & (te_["nprev"] <= hi)])
    for lo, hi, lab in ((1, 1, "같은 동 이전 1건"), (2, 3, "2~3건"), (4, 9999, "4건+")): out["동거래수별"][lab] = rep(te_[(te_["m"] >= lo) & (te_["m"] <= hi)])
    big = te_["es"].abs()
    q = big.quantile([.5, .8]).values
    for lo, hi, lab in ((0, q[0], "동 효과 작음(하위 50%)"), (q[0], q[1], "중간"), (q[1], 9, "동 효과 큼(상위 20%)")): out["동효과크기별"][lab] = rep(te_[(big >= lo) & (big < hi + 1e-12)])
    out["동효과_상위20%_평균%"] = round(float(np.expm1(te_.loc[big >= q[1], "es"].abs().mean())) * 100, 2)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("dong-effect.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
