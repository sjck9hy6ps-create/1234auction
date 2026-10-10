"""
🏢 층별 가격 차이 실측 (2026-10-10, 사용자: "저층 보정에서 1층은 별개로 봐야 - 1층은 금액 차이가 상당히 크다")
같은 단지·같은 평형(5㎡ 구간)·같은 분기에서 중층(4층~꼭대기 아래) 거래 중앙값 대비 1층·2층·3층 거래 가격을 비교(단지 최고층 구간별, 수도권/지방 따로).
결과: 1층·2층·3층 각각의 중앙값 비율·건수 → 앱의 저층 보정 기본값과 비교
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("avm", os.path.join(HERE, "train-avm.py"))
avm = importlib.util.module_from_spec(_s); _s.loader.exec_module(avm)


def main():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,size,floor,price,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20250101")
    print(f"받은 아파트 거래 {len(raw):,}건")
    df = raw.copy()
    df = df[df["cdeal_type"].fillna("").astype(str).str.strip() == ""]
    df = df[df["dealing_type"].fillna("") != "직거래"]
    for c in ("size", "floor", "price", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["size", "floor", "price", "deal_date"])
    df = df[(df["price"] > 0) & (df["size"] >= 20) & (df["size"] <= 200) & (df["floor"] >= 1)]
    df["metro"] = df["region"].astype(str).str.match(r"^(서울|경기|인천)")
    df["q"] = (df["deal_date"] // 10000) * 4 + ((df["deal_date"] // 100 % 100) - 1) // 3
    df["unit"] = df["region"].astype(str) + "|" + df["dong"].astype(str) + "|" + df["danji"].astype(str) + "|" + (df["size"] / 5).round().astype(int).astype(str)
    df["cx"] = df["region"].astype(str) + "|" + df["dong"].astype(str) + "|" + df["danji"].astype(str)
    df["maxF"] = df.groupby("cx")["floor"].transform("max")
    df = df[df["maxF"] >= 4]
    df["lp"] = np.log(df["price"])
    # 같은 단지·평형·분기의 중층(4층 ~ 꼭대기 아래) 거래 중앙값
    mid = df[(df["floor"] >= 4) & (df["floor"] < df["maxF"])]
    g = mid.groupby(["unit", "q"])["lp"].agg(["median", "size"]).rename(columns={"median": "ref", "size": "nref"}).reset_index()
    D = df.merge(g, on=["unit", "q"], how="inner")
    D = D[D["nref"] >= 3]
    D["dev"] = D["lp"] - D["ref"]
    D["h"] = pd.cut(D["maxF"], [0, 5, 10, 15, 20, 100], labels=["5층 이하", "6~10층", "11~15층", "16~20층", "21층+"])
    D["fl"] = D["floor"].clip(upper=4).astype(int)
    out = {}
    def tab(S):
        r = S.groupby(["h", "fl"])["dev"].agg(["size", "median"]).reset_index()
        res = {}
        for row in r.itertuples():
            if row.fl > 3 or row.size < 150: continue
            res.setdefault(str(row.h), {})[f"{row.fl}층"] = {"n": int(row.size), "pct": round((float(np.exp(row.median)) - 1) * 100, 1)}
        return res
    out["수도권"] = tab(D[D["metro"]]); out["지방"] = tab(D[~D["metro"]]); out["전체"] = tab(D)
    # 1층 평균 외에 분포(하위 25%, 상위 25%)
    d1 = D[D["floor"] == 1]
    out["1층_분포"] = {k: {"n": int(len(G)), "p25": round((float(np.exp(G['dev'].quantile(.25))) - 1) * 100, 1), "p50": round((float(np.exp(G['dev'].median())) - 1) * 100, 1), "p75": round((float(np.exp(G['dev'].quantile(.75))) - 1) * 100, 1)} for k, G in d1.groupby("h") if len(G) >= 150}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("floor-premium.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
