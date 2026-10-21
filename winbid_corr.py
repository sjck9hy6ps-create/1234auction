"""
예상 낙찰가 자동 보정 검증 (2026-10-22, 사용자: 예상 낙찰가를 기반으로 현재 로직을 맞춰 가는 방향 - 아파트·빌라 모두 매주 확인)
방법(과거로 한 주씩 앞으로 가며): 최근 8개 4주 구간(약 32주)을 차례로, 각 구간 이전 사례만으로 모델을 새로 학습해 그 구간 낙찰가를 맞히고(학습에 안 쓴 예측) 잔차(실제÷예측)를 쌓음.
 보정 = 직전 3개 구간(약 12주)의 잔차 중앙값을 구간(지역 / 유찰 / 지역×유찰)별로 구해 표본 수만큼 줄여서(n÷(n+30)) 최대 ±4%까지 다음 구간 예측에 반영.
 평가 = 보정 전·후 보통 오차·치우침·±10% 비율·예상가로 낙찰 비율. 구간별로 0.15%p 이상 좋아지고 표본 100건 이상일 때만 '적용 권장'.
입력 D 필수 열: sale(YYYYMMDD 정수), actual, est, cls(서울·경기·인천·지방 등), fb(신건·1회 유찰·2회+ 유찰)
"""
import numpy as np
import pandas as pd

VARIANTS = {"지역": ["cls"], "유찰": ["fb"], "지역×유찰": ["cls", "fb"]}


def _stat(actual, pred):
    e = pred / actual - 1; a = np.abs(e)
    return {"n": int(len(e)), "medAbsErrPct": round(float(np.median(a)) * 100, 2), "biasPct": round(float(np.median(e)) * 100, 2),
            "within10Pct": round(float((a <= 0.10).mean()) * 100, 1), "winAtPredPct": round(float((actual <= pred).mean()) * 100, 1)}


def _corr_table(H, cols, min_n, k, cap):
    """H: 잔차 데이터(res 열) → {구간키: (보정값, n)}"""
    out = {}
    for key, G in H.groupby(cols, observed=True):
        key = key if isinstance(key, tuple) else (key,)
        n = len(G)
        if n < min_n:
            continue
        c = float(np.median(G["res"])) * n / (n + k)
        out["|".join(str(x) for x in key)] = (float(np.clip(c, -cap, cap)), int(n))
    return out


def _apply(T, table, cols):
    keys = T[cols].astype(str).agg("|".join, axis=1) if len(cols) > 1 else T[cols[0]].astype(str)
    return keys.map(lambda x: table.get(x, (0.0, 0))[0]).values.astype(float)


def walk_forward(D, fit_fn, pred_fn, n_blocks=8, block_days=28, hist_blocks=3, min_n=30, k=30, cap=0.04, min_train=3000):
    D = D.copy(); D["dt"] = pd.to_datetime(D["sale"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); D = D.dropna(subset=["dt"])
    t_end = D["dt"].max() + pd.Timedelta(days=1)
    blocks = []
    for b in range(n_blocks):
        s = t_end - pd.Timedelta(days=block_days * (n_blocks - b)); e = t_end - pd.Timedelta(days=block_days * (n_blocks - b - 1))
        tr = D[D["dt"] < s]; te = D[(D["dt"] >= s) & (D["dt"] < e)].copy()
        if len(te) < 30 or len(tr) < min_train:
            continue
        m = fit_fn(tr); p = pred_fn(m, te)
        te["p"] = p; te["res"] = np.log(te["actual"].values / te["est"].values) - p; te["blk"] = b
        blocks.append(te)
    if len(blocks) <= hist_blocks:
        return {"ok": False, "why": "검증 구간이 모자라요"}
    A = pd.concat(blocks)
    ev_parts = {v: [] for v in VARIANTS}
    for bi in sorted(A["blk"].unique()):
        hist = A[(A["blk"] < bi) & (A["blk"] >= bi - hist_blocks)]
        if hist["blk"].nunique() < hist_blocks:
            continue
        T = A[A["blk"] == bi].copy()
        for v, cols in VARIANTS.items():
            tab = _corr_table(hist, cols, min_n, k, cap)
            T2 = T.copy(); T2["corr"] = _apply(T, tab, cols); ev_parts[v].append(T2)
    out = {"ok": True, "blocks": int(len(blocks)), "histBlocks": hist_blocks, "params": {"minN": min_n, "k": k, "capPct": cap * 100}, "variants": {}}
    best = None
    for v, parts in ev_parts.items():
        if not parts:
            continue
        E = pd.concat(parts)
        act = E["actual"].values
        before = _stat(act, E["est"].values * np.exp(E["p"].values)); after = _stat(act, E["est"].values * np.exp(E["p"].values + E["corr"].values))
        seg = {}
        for cname in ("cls", "fb"):
            for val, G in E.groupby(cname):
                if len(G) < 100:
                    continue
                b0 = _stat(G["actual"].values, G["est"].values * np.exp(G["p"].values)); a0 = _stat(G["actual"].values, G["est"].values * np.exp(G["p"].values + G["corr"].values))
                seg[f"{cname}={val}"] = {"before": b0, "after": a0, "gainPct": round(b0["medAbsErrPct"] - a0["medAbsErrPct"], 2), "recommend": bool(b0["medAbsErrPct"] - a0["medAbsErrPct"] >= 0.15)}
        gain = round(before["medAbsErrPct"] - after["medAbsErrPct"], 2)
        out["variants"][v] = {"before": before, "after": after, "gainPct": gain, "segments": seg}
        if best is None or gain > best[1]:
            best = (v, gain)
    if best:
        out["best"] = best[0]; out["bestGainPct"] = best[1]
        out["recommend"] = bool(best[1] >= 0.05 or any(s["recommend"] for s in out["variants"][best[0]]["segments"].values()))
        # 지금(이번 주) 적용한다면: 가장 최근 구간 hist_blocks개 잔차로 만든 보정표
        H = A[A["blk"] >= A["blk"].max() - hist_blocks + 1]
        cols = VARIANTS[best[0]]
        tab = _corr_table(H, cols, min_n, k, cap)
        out["current"] = {"variant": best[0], "table": {kk: {"corrPct": round(vv[0] * 100, 2), "n": vv[1]} for kk, vv in tab.items()}}
    return out
