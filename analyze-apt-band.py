"""아파트 단지 안에서 '잘 거래되는 평형' 검증(2026-11-21). 단지마다 전용면적 묶음(평형)별 최근 12개월 거래 건수로 활발/보통/비활발을 매기고,
그 뒤 거래(오늘 기준 3·6·9·12개월 전 시점 4곳 → 이후 거래)가 실제로 활발 평형에 더 몰렸는지 확인. 앱 화면 규칙과 같은 기준(aptBandRows).
활발 = 단지 내 거래 비중이 균등(1/평형 수)의 1.2배 이상, 비활발 = 0.5배 이하(또는 직전 12개월 1건 이하), 나머지 보통. 직거래 제외, 평형 3개 이상·직전 12개월 12건 이상 단지만."""
import importlib.util, os, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py")); cyc = importlib.util.module_from_spec(sp); sp.loader.exec_module(cyc)
avm = cyc.avm
raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type", extra_filter="&deal_date=gte.20230101")
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
res = {}
for back in (3, 6, 9, 12):
    T = last - back   # 판정 시점(이 달까지의 자료)
    pre = df[(df["ym"] > T - 12) & (df["ym"] <= T)]; fwd = df[(df["ym"] > T) & (df["ym"] <= last)]
    rows = []
    for ck, g in pre.groupby("ckey", observed=True):
        if len(g) < 12: continue
        mp = bands(g["sz"].tolist()); allsz = set(g["sz"]) | set(fwd[fwd["ckey"] == ck]["sz"]) if False else set(g["sz"])
        nb = len(set(mp.values()))
        if nb < 3: continue
        cnt = g["sz"].map(mp).value_counts(); f = fwd[fwd["ckey"] == ck]
        fc = f["sz"].map(lambda s: mp.get(s, min(mp, key=lambda m: abs(m - s)) if abs(min(mp, key=lambda m: abs(m - s)) - s) <= 1 else None)).map(lambda s: mp.get(s, s) if s is not None else None).value_counts() if len(f) else pd.Series(dtype=int)
        tot = len(g); ftot = int(fc.sum())
        if ftot < 3: continue
        for b in set(mp.values()):
            sh = cnt.get(b, 0) / tot; v = "활발" if sh >= 1.2 / nb else ("비활발" if (sh <= 0.5 / nb or cnt.get(b, 0) <= 1) else "보통")
            rows.append((v, fc.get(b, 0) / ftot, fc.get(b, 0), nb, sh))
    r = pd.DataFrame(rows, columns=["v", "fshare", "fcnt", "nb", "pshare"])
    out = {}
    for v, g in r.groupby("v"):
        out[v] = {"평형수": len(g), "이후 거래 비중 평균": round(float(g["fshare"].mean()) * 100, 1), "기준(균등)": round(float((1 / g["nb"]).mean()) * 100, 1), "이후 거래 0건인 평형 %": round(float((g["fcnt"] == 0).mean()) * 100, 1)}
    res[f"{back}개월 전 시점(이후 {back}개월)"] = out
    print(f"[{back}개월 전] 단지·평형 {len(r):,}개", json.dumps(out, ensure_ascii=False), flush=True)
json.dump(res, open("apt-band-test.json", "w"), ensure_ascii=False, indent=1)
