"""
🌊 거래량·가격 흐름별 '낙찰 뒤 실제 되판 가격' 시험 (2026-11-10, 사용자: 수도권 아파트는 더 오르기 어렵다고 본다 - 거래량이 줄어드는 단지에서 되팔 때 실제로 예상보다 얼마나 낮게 나왔나)
입찰 35일 전(채점 사례 cutoff) 자료만으로 같은 단지의 가격 흐름(최근 60일 vs 120~240일 전 ㎡당 중위값)·거래량 흐름(최근 90일 vs 그 전 90일 거래 수, 같은 단지 전 평형)을 재고,
결과는 y = 낙찰 뒤 6개월 같은 단지·평형 시장 중위값(mkt) ÷ 앱 예상매도가(saleFinal) - 1 (음수 = 예상보다 낮게 팔림). 정답이 3건 이상 거래로 만들어진 사례만(정답 노이즈 방지).
입력 ROWS_DIR(채점 사례 rows.json), 출력 flow-vs-resale.json. 측정 전용.
"""
import os, json, glob, importlib.util
import numpy as np, pandas as pd, requests
HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("avm", os.path.join(HERE, "train-avm.py")); avm = importlib.util.module_from_spec(_s); _s.loader.exec_module(avm)
_s2 = importlib.util.spec_from_file_location("abc", os.path.join(HERE, "analyze-bidcases.py")); abc = importlib.util.module_from_spec(_s2); _s2.loader.exec_module(abc)


def to_days(d):
    d = np.asarray(d, dtype=np.int64)
    return (d // 10000 - 2000) * 372 + ((d // 100) % 100 - 1) * 31 + (d % 100 - 1)


def main():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,bunji,size,price,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20240901")
    df = raw[raw["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy(); df = df[df["dealing_type"].fillna("") != "직거래"]
    for c in ("size", "price", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["size", "price", "deal_date"]); df = df[(df["price"] > 0) & (df["size"] >= 20) & (df["size"] <= 250)]
    df["ppm"] = df["price"] / df["size"]; df["day"] = to_days(df["deal_date"].astype(int).values)
    df["rn"] = df["region"].map(abc.region_norm); df["dk"] = df["dong"].map(abc.dong_key); df["bj"] = df["bunji"].astype(str).str.strip()
    cxg = {k: (g["day"].values, g["size"].values, g["ppm"].values) for k, g in df.groupby(["rn", "dk", "bj"])}
    dgg = {k: g["day"].values for k, g in df.groupby(["rn", "dk"])}
    cases = {c["id"]: c for c in requests.get(os.environ.get("SITE_URL", "https://1234auction.vercel.app") + "/api/auction?kind=bidCases", timeout=180).json() if isinstance(c, dict) and c.get("id")}
    rows = []
    for f in glob.glob(os.path.join(os.environ.get("ROWS_DIR", "."), "**", "rows.json"), recursive=True): rows += json.load(open(f))
    out = []
    for r in rows:
        if r.get("err") or not r.get("mkt") or not r.get("saleFinal") or (r.get("mktN") or 0) < 3: continue
        c = cases.get(r["id"])
        if not c: continue
        cut = to_days([int(str(r["cutoff"]).replace("-", ""))])[0]; area = float(c.get("areaM2") or 0)
        key = (abc.region_norm(c.get("addrJibun")), abc.dong_key(c.get("dong")), str(c.get("bunji") or "").strip())
        g = cxg.get(key)
        if g is None or not area: continue
        d_all = g[0]; m = np.abs(g[1] - area) <= 3; d_b, p_b = g[0][m], g[2][m]
        a = p_b[(d_b <= cut) & (d_b > cut - 60)]; b = p_b[(d_b <= cut - 120) & (d_b > cut - 240)]
        cxP = float(np.log(np.median(a) / np.median(b))) if len(a) >= 3 and len(b) >= 3 else np.nan
        n1 = int(((d_all <= cut) & (d_all > cut - 90)).sum()); n0 = int(((d_all <= cut - 90) & (d_all > cut - 180)).sum())
        if n0 + n1 < 6: continue
        cxV = float(np.log((n1 + 1) / (n0 + 1)))
        dd = dgg.get(key[:2]); dgV = np.nan
        if dd is not None:
            e1 = int(((dd <= cut) & (dd > cut - 90)).sum()); e0 = int(((dd <= cut - 90) & (dd > cut - 180)).sum())
            if e0 + e1 >= 30: dgV = float(np.log((e1 + 1) / (e0 + 1)))
        cls = "서울" if str(r["lawd"]).startswith("11") else ("경기·인천" if str(r["lawd"])[:2] in ("41", "28") else "지방")
        out.append({"y": r["mkt"] / r["saleFinal"] - 1, "cxP": cxP, "cxV": cxV, "dgV": dgV, "cls": cls, "go": bool(r.get("go")), "date": r["saleDate"], "n6": r.get("n6")})
    O = pd.DataFrame(out); print(f"사례 {len(O):,}건")
    def row(G): return {"n": int(len(G)), "되판가 vs 예상 중앙%": round(float(G["y"].median()) * 100, 1), "예상보다 5%+ 낮게 팔림%": round(float((G["y"] < -0.05).mean()) * 100, 1), "10%+ 낮게%": round(float((G["y"] < -0.10).mean()) * 100, 1), "하위10% 지점%": round(float(G["y"].quantile(0.1)) * 100, 1)}
    res = {"n": int(len(O))}
    vb = lambda v: pd.cut(v, [-9, -0.4, -0.1, 0.1, 0.4, 9], labels=["거래량 급감", "감소", "비슷", "증가", "급증"])
    pb = lambda v: pd.cut(v, [-9, -0.01, 0.03, 9], labels=["가격 하락·횡보(~+1%)", "소폭 상승(+1~3%)", "상승(+3%↑)"])
    for nm, S in (("전체", O), ("서울", O[O["cls"] == "서울"]), ("경기·인천", O[O["cls"] == "경기·인천"]), ("지방", O[O["cls"] == "지방"]), ("후보(go)만", O[O["go"]])):
        t = {}
        for lab, G in S.groupby(vb(S["cxV"]), observed=True):
            if len(G) >= 40: t[str(lab)] = row(G)
        res["단지 거래량 흐름별 - " + nm] = t
    S = O[O["cxP"].notna()]; t = {}
    for lp, Gp in S.groupby(pb(S["cxP"]), observed=True):
        for lv, G in Gp.groupby(np.where(Gp["cxV"] <= -0.1, "거래량 감소", np.where(Gp["cxV"] >= 0.1, "거래량 증가", "거래량 비슷"))):
            if len(G) >= 40: t[f"{lp} × {lv}"] = row(G)
    res["가격 × 거래량 (전체)"] = t
    S = O[O["dgV"].notna()]; t = {}
    for lab, G in S.groupby(vb(S["dgV"]), observed=True):
        if len(G) >= 40: t[str(lab)] = row(G)
    res["법정동 거래량 흐름별"] = t
    print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("flow-vs-resale.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
