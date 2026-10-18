"""
🔬 한국부동산원(R-ONE) 시군구 월간 아파트 매매가격지수로 오래된 거래를 지금 시점에 맞추면 예상매도가가 정확해지나 (2026-10-18, 사용자: 오픈API 인증키 제공)
정답 = 시험 거래의 실제 가격, 직전 정보만 사용(같은 단지·같은 평형 ±3㎡ 중개거래). 지수는 '시험 거래 달의 직전 달까지'만 사용(R1·R2) / 두 달 전까지만(R3·R4, 발표 지연 고려).
 V0  현재: 6개월 원값, 반감 2개월 가중 중위값
 R1  6개월 거래를 R-ONE 지수로 지금(직전 달) 시점에 맞춘 뒤 반감 2개월 가중 중위값
 R2  12개월 거래를 R-ONE 지수로 맞춘 뒤 반감 3개월 가중 중위값
 R3/R4  R1/R2에서 지수를 두 달 전까지만 사용
 R5  V0 × (직전 달 지수 ÷ 3개월 전 지수)^0.5 (최근 추세를 반만 얹음, ±3% 제한)
키: 환경변수 REB_API_KEY (R-ONE 인증키, 값은 로그에 찍지 않음)
"""
import os, re, json, time, importlib.util
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
REB_KEY = os.environ.get("REB_API_KEY", "").strip()
rng = np.random.default_rng(9)
MAX_TEST = int(os.environ.get("MAX_TEST", "40000"))
BASE = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"


def fetch_reb(statbl, cycle="MM", start="202101", end="202612"):
    rows, page = [], 1
    while True:
        r = requests.get(BASE, params={"KEY": REB_KEY, "Type": "json", "pIndex": page, "pSize": 1000, "STATBL_ID": statbl, "DTACYCLE_CD": cycle, "START_WRTTIME": start, "END_WRTTIME": end}, timeout=60)
        d = r.json()
        if "RESULT" in d: raise RuntimeError(f"R-ONE 오류 {d['RESULT']}")
        blk = list(d.values())[0]
        got = [b for b in blk if "row" in b]
        got = got[0]["row"] if got else []
        rows += got
        total = blk[0]["head"][0]["list_total_count"]
        if len(rows) >= total or not got: break
        page += 1; time.sleep(0.2)
    return rows


def norm_city(c):
    return re.sub(r"(시|군)$", "", c) if len(c) > 2 else c


def is_local(region):
    s = str(region or "").split(" ")[0]
    return not (s.startswith("서울") or s[:2] in ("경기", "인천"))


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
    if not REB_KEY: raise SystemExit("REB_API_KEY가 없어요")
    raw = fetch_reb("A_2024_00045")
    print(f"  R-ONE 월간 아파트 매매가격지수 {len(raw):,}행")
    # 분류 경로 → (시도, 시군구) 키. 시·군 단위(경로 2단계)를 우선, 구 단위만 있으면 같은 시의 구들을 평균
    paths = {}
    for r in raw:
        full = r["CLS_FULLNM"]; p = full.split(">")
        if len(p) < 2: continue
        if re.search(r"(권|지역)$", p[-1]) and len(p) == 2: continue
        ym = int(r["WRTTIME_IDTFR_ID"][:4]) * 12 + int(r["WRTTIME_IDTFR_ID"][4:6])
        paths.setdefault(tuple(p), {})[ym] = float(r["DTA_VAL"])
    idx = {}
    for p, ser in paths.items():
        key = (ab.sido_norm(p[0]), norm_city(p[1]))
        if len(p) == 2: idx[key] = ser
    for p, ser in paths.items():  # 구 단위만 있는 시
        key = (ab.sido_norm(p[0]), norm_city(p[1]))
        if len(p) == 3 and key not in idx:
            idx.setdefault(("_g",) + key, []).append(ser)
    for k in [k for k in idx if k[0] == "_g"]:
        sers = idx.pop(k); common = set.intersection(*[set(s) for s in sers])
        idx[k[1:]] = {m: float(np.mean([s[m] for s in sers])) for m in common}
    print(f"  지수 시군구 {len(idx):,}곳")

    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20230101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "floor", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10) & (tr["dealing_type"] != "직거래")]
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["rg"] = tr["region"].map(ab.region_norm); tr["bj"] = tr["bunji"].astype(str).str.strip()
    tr["ts"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); tr = tr.dropna(subset=["ts", "rg"])
    tr["t"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
    tr["ym"] = (tr["ts"].dt.year * 12 + tr["ts"].dt.month).astype(int)
    tr["cls"] = tr["region"].map(cls_of)
    print(f"  거래 {len(tr):,}건")

    def rkey(rg):
        s, c = rg.split(" ", 1)[0], rg.split(" ", 1)[1] if " " in rg else ""
        return (s, norm_city(c))
    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "bj"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    test = []
    for k, g in groups.items():
        if rkey(k[0]) not in idx: continue
        for i in np.where(g["t"].values >= t_start)[0]: test.append((k, i))
    print(f"  지수 연결되는 시험 후보 {len(test):,}건 (전체 거래 {sum(len(g) for g in groups.values()):,}건)")
    sel = rng.choice(len(test), min(len(test), MAX_TEST * 2), replace=False); test = [test[i] for i in sel]
    rows = []
    for k, i in test:
        if len(rows) >= MAX_TEST: break
        g = groups[k]; T = g.iloc[i]; H = g.iloc[:i]; H = H[H["t"] < T["t"]]
        ser = idx[rkey(k[0])]
        sm = H[(H["size"] - T["size"]).abs() <= 3]
        if not len(sm): continue
        ym0 = int(T["ym"]); age = (T["t"] - sm["t"].values) / 30.4
        m6 = age <= 6; m12 = age <= 12
        if m12.sum() < 1: continue
        price = sm["price"].values.astype(float); ymv = sm["ym"].values
        rec = dict(cls=T["cls"], n6=int(m6.sum()), actual=float(T["price"]))
        if m6.sum() >= 1: rec["V0"] = wmed(price[m6], 0.5 ** (age[m6] / 2.0))
        for lag, tag in ((1, ""), (2, "L")):
            i0 = ser.get(ym0 - lag)
            if not i0: continue
            ad = np.array([i0 / ser[y] if y in ser else np.nan for y in ymv])
            ok6 = m6 & ~np.isnan(ad); ok12 = m12 & ~np.isnan(ad)
            if ok6.any(): rec[f"R1{tag}"] = wmed(price[ok6] * ad[ok6], 0.5 ** (age[ok6] / 2.0))
            if ok12.any(): rec[f"R2{tag}"] = wmed(price[ok12] * ad[ok12], 0.5 ** (age[ok12] / 3.0))
        i1, i4 = ser.get(ym0 - 1), ser.get(ym0 - 4)
        if i1 and i4:
            ch = i1 / i4 - 1; rec["trend"] = ch
            if "V0" in rec: rec["R5"] = rec["V0"] * (1 + float(np.clip(ch * 0.5, -0.03, 0.03)))
        rows.append(rec)
    D = pd.DataFrame(rows)
    D.to_json("backtest-sale-reb.json", orient="records", force_ascii=False)
    print(f"  시험 {len(D):,}건")
    report(D)


def line(d, c):
    x = d[d[c].notna() & d["V0"].notna()]
    if len(x) < 100: return None
    r = x["actual"] / x[c]
    return f"n{len(x):6,} 오차{np.median(np.abs(r - 1)) * 100:5.2f}% 치우침{(np.median(r) - 1) * 100:+6.2f}% 하방p10 {(r.quantile(.10) - 1) * 100:+6.1f}% p25 {(r.quantile(.25) - 1) * 100:+6.1f}%"


def report(D):
    V = ["V0", "R1", "R2", "R1L", "R2L", "R5"]
    D["tr"] = pd.cut(D["trend"], [-9, -0.01, 0.01, 9], labels=["하락(-1%↓)", "보합", "상승(+1%↑)"])
    for cls in ("지방", "서울", "경기·인천", None):
        for nm, m in (("6개월 3건+", D.n6 >= 3), ("6개월 1~2건", (D.n6 >= 1) & (D.n6 < 3))):
            d = D[m & ((D.cls == cls) if cls else True)]
            if len(d) < 300: continue
            print(f"\n===== {cls or '전국'} · {nm} n{len(d):,} =====")
            for c in V:
                s = line(d, c)
                if s: print(f"  {c:4} {s}")
            if cls == "지방" and nm == "6개월 3건+":
                for t in ["하락(-1%↓)", "보합", "상승(+1%↑)"]:
                    dd = d[d["tr"] == t]
                    if len(dd) < 300: continue
                    print(f"  -- 지수 추세 {t} n{len(dd):,}")
                    for c in V:
                        s = line(dd, c)
                        if s: print(f"     {c:4} {s}")


if __name__ == "__main__":
    main()
