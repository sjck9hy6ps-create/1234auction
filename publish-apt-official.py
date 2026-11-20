"""아파트 공시가격 → 앱용 자료(2026-11-19): apt-official-price.jsonl(건물별 면적별 요약)을 leader_follower_cache 'apt-official|N' 묶음으로 올림.
항목 키 = 시군구5|본번4|부번4, 값 = [[단지이름, [[전용㎡, 호수, 중앙값(만원)], …]], …](같은 번지에 법정동이 다른 단지가 있으면 여러 개). 앱(공시가격 필터·세금 계산)이 api/data-coverage?mode=aptOfficial로 받음."""
import os, sys, json, time, re, importlib.util, requests
SU = os.environ["SUPABASE_URL"].strip().rstrip("/"); SK = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
H = {"apikey": SK, "Authorization": "Bearer " + SK, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
SRC = os.environ.get("SRC", "apt-official-price.jsonl")
items = {}; n = 0; yr = {}
for ln in open(SRC, encoding="utf-8"):
    r = json.loads(ln)
    if not r.get("n") or not r.get("areas"): continue
    pnu = r["pnu"]; key = pnu[:5] + "|" + pnu[11:15] + "|" + pnu[15:19]
    ar = [[float(a), v[0], int(round(v[1] / 10000))] for a, v in r["areas"].items() if v[1] > 0]
    if not ar: continue
    items.setdefault(key, []).append([r.get("danji", ""), ar]); n += 1; yr[r.get("year")] = yr.get(r.get("year"), 0) + 1
# ---- 호별 공시가격(경매 물건 id → 만원) - 지분경매처럼 앱의 평형이 건물 전체와 다른 물건도 동·호로 찾음(2026-11-20, 사용자 지적: 건물에 대한 공시가격이라 평형으로 찾으면 안 됨)
LETTER = {"에이": "A", "비": "B", "씨": "C", "디": "D"}
def build_units():
    HERE = os.path.dirname(os.path.abspath(__file__))
    sp = importlib.util.spec_from_file_location("collector", os.path.join(HERE, "collect-apt-official-price.py")); C = importlib.util.module_from_spec(sp); sp.loader.exec_module(C)
    src = open(os.path.join(HERE, "api", "get-official-price.js"), encoding="utf-8").read()
    leg = json.loads(re.search(r"const LEGACY_SIGUNGU_PREFIX = (\{.*?\});", src).group(1))
    recs = {}
    for ln in open(SRC, encoding="utf-8"):
        r = json.loads(ln); recs[r["pnu"]] = r
    vrecs = {}   # 빌라 호별 공시가격(collect-villa-official-price.py가 모은 보관소 파일) → pnu: 호 목록(가장 최근 연도)
    vyear = {}
    if os.path.exists("official-price.jsonl"):
        for ln in open("official-price.jsonl", encoding="utf-8"):
            try: r = json.loads(ln)
            except Exception: continue
            if r.get("units") and r.get("year", 0) >= vyear.get(r["pnu"], 0): vrecs[r["pnu"]] = r["units"]; vyear[r["pnu"]] = r["year"]
        print(f"빌라 공시가격 보관 건물 {len(vrecs):,}곳", flush=True)
    have = lambda pnu: (recs.get(pnu) or {}).get("units") or vrecs.get(pnu)
    site = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
    auc = requests.get(site + "/api/auction", timeout=180).json()
    dg = lambda x: re.sub(r"\D", "", str(x or ""))
    try: csvdong = json.load(open(os.path.join(HERE, "data", "csv-dong.json"), encoding="utf-8"))
    except Exception: csvdong = {}
    ainfo = {}; detail = []
    jobinfo = {}   # pnu → [(단지명, 법정동명, 번지)]
    jobs = []   # (경매 id, pnu, 동, 호)
    for a in auc:
        if a.get("propType") not in ("apt", "아파트", "villa") or not a.get("bCode") or not a.get("bunji") or not a.get("unitNo"): continue
        bb = C.bunji_to_bunji(a.get("bunji")); ho = dg(a.get("unitNo"))
        if not bb or not ho: continue
        dm = re.findall(r"(\d+)\s*동(?![가-힣])", str(a.get("aptDong") or "") + " " + str(a.get("addr") or "")); dong = dm[-1] if dm else ""
        if not dong:   # 글자 동('다동'·'제가동'·'에이동')
            lm = re.findall(r"(?:^|[\s,(])제?([가나다라마바사아자차카타파하]|에이|비|씨|디|A|B|C|D)\s*동(?![가-힣])", str(a.get("aptDong") or "") + " " + re.sub(r"^.*?\d[\d-]*", "", str(a.get("addr") or ""), 1))
            dong = LETTER.get(lm[-1], lm[-1]) if lm else ""
        if not dong:   # 저장된 사건에 동이 없으면: 새로 올린 CSV에서 저장한 csvDong → 과거 CSV에서 모은 표(data/csv-dong.json, 사건번호로 찾음)
            cn = re.sub(r"\s", "", str(a.get("caseNo") or "")); mm = re.search(r"(\d{4})\D*(\d+)$", cn)
            dong = dg(a.get("csvDong")) or (csvdong.get(cn) or (csvdong.get(mm.group(1) + "-" + mm.group(2)) if mm else "") or "")
        land = "2" if re.search(r"(?:동|리|가)\s*산\s*\d", str(a.get("addr") or "")) or str(a.get("bunji") or "").strip().startswith("산") else "1"   # '산 54-4'는 산 번지(PNU 11번째 자리 2)
        jobs.append((a["id"], str(a["bCode"]) + land + bb[0] + bb[1], dong, ho))
        ainfo[a["id"]] = {"addr": a.get("addr"), "name": a.get("name"), "case": a.get("caseNo"), "floor": a.get("floor"), "unit": a.get("unitNo"), "buildYear": a.get("buildYear"), "bunji": a.get("bunji")}
        jobinfo.setdefault(jobs[-1][1], []).append((str(a.get("name") or "") or re.sub(r"\s*(제?\d+\s*동|[가-힣]동\s|[가-힣]동$|제?\d+층.*|\d+호.*|외\s*\d.*)", "", re.sub(r"^.*?\d[\d-]*\s*", "", str(a.get("addr") or ""), 1)).strip(), str(a.get("dong") or ""), str(a.get("bunji") or "")))
    # 호 목록이 없는 건물(요약만 있거나 아직 안 받은 건물)은 지금 받아 옴: 쓴 적 있는 실제 조회 PNU(via) → 새 PNU → 옛 시군구 코드 순
    need = sorted({j[1] for j in jobs if not have(j[1])})
    print(f"경매 아파트·빌라 {len(jobs):,}건 · 호 목록을 새로 받을 건물 {len(need):,}곳", flush=True)
    from concurrent.futures import ThreadPoolExecutor
    def get(pnu):
        cands = [(recs.get(pnu) or {}).get("via"), pnu, (leg.get(pnu[:5], "") + pnu[5:]) if pnu[:5] in leg else None]
        for cp in [c for c in cands if c]:
            _, res, ok = C.fetch_pnu((cp, True))
            if ok and res and res[1]: return pnu, [list(u) for u in res[1]]
        return pnu, None
    got = {}
    with ThreadPoolExecutor(max_workers=int(os.environ.get("THREADS", "8"))) as ex:
        for pnu, u in ex.map(get, need):
            if u: got[pnu] = u
    # 2차(1차에서 못 받은 건물): ① 한 번 더(통신 오류 대비, 천천히) ② 인천 신설구는 옛 시군구×법정동코드 탐색 ③ 같은 본번의 건물 목록(접두 PNU)에서 단지명·번지로 찾기
    def norm_nm(x): return re.sub(r"[\s·\-()]|아파트|맨션|빌라|주상복합|제?\d*동$", "", str(x or ""))
    def prefix_rows(pre):
        rows_all = []
        for pg in range(1, 61):
            f, total, ok = C.vget(pre, C.YEAR, pg)
            if not ok: return None
            rows_all += [x for x in f if str(x.get("stdrYear")) == str(C.YEAR)]
            if len(f) < C.ROWS: break
        return rows_all
    inc_new = ("28275", "28290", "28125", "28155"); inc_cache = {}
    def second(pnu):
        res, _ = get(pnu)[1], 0
        if res: return pnu, res
        sg, bjd, tail = pnu[:5], pnu[5:10], pnu[10:]
        nm, dn_, bn = (jobinfo.get(pnu) or [("", "", "")])[0]
        if sg in inc_new:
            for osg in ("28110", "28140", "28260", "28200"):
                for bj in range(10100, 15100, 100):
                    key = (osg, bj, dn_)
                    if inc_cache.get(key) is False: continue
                    if key not in inc_cache:
                        f, _, ok = C.vget(osg + str(bj) + tail[:5], C.YEAR, 1)   # 같은 번지로 시험 조회(법정동명으로 확인)
                        inc_cache[key] = bool(f and dn_ and (f[0].get("ldCodeNm") or "").endswith(dn_))
                    if inc_cache[key]:
                        _, r2, ok2 = C.fetch_pnu((osg + str(bj) + tail, True))
                        if ok2 and r2 and r2[1]: return pnu, [list(u) for u in r2[1]]
        for base in ([leg.get(pnu[:5], "") + pnu[5:]] if pnu[:5] in leg else []) + [pnu]:
            rows = prefix_rows(base[:15])
            if not rows: continue
            m = re.match(r"0*(\d+)-?0*(\d*)", bn.replace(" ", "")); lot = (m.group(1) + ("-" + m.group(2) if m.group(2) else "")) if m else ""
            byb = {}
            for x in rows: byb.setdefault((x.get("aphusCode"), x.get("aphusNm")), []).append(x)
            nn = norm_nm(nm)
            def nmok(k):
                kk = norm_nm(k[1])
                if nn and len(nn) >= 2 and kk and (nn in kk or (len(kk) >= 2 and kk in nn)): return True
                return bool(lot and ("(" + lot + ")") in str(k[1]))
            pick = [k for k in byb if nmok(k)]
            if not pick and nn and len(byb) == 1:   # 단지명이 조금 달라도(예: 3차우방타운↔우방1) 같은 본번에 건물이 하나뿐이고 앞 두 글자가 같으면 같은 건물로 봄(이후 동·호까지 맞아야 연결)
                k0 = list(byb)[0]; kk = norm_nm(k0[1]); nn2 = re.sub(r"^\d+차", "", nn)
                if len(kk) >= 2 and len(nn2) >= 2 and kk[:2] == nn2[:2]: pick = [k0]
            us2 = []
            for k in pick: us2 += [[x.get("dongNm"), x.get("floorNm"), x.get("hoNm"), x.get("prvuseAr"), x.get("pblntfPc")] for x in byb[k]]
            if us2: return pnu, us2
        return pnu, None
    todo2 = [x for x in need if x not in got]
    print(f"2차 조회 대상 {len(todo2):,}곳", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for pnu, u in ex.map(second, todo2):
            if u: got[pnu] = u
    print(f"2차로 새로 받은 건물 {sum(1 for x in todo2 if x in got):,}곳", flush=True)
    out = {}; rng = {}; miss = 0; why = {}
    def bad(k, extra=None):
        why[k] = why.get(k, 0) + 1; detail.append({"why": k, "id": aid, "pnu": pnu, "dong": dong, "ho": ho, **ainfo.get(aid, {}), **(extra or {})})
    for aid, pnu, dong, ho in jobs:
        us = have(pnu) or got.get(pnu)
        if not us: miss += 1; bad("건물 호 목록 못 받음"); continue
        # 호 표기: '102-1401'(동-호)·'0803'(앞 0)은 호만 떼어 비교, 동은 호 앞 숫자가 있으면 그것을 씀. 국토부 자료에 동이 하나뿐('제1'·'101' 등 건물 전체)이면 사건 동과 비교하지 않음
        def pr(u):   # (동, 호) 정리: '101동1001호'·'10층 1001호'·'1-1001호'·'101-1001'·'0803' 같은 표기를 호 숫자만으로, 동은 호 앞 숫자 또는 동 칸 첫 숫자로
            k = (id(u))
            s0 = str(u[2] or ""); d0 = None
            m = re.search(r"(\d+)\s*동(?![가-힣])", s0)
            if m: d0 = m.group(1)
            s0 = re.sub(r"\d+\s*(동|층|단지)", "", s0)
            if "-" in s0: a0, b0 = s0.rsplit("-", 1); d0 = d0 or dg(a0); s0 = b0
            m2 = re.match(r"\D*(\d+)", str(u[0] or ""))
            dl = ""
            if not d0 and not m2:   # 글자 동 ('가'·'가동'·'제가동'·'에이'·'A동')
                t3 = re.sub(r"동$", "", re.sub(r"^제\s*", "", str(u[0] or "").strip()))   # 'B동'·'제가동'·'가동' → 'B'·'가'
                m3 = re.match(r"^([가-힣A-Za-z]{1,2})$", t3)
                if m3: dl = LETTER.get(m3.group(1), m3.group(1)).upper()
            return (dg(s0).lstrip("0"), (d0 or (m2.group(1) if m2 else "") or dl or "").lstrip("0"))
        def dalt(u):   # '12(에이)'·'11(비)'처럼 숫자 뒤 괄호에 글자 동이 같이 적힌 경우
            m4 = re.search(r"\(\s*([가-힣A-Za-z]{1,2})\s*\)", str(u[0] or ""))
            return LETTER.get(m4.group(1), m4.group(1)).upper() if m4 else ""
        def hn(u): return pr(u)[0]
        def dn(u): return pr(u)[1]
        alld = {dn(u) for u in us}; one = len(alld) <= 1
        hol = ho.lstrip("0")
        cand = [u for u in us if hn(u) == hol and (not dong or one or dn(u) == dong.lstrip("0").upper() or dn(u) == dong.lstrip("0") or dalt(u) == dong.upper() or not dn(u))]
        if not cand: miss += 1; bad("그 호가 목록에 없음", {"n_units": len(us), "dongs": sorted({str(u[0]) for u in us})[:8], "ho_sample": sorted({str(u[2]) for u in us})[:10], "floors": sorted({str(u[1]) for u in us})[:12]}); continue
        try: pr = sorted(float(u[4]) for u in cand)
        except Exception: miss += 1; bad("가격 읽기 실패"); continue
        # 동을 모르는데 같은 호가 여러 동에 있으면: 가격이 서로 3% 이내로 같을 때만 중앙값을 씀(면적으로 찾지 않음)
        if len(cand) > 1 and not dong and pr[-1] > pr[0] * 1.03:
            miss += 1; bad("동을 몰라 여러 동 가격이 다름", {"dongs": [str(u[0]) for u in cand][:8]}); rng[str(aid)] = [int(round(pr[0] / 10000)), int(round(pr[-1] / 10000)), len(pr)]; continue
        out[str(aid)] = int(round(pr[len(pr) // 2] / 10000))
    json.dump(detail, open("unmatched.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("못 찾은 이유:", why, flush=True)
    print(f"호별 공시가격 {len(out):,}건 · 못 찾음 {miss:,}건", flush=True)
    build_units.ranges = rng
    return out
keys = sorted(items); CH = 5000; now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
print(f"건물 {n:,}곳 · 번지 키 {len(keys):,}개 · 기준연도 {yr}", flush=True)
rows = []
for i in range(0, len(keys), CH):
    rows.append({"id": f"apt-official|{i // CH}", "payload": {"items": {k: items[k] for k in keys[i:i + CH]}}, "fetched_at": now})
try:
    um = build_units(); rows.append({"id": "apt-official|units", "payload": {"items": um, "ranges": getattr(build_units, "ranges", {}), "at": now}, "fetched_at": now})
except Exception as e:
    print("호별 공시가격 만들기 실패(면적별 자료만 올림):", e, flush=True)
rows.append({"id": "apt-official|meta", "payload": {"at": now, "n": n, "keys": len(keys), "chunks": len(rows), "years": {str(k): v for k, v in yr.items()}}, "fetched_at": now})
for r in rows:
    body = json.dumps(r, ensure_ascii=False, allow_nan=False)
    for a in range(4):
        x = requests.post(f"{SU}/rest/v1/leader_follower_cache?on_conflict=id", headers=H, data=body.encode("utf-8"), timeout=120)
        if x.status_code < 300: break
        print("재시도", r["id"], x.status_code, x.text[:160], flush=True); time.sleep(3 * (a + 1))
    else: sys.exit(1)
    print(f"올림 {r['id']} {len(body)/1e3:.0f}KB", flush=True)
