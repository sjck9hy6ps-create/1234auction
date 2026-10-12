"""거래내역 ↔ 건축물대장 연결표 내보내기·점검(2026-10-12, 사용자: "거래내역과 건축물대장의 매치가 내 백업 자료의 가장 핵심").
연결은 두 표로 이어짐: ① complex_coords(거래의 건물 키 'dong|단지명|번지|도로명|주번|부번' → 시군구코드·법정동코드·좌표)
② building_info(시군구코드·법정동코드·본번·부번 → 대장 JSON). 이 스크립트는 백업 폴더만 읽어(서버·키 필요 없음) 연결표를 한 파일로 풀어 쓰고 연결률을 계산함.
사용: python scripts/export-building-link.py <백업 폴더(예: backups/full-20261011)>
결과: <백업 폴더>/links/trade_building_link.ndjson.gz (건물 키, 거래 수, 시군구·법정동코드, 본번·부번, 대장 유무) + links/coverage.json + 못 이은 건물 상위 목록(거래 많은 순)"""
import sys, os, gzip, json, glob, collections
root = sys.argv[1] if len(sys.argv) > 1 else "."
def trade_keys(pattern):
    c = collections.Counter()
    for f in sorted(glob.glob(os.path.join(root, pattern))):
        for l in gzip.open(f, "rt", encoding="utf-8"):
            r = json.loads(l)
            # warmup-locations.mjs buildCacheKey와 같은 규칙: 주번은 없으면 0, 부번은 없으면 빈 칸
            k = "|".join(str(x) for x in [r.get("dong") or "", r.get("danji") or "", r.get("bunji") or "", r.get("road_name") or "", r.get("main_num") or 0, r.get("sub_num") or ""]).lower()
            lk = "|".join(str(x if x is not None else "") for x in [r.get("dong"), r.get("danji"), r.get("bunji"), r.get("road_name"), r.get("main_num"), r.get("sub_num")]).lower()  # 예전 형식(없으면 빈 칸) - complex_coords에는 두 형식이 섞여 있음
            c[(k, lk, r.get("region") or "")] += 1
    return c
H = trade_keys("part-house_trades/*.ndjson.gz"); V = trade_keys("part-villa_trades/*.ndjson.gz")
oth = glob.glob(os.path.join(root, "part-others*"))[0]
cc = {}
for l in gzip.open(os.path.join(oth, "complex_coords.ndjson.gz"), "rt", encoding="utf-8"):
    r = json.loads(l); cc[r["cache_key"].lower()] = (r.get("sigungu_cd"), r.get("bjdong_cd"), r.get("lat"), r.get("lon"))
bi = {}
for l in gzip.open(os.path.join(oth, "building_info.ndjson.gz"), "rt", encoding="utf-8"):
    r = json.loads(l); bi[(r["sigungu_cd"], r["bjdong_cd"], r["bun"], r["ji"])] = (r["id"], bool(r.get("title_json")))
out_dir = os.path.join(root, "links"); os.makedirs(out_dir, exist_ok=True)
cov, miss = {}, []
with gzip.open(os.path.join(out_dir, "trade_building_link.ndjson.gz"), "wt", encoding="utf-8") as fo:
    for kind, C in (("apt", H), ("villa", V)):
        tot = sum(C.values()); n = len(C); m = b = 0; mt = bt = 0
        for (k, lk, region), cnt in C.items():
            s = cc.get(k) or cc.get(lk); bid = None; has = False; bun = ji = ""
            if s:
                p = k.split("|")[2].split("-")
                try: bun = p[0].zfill(4); ji = (p[1] if len(p) > 1 else "0").zfill(4)
                except Exception: pass
                hit = bi.get((s[0], s[1], bun, ji))
                if hit: bid, has = hit[0], hit[1]
            fo.write(json.dumps({"kind": kind, "key": k, "region": region, "trades": cnt, "sigungu_cd": s[0] if s else None, "bjdong_cd": s[1] if s else None, "bun": bun, "ji": ji, "building_info_id": bid, "has_title": has}, ensure_ascii=False) + "\n")
            if s: m += 1; mt += cnt
            if bid is not None and has: b += 1; bt += cnt
            else: miss.append((cnt, kind, "좌표·법정동 없음" if not s else "대장 없음", k, region))
        cov[kind] = {"buildings": n, "trades": tot, "linkedCoords": m, "linkedCoordsPct": round(m / n * 100, 1), "tradesLinkedCoordsPct": round(mt / tot * 100, 1), "withTitle": b, "withTitlePct": round(b / n * 100, 1), "tradesWithTitlePct": round(bt / tot * 100, 1)}
json.dump(cov, open(os.path.join(out_dir, "coverage.json"), "w"), ensure_ascii=False, indent=1)
miss.sort(reverse=True)
with open(os.path.join(out_dir, "unlinked_top.tsv"), "w", encoding="utf-8") as f:
    f.write("거래수\t종류\t사유\t키\t지역\n")
    for cnt, kind, why, k, region in miss[:5000]: f.write(f"{cnt}\t{kind}\t{why}\t{k}\t{region}\n")
print(json.dumps(cov, ensure_ascii=False, indent=1)); print("못 이은 건물 상위는", os.path.join(out_dir, "unlinked_top.tsv"))
