"""
🔬 예상매도가 규칙 비교 - 지역(서울·경기인천·지방) × 회전율 × 거래량 (2026-10-17, 사용자: "서울은 3개월 3건 이상이 거의 모든 아파트 / 거래량·회전율로 최근거래 비중을 달리")
낙찰 되팔기 표본(3,284건)은 거의 전부 지방이라 서울·수도권은 검증된 적이 없었음 → 전체 아파트 실거래로 비교함:
 각 거래(정답 = 그 거래의 실제 가격)에 대해 "그 거래 직전까지의" 같은 단지·같은 평형(±3㎡) 중개거래만으로 규칙별 예상가를 만들어 비교.
 (정답이 낙찰 후 되판 값이 아니라 시장 일반 거래값이라 '보수적으로 낮게 잡기'의 효과는 치우침(음수=예상이 높음)·과대(예상이 정답의 110% 넘는 비율)로 봄)
 회전율 = (직전 1년 같은 단지 전체 평형 거래 수) ÷ 세대수(kapt_complex_info, 법정동+단지명 연결).
결과는 로그로 출력.
"""
import os, re, math, json, importlib.util
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
            for qq in (0.4, 0.5, 0.6):  # 2026-10-25 현재 지역별 규칙의 기준 지점(분위) 비교
                if cls == "서울":
                    l3 = pr[np.argsort(ag)[:3]]; ests[f"주규칙{int(qq*100)}"] = wq(l3, np.ones(len(l3)), qq)
                else:
                    hl = 1.0 if cls == "경기·인천" else 2.0
                    ests[f"주규칙{int(qq*100)}"] = wq(p6, [0.5 ** (x / hl) for x in a6], qq)
            for hl in (0.5, 3.0):
                ests[f"최근가중(반감{hl:g}m)중위"] = wq(p6, [0.5 ** (x / hl) for x in a6], 0.5)
            ests["최근5건중위"] = float(np.median(pr[np.argsort(ag)[:5]])) if len(pr) >= 5 else np.nan
            ests["최근3건평균"] = float(np.mean(pr[np.argsort(ag)[:3]])) if len(pr) >= 3 else np.nan
            ests["최근3건중위"] = float(np.median(pr[np.argsort(ag)[:3]])) if len(pr) >= 3 else np.nan
            # 2026-10-27 단지 시세 흐름: 같은 평형 최근 3개월 중위 ÷ 4~9개월 전 중위 - 1 (최근 2건+, 이전 3건+)
            r3, r9 = pr[ag <= 3], pr[(ag > 4) & (ag <= 9)]
            trd = float((np.median(r3) / np.median(r9) - 1) * 100) if len(r3) >= 2 and len(r9) >= 3 else np.nan
            rows.append(dict(cls=cls, trd=trd, t=float(T["t"]), n3=len(p3), n6=len(p6), tr12=tr12, hh=h, actual=float(T["price"]), **{"e_" + k2: v for k2, v in ests.items()}))
    D = pd.DataFrame(rows)
    D.to_json("backtest-sale-rule.json", orient="records", force_ascii=False)
    print(f"  시험 가능 {len(D):,}건, 세대수 연결 {D['hh'].notna().sum():,}건({D['hh'].notna().mean() * 100:.0f}%)")
    report(D)
    write_params(D)
    try:
        import accuracy_ledger as _led
        for cls, cur in MAIN_RULE.items():
            d = D[(D.cls == cls) & D[cur].notna()]
            if len(d) >= 1000:
                st = _stat(d, cur)
                _led.record(ab.cyc, "sale_market_" + {"서울": "seoul", "경기·인천": "gi", "지방": "local"}[cls], {"n": st["n"], "err": st["err"], "bias": st["bias"], "hi10": st["hi10"], "hi15": st["hi15"]}, f"예상매도가 vs 시장 거래({cls})")
    except Exception as e:
        print("  원장 기록 건너뜀:", e)
    try:
        write_challenger(D)
    except Exception as e:
        print("  개선 후보 점검 건너뜀:", e)


def trend_report(D):
    """2026-10-27(사용자: 호황이면 더 높게·하락이면 더 보수적으로 - 단지 시세 흐름 반영) 현재 규칙(지역별 주규칙)이 오르는/내리는 단지에서 한쪽으로 치우치나, 흐름을 반영하면 나아지나"""
    out = {}
    d = D[D["trd"].notna()].copy()
    if len(d) < 1000: print("  흐름 점검: 표본 부족"); return
    d["cur"] = [d.loc[i, MAIN_RULE[d.loc[i, "cls"]]] for i in d.index]
    d = d[d["cur"].notna()]
    d["r"] = d["actual"] / d["cur"] - 1
    bins = [(-999, -8, "하락 -8%↓"), (-8, -3, "하락 -8~-3%"), (-3, 3, "보합 ±3%"), (3, 8, "상승 +3~8%"), (8, 999, "상승 +8%↑")]
    def line(G):
        r = G["r"]
        return {"n": int(len(G)), "bias": round(float(r.median()) * 100, 2), "err": round(float(r.abs().median()) * 100, 2), "hi10": round(float((r < -0.10).mean()) * 100, 1), "lo10": round(float((r > 0.10).mean()) * 100, 1)}
    print("\n==== 📈 단지 시세 흐름별 현재 규칙의 치우침 (bias +: 실제가 예상보다 비쌌음) ====")
    for cls in ("전체", "서울", "경기·인천", "지방"):
        G0 = d if cls == "전체" else d[d.cls == cls]
        out[cls] = {}
        for lo, hi, lab in bins:
            G = G0[(G0.trd > lo) & (G0.trd <= hi)]
            if len(G) >= 150: out[cls][lab] = line(G)
        print(f"[{cls}] 흐름 계산된 {len(G0):,}건 (전체의 {len(G0) / len(D) * 100:.0f}%)")
        for lab, v in out[cls].items(): print(f"   {lab:<12}", v)
    print("\n==== 흐름을 예상매도가에 반영하면? (예상 × (1 + k × 흐름%)) ====")
    cmp = {}
    for k in (0.0, 0.1, 0.2, 0.3, 0.5):
        adj = d["cur"] * (1 + k * d["trd"].clip(-15, 15) / 100)
        r = d["actual"] / adj - 1
        cmp[k] = {"err": round(float(r.abs().median()) * 100, 3), "bias": round(float(r.median()) * 100, 2), "hi10": round(float((r < -0.10).mean()) * 100, 2), "hi15": round(float((r < -0.15).mean()) * 100, 2), "p10": round(float(np.quantile(r, .1)) * 100, 1)}
        print(f"   k={k}", cmp[k])
    # 하락·상승 구간만 따로(상승에서만 올리기 / 하락에서만 내리기)
    for nm, mk in (("상승(+3%↑)만 반영", d.trd > 3), ("하락(-3%↓)만 반영", d.trd < -3)):
        for k in (0.2, 0.5):
            adj = np.where(mk, d["cur"] * (1 + k * d["trd"].clip(-15, 15) / 100), d["cur"])
            r = d["actual"] / adj - 1
            print(f"   {nm} k={k}", {"err": round(float(np.median(np.abs(r))) * 100, 3), "hi10": round(float((r < -0.10).mean()) * 100, 2), "hi15": round(float((r < -0.15).mean()) * 100, 2)})
    out["adj"] = cmp
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 단지 시세 흐름별 치우침\n```json\n" + json.dumps(out, ensure_ascii=False, indent=1) + "\n```\n")


def report(D):
    ecols = [c for c in D.columns if c.startswith("e_")]
    def line(d):
        out = []
        for c in ecols:
            r = d["actual"] / d[c]
            out.append(f"{c[2:]:<22} 오차{np.nanmedian(np.abs(r - 1)) * 100:4.1f}% 치우침{(np.nanmedian(r) - 1) * 100:+5.1f}% 과대{(r < 0.9).mean() * 100:3.0f}%")
        return out
    print("\n==== 🎯 주규칙 기준 지점 40/50/60% ====")
    def tail(d, c):
        r = d["actual"] / d[c]
        return f"오차 {np.nanmedian(np.abs(r - 1)) * 100:5.2f}% 치우침 {(np.nanmedian(r) - 1) * 100:+5.2f}% | 예상이 10%+ 높음 {(r < 0.9).mean() * 100:4.1f}% · 15%+ 높음 {(r < 0.85).mean() * 100:4.1f}% · 하위10% {(np.nanquantile(r, .10) - 1) * 100:+6.1f}% | 10%+ 낮음 {(r > 1.1).mean() * 100:4.1f}%"
    for cls in ("전체", "서울", "경기·인천", "지방"):
        d = D if cls == "전체" else D[D.cls == cls]
        for nm, lo, hi in (("전체", 0, 999), ("6m 3~4건", 3, 5), ("5~9건", 5, 10), ("10건+", 10, 999)):
            dd = d[(d.n6 >= lo) & (d.n6 < hi)]
            if len(dd) < 300: continue
            print(f"[{cls}·{nm}] n{len(dd):,}")
            for q in (40, 50, 60): print(f"   {q}%", tail(dd, f"e_주규칙{q}"))
    trend_report(D)
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


MAIN_RULE = {"서울": "e_최근3건중위", "경기·인천": "e_최근가중(반감1m)중위", "지방": "e_최근가중(반감2m)중위"}


def _stat(d, c):
    r = (d["actual"] / d[c]).replace([np.inf, -np.inf], np.nan).dropna()
    return {"n": int(len(r)), "err": round(float(np.median(np.abs(r - 1))) * 100, 3), "bias": round(float(np.median(r) - 1) * 100, 3),
            "hi10": round(float((r < 0.9).mean()) * 100, 2), "hi15": round(float((r < 0.85).mean()) * 100, 2)}


def challenger_check(D):
    """2026-10-25(사용자: 매주 지금보다 더 나은 계산 방법이 있는지 확인하고 오차를 더 줄일 방법을 찾아야 함)
    지역별 '현재 규칙'(MAIN_RULE)과 나머지 후보 규칙을 같은 거래로 비교. 교체 후보 조건(모두 만족):
      ① 시험 기간을 앞·뒤 절반으로 나눈 두 구간 모두에서 보통 오차가 현재보다 0.05%p 이상 작음
      ② 두 구간 모두에서 '예상이 10%+ 높음' 비율이 현재보다 0.3%p 넘게 늘지 않음(손해 쪽 위험 유지)
      ③ 15%+ 높음도 0.2%p 넘게 늘지 않음
    조건을 모두 채워도 자동 적용하지 않음 - 사용자가 확인 후 결정(튀는 가격 원칙)."""
    out = {}
    tmid = float(D["t"].median())
    cols = [c for c in D.columns if c.startswith("e_") and not c.startswith("e_주규칙")]
    for cls, cur in MAIN_RULE.items():
        d = D[(D.cls == cls) & D[cur].notna()]
        if len(d) < 1000: continue
        halves = (d[d.t < tmid], d[d.t >= tmid])
        base = [_stat(h, cur) for h in halves]
        rows = []
        for c in cols:
            if c == cur: continue
            h2 = [h[h[c].notna() & h[cur].notna()] for h in halves]
            if min(len(x) for x in h2) < 500: continue
            st = [_stat(x, c) for x in h2]; bs = [_stat(x, cur) for x in h2]
            dErr = [bs[i]["err"] - st[i]["err"] for i in range(2)]
            dHi10 = [st[i]["hi10"] - bs[i]["hi10"] for i in range(2)]
            dHi15 = [st[i]["hi15"] - bs[i]["hi15"] for i in range(2)]
            ok = all(x >= 0.05 for x in dErr) and all(x <= 0.3 for x in dHi10) and all(x <= 0.2 for x in dHi15)
            rows.append({"name": c[2:], "errGain": round(sum(dErr) / 2, 3), "hi10Diff": round(sum(dHi10) / 2, 2), "hi15Diff": round(sum(dHi15) / 2, 2), "ok": bool(ok), "n": int(sum(len(x) for x in h2)), "stat": st[1]})
        rows.sort(key=lambda x: (not x["ok"], -x["errGain"]))
        out[cls] = {"current": cur[2:], "currentStat": _stat(d, cur), "best": rows[:3], "adoptable": [r["name"] for r in rows if r["ok"]]}
    return out


def write_challenger(D):
    from datetime import datetime, timezone
    res = challenger_check(D)
    for cls, v in res.items():
        b = v["best"][0] if v["best"] else None
        print(f"  🔎 개선 후보 점검 [{cls}] 현재 {v['current']} 오차 {v['currentStat']['err']}% · 10%+높음 {v['currentStat']['hi10']}% → " + (f"최선 {b['name']} 오차 {-b['errGain']:+.2f}%p · 손해쪽 {b['hi10Diff']:+.2f}%p · {'✅ 교체 후보' if b['ok'] else '조건 미달'}" if b else "후보 없음"))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 예상매도가 개선 후보 점검\n```json\n" + json.dumps(res, ensure_ascii=False, indent=1) + "\n```\n")
    if not os.environ.get("WRITE_PARAMS"): return
    now = datetime.now(timezone.utc).isoformat()
    prev = {}
    try:
        import requests
        rr = requests.get(f"{ab.cyc.SUPABASE_URL}/rest/v1/leader_follower_cache?select=payload&id=eq.signal%7C__challenger_sale__", headers=ab.cyc.HEADERS, timeout=60)
        if rr.ok and rr.json(): prev = rr.json()[0].get("payload") or {}
    except Exception:
        prev = {}
    hist = [h for h in (prev.get("history") or []) if h.get("at", "")[:10] != now[:10]]
    hist.insert(0, {"at": now, "adoptable": {c: v["adoptable"] for c, v in res.items()}})
    P = {"generatedAt": now, "basis": "2025년~ 전국 아파트 실거래, 직전 정보만으로 예측(같은 단지·평형 6개월 3건+)", "result": res, "history": hist[:12]}
    ab.cyc.upsert_rows([{"id": "signal|__challenger_sale__", "payload": ab.cyc.clean_json(P), "fetched_at": now}])
    print("  개선 후보 점검 저장")


def build_params(D):
    """6개월 같은 평형 3건 이상일 때: 지역별 규칙(서울 최근3건·경기인천 반감1개월·지방 반감2개월)의 회전율 구간별 치우침·하방"""
    X = D[D.hh.notna() & (D.hh > 0)].copy()
    if len(X) < 1500: return None
    X["turn"] = X.tr12 / X.hh * 100
    qs = X.turn.quantile([1 / 3, 2 / 3]).values
    X["tb"] = pd.cut(X.turn, [-1, qs[0], qs[1], 1e9], labels=["낮음", "중간", "높음"])
    out = {"cuts": [round(float(qs[0]), 2), round(float(qs[1]), 2)], "n": int(len(X)), "table": {}}
    for cls, col in MAIN_RULE.items():
        out["table"][cls] = {}
        for b in ("낮음", "중간", "높음"):
            d = X[(X.cls == cls) & (X.tb == b) & X[col].notna()]
            if len(d) < 200: continue
            r = (d["actual"] / d[col]).replace([np.inf, -np.inf], np.nan).dropna()
            out["table"][cls][b] = {"bias": round(float(np.median(r) - 1), 4), "p25": round(float(r.quantile(.25) - 1), 4), "n": int(len(r))}
    return out


def write_params(D):
    if not os.environ.get("WRITE_PARAMS"): return
    from datetime import datetime, timezone
    P = build_params(D)
    if not P:
        print("  보정 표 만들기엔 세대수 연결 표본이 부족해요 - 저장 안 함"); return
    P["generatedAt"] = datetime.now(timezone.utc).isoformat()
    P["basis"] = "지역별 최근 거래 규칙 예상 대비 실제 거래가(회전율 3분위) - 직전 정보만으로 2025년~ 아파트 거래 검증"
    ab.cyc.upsert_rows([{"id": "signal|__salerule_main__", "payload": ab.cyc.clean_json(P), "fetched_at": P["generatedAt"]}])
    print("  보정 표 저장:", P["cuts"], {c: list(v.keys()) for c, v in P["table"].items()})


if __name__ == "__main__":
    main()
