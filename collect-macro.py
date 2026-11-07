"""
📊 금리·시장 흐름 자료 수집 (2026-11-07, 사용자: 금리·정책에 즉각 대응해 후발주자 중 앞서기)
공개 통계만 사용: 한국은행 ECOS(기준금리·주택담보대출 금리·CD·국고채) + 한국부동산원 R-ONE 주간(매매·전세 가격지수, 매매·전세 수급동향=매수우위).
서버(api/data-coverage.js의 ecosRaw·roneRaw 통로)를 거쳐 읽으므로 키는 필요 없음. 결과는 signal|__macro__에 저장하고 macro.json으로도 남김.
금리 변경일은 ECOS 기준금리 일별 값에서 자동으로 뽑음(사건 목록). 정책 발표는 근거를 붙여 data/policy-events.json에 직접 적은 것만 합침.
"""
import os, sys, json, time, importlib.util
from datetime import datetime, timezone
import requests
HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
RONE = {"saleIdx": "T244183132827305", "jeonseIdx": "T247713133046872", "saleDemand": "T248163133074619", "jeonseDemand": "T245423133086632"}
FROM_WEEK = "202001"


def get(params, tries=4):
    for k in range(tries):
        try:
            r = requests.get(f"{SITE}/api/data-coverage", params=params, timeout=90)
            return r.json()
        except Exception as e:
            time.sleep(2 * (k + 1))
    return {}


def rone_all(statbl):
    out, page, total = {}, 1, None
    while True:
        d = get({"mode": "roneRaw", "statbl": statbl, "cycle": "WK", "size": 1000, "page": page})
        blk = (d.get("SttsApiTblData") or [None, None])
        head = blk[0]["head"][0] if blk[0] else {}
        rows = (blk[1] or {}).get("row") if len(blk) > 1 and blk[1] else None
        if total is None: total = head.get("list_total_count")
        if not rows: break
        for r in rows:
            w = str(r.get("WRTTIME_IDTFR_ID"))
            if w < FROM_WEEK: continue
            name = r.get("CLS_FULLNM") or r.get("CLS_NM")
            if not name or r.get("DTA_VAL") is None: continue
            out.setdefault(name, {})[w] = (round(float(r["DTA_VAL"]), 3), r.get("WRTTIME_DESC"))
        if total is None or page * 1000 >= total: break
        page += 1
    return out, total


def ecos(stat, cycle, frm, to, item):
    d = get({"mode": "ecosRaw", "stat": stat, "cycle": cycle, "from": frm, "to": to, "item": item, "count": 20000})
    rows = (d.get("StatisticSearch") or {}).get("row") or []
    return [(r["TIME"], float(r["DATA_VALUE"])) for r in rows if r.get("DATA_VALUE") not in (None, "")]


def main():
    now = datetime.now(timezone.utc)
    macro = {"generatedAt": now.isoformat(), "rone": {}, "ecos": {}}
    for k, sid in RONE.items():
        data, total = rone_all(sid)
        weeks = sorted({w for v in data.values() for w in v})
        desc = {}
        for v in data.values():
            for w, (_, d) in v.items(): desc[w] = d
        macro["rone"][k] = {"weeks": weeks, "dates": [desc.get(w) for w in weeks], "reg": {n: [v[w][0] if w in v else None for w in weeks] for n, v in data.items()}}
        print(k, "행", total, "지역", len(data), "최근", weeks[-1] if weeks else None)
    ym = now.strftime("%Y%m"); ymd = now.strftime("%Y%m%d")
    base_d = ecos("722Y001", "D", "20190101", ymd, "0101000")
    mort = ecos("121Y006", "M", "201901", ym, "BECBLA0302")
    cd91 = ecos("817Y002", "D", "20190101", ymd, "010502000")
    ktb3 = ecos("817Y002", "D", "20190101", ymd, "010200000")
    macro["ecos"] = {"baseRateD": base_d, "mortgageM": mort, "cd91D": cd91, "ktb3D": ktb3}
    print("기준금리 일별", len(base_d), "주담대 월별", len(mort), "CD", len(cd91), "국고3", len(ktb3), "최근 기준금리", base_d[-1] if base_d else None, "주담대", mort[-1] if mort else None)
    ev, prev = [], None
    for t, v in base_d:
        if prev is not None and abs(v - prev) > 1e-9: ev.append({"date": f"{t[:4]}-{t[4:6]}-{t[6:]}", "type": "기준금리", "title": f"기준금리 {prev:.2f}% → {v:.2f}%", "delta": round(v - prev, 2), "source": "한국은행 ECOS"})
        prev = v
    try:
        extra = json.load(open(os.path.join(HERE, "data", "policy-events.json"), encoding="utf-8"))
        ev += [e for e in extra if e.get("date") and e.get("title") and e.get("source")]
    except Exception as e:
        print("정책 사건 목록 없음:", e)
    macro["events"] = sorted(ev, key=lambda e: e["date"])
    json.dump(macro, open("macro.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("macro.json", os.path.getsize("macro.json") // 1024, "KB, 사건", len(ev))
    if os.environ.get("SUPABASE_URL"):
        s = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py")); cyc = importlib.util.module_from_spec(s); s.loader.exec_module(cyc)
        cyc.upsert_rows([{"id": "signal|__macro__", "payload": cyc.clean_json(macro), "fetched_at": macro["generatedAt"]}]); print("서버 저장: macro")


if __name__ == "__main__":
    main()
