"""아파트 단지 안에서 '잘 거래되는 평형' 검증(2026-11-21). 단지마다 전용면적 묶음(평형)별 최근 12개월 거래 건수로 활발/보통/비활발을 매기고,
그 뒤 거래(오늘 기준 3·6·9·12개월 전 시점 4곳 → 이후 거래)가 실제로 활발 평형에 더 몰렸는지 확인. 앱 화면 규칙과 같은 기준(aptBandRows).
활발 = 단지 내 거래 비중이 균등(1/평형 수)의 1.2배 이상, 비활발 = 0.5배 이하(또는 직전 12개월 1건 이하), 나머지 보통. 직거래 제외, 평형 3개 이상·직전 12개월 12건 이상 단지만."""
import importlib.util, os, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py")); cyc = importlib.util.module_from_spec(sp); sp.loader.exec_module(cyc)
avm = cyc.avm
raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type", extra_filter="&deal_date=gte.20190101")
df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
for c in ("price", "size", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"]); df = df[(df["price"] > 0) & (df["size"] > 10)]
df["ym"] = (df["deal_date"] // 10000) * 12 + (df["deal_date"] // 100 % 100) - 1   # 월 번호
df["ckey"] = df["region"].astype(str) + "|" + df["dong"].astype(str).str.split().str[-1] + "|" + df["danji"].astype(str)
df["sz"] = df["size"].round().astype(int)
last = int(df["ym"].max()) - 1   # 마지막 달은 신고 지연으로 덜 들어옴
print(f"거래 {len(df):,}건 · 마지막 완전한 달 {last // 12}-{last % 12 + 1:02d}", flush=True)
def bands(sizes):   # 1㎡ 이내 이웃 크기는 한 평형으로 묶음
    u = sorted(set(sizes)); g = {}; cur = u[0]
    for s in u:
        if s - cur > 1: cur = s
        g[s] = cur
    return g
def judge(g, mp):
    cnt = g["sz"].map(mp).value_counts(); nb = len(set(mp.values())); tot = len(g)
    return {b: ("활발" if cnt.get(b, 0) / tot >= 1.2 / nb else ("비활발" if (cnt.get(b, 0) / tot <= 0.5 / nb or cnt.get(b, 0) <= 1) else "보통")) for b in set(mp.values())}, cnt, nb, tot
res = {}
WINS = (12, 36, 60); MINTOT = {12: 12, 36: 12, 60: 12}
for back in (3, 6, 9, 12):
    T = last - back
    fwd = df[(df["ym"] > T) & (df["ym"] <= last)]
    fgrp = {k: g for k, g in fwd.groupby("ckey", observed=True)}
    rows = []
    pre_all = df[(df["ym"] > T - 60) & (df["ym"] <= T)]
    for ck, g60 in pre_all.groupby("ckey", observed=True):
        f = fgrp.get(ck)
        if f is None or len(f) < 3: continue
        g12 = g60[g60["ym"] > T - 12]
        j12 = None
        info = {}
        for w in WINS:
            g = g60 if w == 60 else g60[g60["ym"] > T - w]
            if len(g) < MINTOT[w]: info[w] = None; continue
            mp = bands(g["sz"].tolist()); nb = len(set(mp.values()))
            if nb < 2: info[w] = None; continue
            info[w] = (g, mp)
        # 미래 거래를 12M 기준 평형 묶음이 아니라 가장 풍부한 창(60M)의 묶음 기준으로 통일해 비교(같은 평형 단위)
        base = info[60] or info[36] or info[12]
        if base is None: continue
        mpb = base[1]
        fc = f["sz"].map(lambda s_: next((mpb[k2] for k2 in (s_, s_ - 1, s_ + 1) if k2 in mpb), None)).dropna().value_counts(); ftot = int(fc.sum())
        if ftot < 3: continue
        for w in WINS:
            if info[w] is None: continue
            g, mp = info[w]
            # 이 창의 묶음을 기준 묶음(mpb)으로 다시 이름 붙이기: 각 기준 평형이 이 창에서 얼마나 거래됐는지
            cnt = g["sz"].map(lambda s_: next((mpb[k2] for k2 in (s_, s_ - 1, s_ + 1) if k2 in mpb), None)).dropna().value_counts(); tot = int(cnt.sum())
            if tot < 6: continue
            nbb = len(set(mpb.values()))
            for b in set(mpb.values()):
                sh = cnt.get(b, 0) / tot; v = "활발" if sh >= 1.2 / nbb else ("비활발" if (sh <= 0.5 / nbb or cnt.get(b, 0) <= 1) else "보통")
                rows.append((w, v, fc.get(b, 0) / ftot, fc.get(b, 0), nbb, info[12] is None))
    r = pd.DataFrame(rows, columns=["w", "v", "fshare", "fcnt", "nb", "short12"])
    out = {}
    for w in WINS:
        rw = r[r["w"] == w]
        out[f"{w}개월 창"] = {v: {"평형수": len(g), "이후 거래 비중 평균%": round(float(g["fshare"].mean()) * 100, 1), "균등%": round(float((1 / g["nb"]).mean()) * 100, 1), "이후 0건 %": round(float((g["fcnt"] == 0).mean()) * 100, 1)} for v, g in rw.groupby("v")}
    rs = r[(r["w"] == 60) & r["short12"]]   # 12개월 자료는 모자라지만 5년 자료로는 판정되는 단지
    out["12개월 부족·5년으로만 판정"] = {v: {"평형수": len(g), "이후 거래 비중 평균%": round(float(g["fshare"].mean()) * 100, 1), "균등%": round(float((1 / g["nb"]).mean()) * 100, 1), "이후 0건 %": round(float((g["fcnt"] == 0).mean()) * 100, 1)} for v, g in rs.groupby("v")}
    out["판정 가능 단지·평형 수"] = {f"{w}개월": int((r["w"] == w).sum()) for w in WINS}
    res[f"{back}개월 전"] = out
    print(f"[{back}개월 전]", json.dumps(out, ensure_ascii=False), flush=True)
json.dump(res, open("apt-band-test.json", "w"), ensure_ascii=False, indent=1)
