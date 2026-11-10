"""
🌊 '오르는 단지에 입찰자가 몰리고 낙찰가가 시세에 가까워지는가' 검증 (2026-11-10, 사용자: 낙찰자가 몰린다는 건 수익성이 보인다는 것 = 오름 추세이고 거래량·거래금액이 받쳐 준다. '시세의 몇 %'는 앱 방향과 맞지 않다)
입찰 35일 전(채점 사례의 cutoff) 자료만으로 같은 단지·평형의 흐름을 재서, 낙찰 결과(입찰자 수·낙찰가÷예측)와 비교한다.
 - 가격 흐름 cxP = ln(최근 60일 ㎡당 중위값 ÷ 120~240일 전 ㎡당 중위값) (같은 단지·같은 평형 ±3㎡, 각 구간 3건 이상)
 - 거래량 흐름 cxV = ln((최근 90일 거래 수+1) ÷ (그 전 90일 거래 수+1))
 - 동·시군구 가격 흐름 dgP / sgP (같은 법정동·시군구 전체 거래 ㎡당 중위값, 같은 구간)
비교 대상: 현재 낙찰가 모델의 잔차 ln(실제 낙찰가 ÷ 모델 예측 wbP)와 응찰자 수. 모델이 흐름을 못 읽는다면 흐름이 오를수록 잔차(+)·입찰자 수가 커진다.
(학습에 안 쓴 2025-10-30 이후 사례만) 입력: ROWS_DIR(채점 사례 rows.json), SITE_URL(낙찰사례 API). 출력 flow-vs-winbid.json
"""
import os, json, glob, re, importlib.util
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("avm", os.path.join(HERE, "train-avm.py"))
avm = importlib.util.module_from_spec(_s); _s.loader.exec_module(avm)
_s2 = importlib.util.spec_from_file_location("abc", os.path.join(HERE, "analyze-bidcases.py"))
abc = importlib.util.module_from_spec(_s2); _s2.loader.exec_module(abc)
OOS = "2025-10-30"


def to_days(d):
    d = np.asarray(d, dtype=np.int64)
    return (d // 10000 - 2000) * 372 + ((d // 100) % 100 - 1) * 31 + (d % 100 - 1)


def main():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,bunji,size,price,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20250101")
    df = raw[raw["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    df = df[df["dealing_type"].fillna("") != "직거래"]
    for c in ("size", "price", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["size", "price", "deal_date"]); df = df[(df["price"] > 0) & (df["size"] >= 20) & (df["size"] <= 250)]
    df["ppm"] = df["price"] / df["size"]; df["day"] = to_days(df["deal_date"].astype(int).values)
    df["rn"] = df["region"].map(abc.region_norm); df["dk"] = df["dong"].map(abc.dong_key); df["bj"] = df["bunji"].astype(str).str.strip()
    cxg = {k: (g["day"].values, g["size"].values, g["ppm"].values) for k, g in df.groupby(["rn", "dk", "bj"])}
    dgg = {k: (g["day"].values, g["ppm"].values) for k, g in df.groupby(["rn", "dk"])}
    sgg = {k: (g["day"].values, g["ppm"].values) for k, g in df.groupby("rn")}
    print(f"거래 {len(df):,}건, 단지 {len(cxg):,}, 동 {len(dgg):,}")
    cases = {c["id"]: c for c in requests.get(os.environ.get("SITE_URL", "https://1234auction.vercel.app") + "/api/auction?kind=bidCases", timeout=180).json() if isinstance(c, dict) and c.get("id")}
    rows = []
    for f in glob.glob(os.path.join(os.environ.get("ROWS_DIR", "."), "**", "rows.json"), recursive=True): rows += json.load(open(f))

    def pchg(day, ppm, cut, w1=60, w0a=120, w0b=240, minn=3):
        a = ppm[(day <= cut) & (day > cut - w1)]; b = ppm[(day <= cut - w0a) & (day > cut - w0b)]
        return float(np.log(np.median(a) / np.median(b))) if len(a) >= minn and len(b) >= minn else np.nan

    out = []
    for r in rows:
        if r.get("err") or r["saleDate"] < OOS or not r.get("wbP") or not r.get("saleFinal") or not r.get("act") or r["act"] <= 0: continue
        c = cases.get(r["id"])
        if not c: continue
        cut = to_days([int(str(r["cutoff"]).replace("-", ""))])[0]; area = float(c.get("areaM2") or 0)
        key = (abc.region_norm(c.get("addrJibun")), abc.dong_key(c.get("dong")), str(c.get("bunji") or "").strip())
        x = {"id": r["id"], "res": float(np.log(r["act"] / r["wbP"])), "ratio": float(r["act"] / r["saleFinal"]), "bidders": c.get("bidders"), "fails": r.get("fails"), "n6": r.get("n6"), "lawd": str(r["lawd"]), "sale": r["saleDate"]}
        g = cxg.get(key)
        if g is not None and area:
            m = np.abs(g[1] - area) <= 3; d_, p_ = g[0][m], g[2][m]
            x["cxP"] = pchg(d_, p_, cut)
            n1 = int(((d_ <= cut) & (d_ > cut - 90)).sum()); n0 = int(((d_ <= cut - 90) & (d_ > cut - 180)).sum()); x["cxV"] = float(np.log((n1 + 1) / (n0 + 1)))
        dg = dgg.get(key[:2]); x["dgP"] = pchg(dg[0], dg[1], cut, minn=5) if dg is not None else np.nan
        sg = sgg.get(key[0]); x["sgP"] = pchg(sg[0], sg[1], cut, minn=20) if sg is not None else np.nan
        out.append(x)
    O = pd.DataFrame(out); print(f"사례 {len(O):,}건")
    res = {"n": int(len(O))}

    def tab(col, edges, labels, nmin=40):
        S = O[O[col].notna()].copy(); S["b"] = pd.cut(S[col], edges, labels=labels)
        t = {}
        for lab, G in S.groupby("b", observed=True):
            if len(G) < nmin: continue
            bd = G["bidders"].dropna()
            t[str(lab)] = {"n": int(len(G)), "낙찰가 ÷ 모델예측 중앙(+면 모델이 낮게 봄)": round(float(np.expm1(G["res"].median())) * 100, 1), "10%+ 높게 낙찰%": round(float((G["res"] > 0.10).mean()) * 100, 1),
                          "응찰자 중앙": float(bd.median()) if len(bd) else None, "응찰자 9명+%": round(float((bd >= 9).mean()) * 100, 1) if len(bd) else None}
        return t
    res["단지 가격 흐름(60일 vs 120~240일 전)"] = tab("cxP", [-9, -0.05, -0.02, 0.02, 0.05, 0.10, 9], ["-5%↓", "-5~-2%", "-2~+2%", "+2~+5%", "+5~+10%", "+10%↑"])
    res["단지 거래량 흐름(최근 90일 vs 그 전 90일)"] = tab("cxV", [-9, -0.4, -0.1, 0.1, 0.4, 9], ["급감", "감소", "비슷", "증가", "급증"])
    res["법정동 가격 흐름"] = tab("dgP", [-9, -0.03, 0.0, 0.03, 0.06, 9], ["-3%↓", "-3~0%", "0~+3%", "+3~+6%", "+6%↑"])
    res["시군구 가격 흐름"] = tab("sgP", [-9, -0.02, 0.0, 0.02, 0.04, 9], ["-2%↓", "-2~0%", "0~+2%", "+2~+4%", "+4%↑"])
    # 상관(스피어만)
    cor = {}
    for col in ("cxP", "cxV", "dgP", "sgP"):
        S = O[[col, "res"]].dropna()
        if len(S) > 100: cor[col] = {"n": int(len(S)), "잔차와 상관": round(float(S[col].corr(S["res"], method="spearman")), 3)}
        S2 = O[[col, "bidders"]].dropna()
        if len(S2) > 100: cor.setdefault(col, {})["응찰자수와 상관"] = round(float(S2[col].corr(S2["bidders"].astype(float), method="spearman")), 3)
    res["상관"] = cor
    # 가격·거래량이 함께 오르는 단지(수익성이 보이는 단지) vs 나머지
    S = O[O["cxP"].notna() & O["cxV"].notna()]
    up = S[(S["cxP"] >= 0.03) & (S["cxV"] >= 0.1)]; rest = S[~S.index.isin(up.index)]
    def sm(G): bd = G["bidders"].dropna(); return {"n": int(len(G)), "모델잔차 중앙%": round(float(np.expm1(G["res"].median())) * 100, 1), "응찰자 중앙": float(bd.median()), "응찰자 9명+%": round(float((bd >= 9).mean()) * 100, 1), "낙찰/시세 중앙": round(float(G["ratio"].median()), 3)}
    if len(up) >= 30: res["가격↑(+3%↑)·거래량↑(+10%↑) 단지"] = sm(up); res["나머지"] = sm(rest)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    json.dump(res, open("flow-vs-winbid.json", "w"), ensure_ascii=False)
    O.to_json("flow-vs-winbid-rows.json", orient="records", force_ascii=False)


if __name__ == "__main__":
    main()
