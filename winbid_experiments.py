"""
🧪 예상 낙찰가 개선 실험 (2026-10-25, 사용자: 권리분석·명도 난이도(주관적)는 빼고 나머지 개선 후보를 전부 시험)
같은 학습/시험 구간(시험 = 최근 12개월)에서 현재 방식과 비교. 결과는 로그와 GitHub 요약에만 남기고 앱 계산은 바꾸지 않음(개선이 확인되면 사용자와 상의해 반영).
 ① 물건마다 다른 오차 폭: 낙찰 가능성(확률) 정확도(Brier) - 구간 나눔 기준별
 ② 최근 사례 비중: 최근 24·12개월만 / 최근 6개월 2배 / 12개월 3배
 ③ 시세 계산 대안: 기존 est vs 새 규칙·가중 변형(est_rule_experiment 재사용)
 ⑤ 더 복잡한 모델(HistGradientBoosting)과 비교 + 덧셈형 위에 잔차를 얹는 방식
 ④ 객관 정보(세대수·연식·거래량 등 R에 있는 숫자 열)는 ⑤에 함께 넣어 효과 확인
모든 표는 전체와 비규제지역(허가구역 밖) 두 가지로 냄.
"""
import os, json
import numpy as np
import pandas as pd

DELTAS = (-0.08, -0.04, 0.0, 0.04, 0.08, 0.12)


def _metrics(p, te, mask=None):
    est, act = te["est"].values, te["actual"].values
    pr = np.exp(p) * est
    r = act / pr - 1
    if mask is not None: r = r[mask]
    return {"n": int(len(r)), "err": round(float(np.median(np.abs(r))) * 100, 3), "bias": round(float(np.median(r)) * 100, 2), "hit10": round(float((np.abs(r) <= 0.10).mean()) * 100, 1),
            "hi10": round(float((r < -0.10).mean()) * 100, 1), "p90": round(float(np.quantile(np.abs(r), .9)) * 100, 1)}


def _cdf_from(res):
    q = np.sort(res)
    return lambda d: np.searchsorted(q, d, side="right") / max(len(q), 1)


def _brier(res_te, cdf_fn_per_row):
    tot = 0.0
    for d in DELTAS:
        pr = cdf_fn_per_row(d)
        ev = (res_te <= d).astype(float)
        tot += float(np.mean((pr - ev) ** 2))
    return round(tot / len(DELTAS), 5)


def run(D, tr, te, wb_fit, wb_predict, zones, est_rule_experiment, R, now):
    out = {}
    nonreg = ~te["region"].map(lambda r: r in zones).values
    base_model = wb_fit(tr); p0 = wb_predict(base_model, te)
    res_te = np.log(te["actual"].values / te["est"].values) - p0
    out["기준(현재)"] = {"전체": _metrics(p0, te), "비규제": _metrics(p0, te, nonreg)}
    print("  🧪 기준(현재)", out["기준(현재)"])

    # ── ① 물건마다 다른 오차 폭 ──
    tr_s = tr.sort_values("sale"); folds = np.array_split(np.arange(len(tr_s)), 4); oof = np.zeros(len(tr_s))
    for k in range(4):
        idx = folds[k]; rest = np.setdiff1d(np.arange(len(tr_s)), idx)
        m = wb_fit(tr_s.iloc[rest]); oof[idx] = wb_predict(m, tr_s.iloc[idx])
    res_tr = np.log(tr_s["actual"].values / tr_s["est"].values) - oof
    def grp(df):
        cls = df["region"].map(lambda r: "서울" if str(r).startswith("서울") else ("경기·인천" if str(r)[:2] in ("경기", "인천") else "지방"))
        own = df["own"].map(lambda n: "거래1~2" if n <= 2 else ("3~5" if n <= 5 else ("6~10" if n <= 10 else "11+")))
        fails = df["fails"].map(lambda f: "?" if f is None or pd.isna(f) else str(min(int(f), 2)))
        pr = df["minbid"] / df["est"]
        lbk = pd.cut(np.log(pr.astype(float)), [-9, -0.5, -0.3, -0.15, 0, 9], labels=False).astype(str)
        return {"전체 하나": pd.Series("a", index=df.index), "거래 수": own, "권역": cls, "유찰": fails, "최저가÷시세": lbk, "거래 수×권역": own + "|" + cls, "거래 수×유찰": own + "|" + fails}
    gtr, gte = grp(tr_s), grp(te)
    glob = _cdf_from(res_tr)
    bri = {"전체 하나(현재)": _brier(res_te, lambda d: np.full(len(te), glob(d)))}
    for nm in list(gtr.keys())[1:]:
        cdfs = {k: _cdf_from(res_tr[(gtr[nm].values == k)]) for k in set(gtr[nm].values) if (gtr[nm].values == k).sum() >= 150}
        keys = gte[nm].values
        bri[nm] = _brier(res_te, lambda d, cdfs=cdfs, keys=keys: np.array([cdfs[k](d) if k in cdfs else glob(d) for k in keys]))
    bri_nr = {}
    for nm in list(bri.keys()):
        if nm.startswith("전체 하나"): cd = lambda d: np.full(nonreg.sum(), glob(d))
        else:
            cdfs = {k: _cdf_from(res_tr[(gtr[nm].values == k)]) for k in set(gtr[nm].values) if (gtr[nm].values == k).sum() >= 150}
            keys = gte[nm].values[nonreg]; cd = (lambda d, cdfs=cdfs, keys=keys: np.array([cdfs[k](d) if k in cdfs else glob(d) for k in keys]))
        bri_nr[nm] = _brier(res_te[nonreg], cd)
    out["① 오차 폭(Brier, 낮을수록 좋음)"] = {"전체": bri, "비규제": bri_nr}
    print("  🧪 ① 오차 폭 구간 나눔별 Brier(전체):", bri, "| 비규제:", bri_nr)

    # ── ② 최근 사례 비중 ──
    last_tr = pd.to_datetime(str(int(tr["sale"].max())), format="%Y%m%d")
    def since(mo): return int((last_tr - pd.DateOffset(months=mo)).strftime("%Y%m%d"))
    variants = {"전체 기간(현재)": tr, "최근 24개월만": tr[tr["sale"] >= since(24)], "최근 12개월만": tr[tr["sale"] >= since(12)],
                "최근 6개월 2배": pd.concat([tr, tr[tr["sale"] >= since(6)]]), "최근 12개월 3배": pd.concat([tr, tr[tr["sale"] >= since(12)], tr[tr["sale"] >= since(12)]])}
    rec = {}
    for nm, T in variants.items():
        pp = wb_predict(wb_fit(T), te); rec[nm] = {"전체": _metrics(pp, te), "비규제": _metrics(pp, te, nonreg)}
    out["② 최근 사례 비중"] = rec
    for nm, v in rec.items(): print("  🧪 ②", nm, v)

    # ── ③ 시세 계산 대안 ──
    alts = [c for c in ("est_rule", "est_q50", "est_w90_q50", "est_w90_q40", "est_w180_q40", "est_idx_q40", "est_idx_w180_q50", "est_idx_w90_q50", "est_last3") if c in R.columns]
    print("  🧪 ③ 시세 대안 후보 열:", alts)
    for c in alts:
        try:
            print(f"  ▶ 시세 대안 {c}")
            est_rule_experiment(R, wb_fit, wb_predict, now, (("현재", "est"), (c, c)), "시세 대안 " + c)
        except Exception as e:
            print("   건너뜀:", c, e)

    # ── ⑤ 복잡한 모델 + ④ 객관 정보 ──
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        num_cols = [c for c in ("n12", "cx12", "own", "area", "floor", "hh", "households", "by", "age", "bage", "years", "mkt", "jb", "dong3y", "appraisal", "minbid", "fails") if c in D.columns]
        print("  🧪 ⑤ 사용한 숫자 열:", num_cols)
        def feats(df):
            X = pd.DataFrame(index=df.index)
            X["lmin"] = np.log(df["minbid"].astype(float) / df["est"].astype(float))
            X["lab"] = np.log(df["appraisal"].astype(float) / df["est"].astype(float))
            for c in num_cols:
                if c not in ("minbid", "appraisal"): X[c] = pd.to_numeric(df[c], errors="coerce")
            X["month"] = (df["sale"] // 100) % 100
            X["rcode"] = df["region"].astype("category").cat.codes if False else 0
            return X
        cats = pd.Categorical(pd.concat([tr["region"], te["region"]]).fillna("?"))
        rcode = dict(zip(cats.categories, range(len(cats.categories))))
        Xtr, Xte = feats(tr), feats(te); Xtr["rcode"] = tr["region"].fillna("?").map(rcode).values; Xte["rcode"] = te["region"].fillna("?").map(rcode).values
        ytr = np.log(tr["actual"].values / tr["est"].values)
        cat_mask = [c == "rcode" for c in Xtr.columns]
        g = HistGradientBoostingRegressor(loss="absolute_error", max_depth=5, learning_rate=0.05, max_iter=300, categorical_features=cat_mask if len(cats.categories) <= 250 else None, random_state=0).fit(Xtr, ytr)
        pg = g.predict(Xte)
        # 덧셈형 위에 잔차를 얹는 방식(학습 잔차는 4분할 OOF)
        tr_pred_oof = np.zeros(len(tr))
        tr_idx = {ix: i for i, ix in enumerate(tr.index)}
        order = [tr_idx[ix] for ix in tr_s.index]; tr_pred_oof[order] = oof
        g2 = HistGradientBoostingRegressor(loss="absolute_error", max_depth=3, learning_rate=0.05, max_iter=200, categorical_features=cat_mask if len(cats.categories) <= 250 else None, random_state=0).fit(Xtr, ytr - tr_pred_oof)
        ps = p0 + g2.predict(Xte)
        cx = {"덧셈형(현재)": {"전체": _metrics(p0, te), "비규제": _metrics(p0, te, nonreg)}, "복잡한 모델 단독": {"전체": _metrics(pg, te), "비규제": _metrics(pg, te, nonreg)}, "덧셈형+잔차 모델": {"전체": _metrics(ps, te), "비규제": _metrics(ps, te, nonreg)}}
        out["⑤ 복잡한 모델·객관 정보"] = cx
        for nm, v in cx.items(): print("  🧪 ⑤", nm, v)
    except Exception as e:
        print("  🧪 ⑤ 건너뜀:", e)
    try:
        out["⑥ 노이즈 낙찰가 거르기"] = noise_experiment(D, tr, te, wb_fit, wb_predict, nonreg)
    except Exception as e:
        import traceback; traceback.print_exc(); print("  🧪 ⑥ 건너뜀:", e)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 예상 낙찰가 개선 실험\n```json\n" + json.dumps(out, ensure_ascii=False, indent=1) + "\n```\n")
    return out


def noise_experiment(D, tr, te, wb_fit, wb_predict, nonreg):
    """2026-10-29(사용자: 실수요·미래가치 입찰자와 보증공사(HUG) 경매는 투자자가 이길 수 없는 높은 가격 → 학습에서 거를 방법)
    ① 태그별 잔차(실제÷예상) ② 태그를 요인으로 ③ 해당 건을 학습에서 빼기 ④ 학습 잔차 이상치(+20% 초과) 빼기 ⑤ 낙찰자가 차순위보다 크게 높게 쓴 비율"""
    G = wb_fit.__globals__; base_f = list(G["WB_FACTORS"])
    tagf = lambda df: np.where(df["notes"].fillna("").astype(str).str.contains("HUG"), "HUG", np.where(df["notes"].fillna("").astype(str).str.contains("임차권|대항력"), "임차", "없음"))
    tag_te = tagf(te); tag_tr = tagf(tr)
    print("  🧪 ⑥ 태그 분포 학습", {k: int((tag_tr == k).sum()) for k in ("HUG", "임차", "없음")}, "시험", {k: int((tag_te == k).sum()) for k in ("HUG", "임차", "없음")})
    y_te = np.log(te["actual"].values / te["est"].values)
    def metrics(p, mask=None):
        r = np.exp(y_te - p) - 1  # 실제 ÷ 예상 − 1
        if mask is not None: r = r[mask]
        return {"n": int(len(r)), "err": round(float(np.median(np.abs(r))) * 100, 2), "bias": round(float(np.median(r)) * 100, 2), "lo10": round(float((r > 0.10).mean()) * 100, 1), "hi10": round(float((r < -0.10).mean()) * 100, 1), "lo20": round(float((r > 0.20).mean()) * 100, 1)}
    out = {}
    m0 = wb_fit(tr); p0 = wb_predict(m0, te)
    out["① 태그별(현재 모델)"] = {k: metrics(p0, tag_te == k) for k in ("HUG", "임차", "없음") if (tag_te == k).sum() >= 100}
    for k, v in out["① 태그별(현재 모델)"].items(): print("  🧪 ⑥①", k, v)
    # ② 태그를 요인으로
    try:
        G["WB_FACTORS"] = base_f + [("hug", 30)]
        m1 = wb_fit(tr); p1 = wb_predict(m1, te)
        out["② 태그를 요인으로"] = {"전체": metrics(p1), "비규제": metrics(p1, nonreg), "HUG": metrics(p1, tag_te == "HUG"), "태그 없음": metrics(p1, tag_te == "없음"), "효과": m1["eff"].get("hug")}
        print("  🧪 ⑥② 요인으로 추가", out["② 태그를 요인으로"])
    finally:
        G["WB_FACTORS"] = base_f
    out["기준(현재) 전체·태그 없음"] = {"전체": metrics(p0), "태그 없음": metrics(p0, tag_te == "없음")}
    print("  🧪 ⑥ 기준", out["기준(현재) 전체·태그 없음"])
    # ③ 학습에서 해당 건 빼기
    for nm, keep in (("HUG만 빼고 학습", tag_tr != "HUG"), ("HUG·임차 모두 빼고 학습", tag_tr == "없음")):
        m2 = wb_fit(tr[keep]); p2 = wb_predict(m2, te)
        out["③ " + nm] = {"전체": metrics(p2), "태그 없음": metrics(p2, tag_te == "없음"), "HUG": metrics(p2, tag_te == "HUG")}
        print("  🧪 ⑥③", nm, out["③ " + nm])
    # ④ 학습 잔차 이상치 빼기
    r_tr = np.log(tr["actual"].values / tr["est"].values) - wb_predict(m0, tr)
    for cut in (0.20, 0.30):
        keep = r_tr <= cut
        m3 = wb_fit(tr[keep]); p3 = wb_predict(m3, te)
        out[f"④ 학습 잔차 +{int(cut*100)}% 초과 빼기({int((~keep).sum())}건)"] = {"전체": metrics(p3), "태그 없음": metrics(p3, tag_te == "없음")}
        print("  🧪 ⑥④", f"+{int(cut*100)}% 초과 제거 {int((~keep).sum())}건", out[f"④ 학습 잔차 +{int(cut*100)}% 초과 빼기({int((~keep).sum())}건)"])
    # ⑤ 낙찰자가 차순위보다 크게 높게 쓴 비율(비경제적 낙찰)
    try:
        sec = pd.to_numeric(te["second"], errors="coerce").values; act = te["actual"].values; bid = pd.to_numeric(te["bidders"], errors="coerce").values
        ok = np.isfinite(sec) & (sec > 0) & (bid >= 2)
        gap = (act - sec) / act
        out["⑤ 차순위 대비 낙찰가 격차 8%+ 비율"] = {k: {"n": int((ok & (tag_te == k)).sum()), "pct": round(float((gap[ok & (tag_te == k)] > 0.08).mean()) * 100, 1)} for k in ("HUG", "임차", "없음") if (ok & (tag_te == k)).sum() >= 100}
        print("  🧪 ⑥⑤", out["⑤ 차순위 대비 낙찰가 격차 8%+ 비율"])
    except Exception as ex:
        print("  🧪 ⑥⑤ 건너뜀:", ex)
    return out
