"""
🗄️ Supabase 전체 백업 (2026-10-10, 사용자: 예비 차원의 전체 백업을 내 PC에)
- 모든 테이블을 PostgREST(OpenAPI 목록)로 찾아 키셋(id) 방식으로 끊어 읽어 NDJSON.gz 파일로 저장 + schema.json(컬럼·타입) + manifest.json(행 수·크기)
- 사용: TABLES=house_trades 또는 TABLES=others(큰 표 제외 전부) 또는 TABLES=all, OUT=폴더
- GitHub Actions(backup-full.yml)가 실행해 산출물(artifact)로 올리고, 사용자가 PC로 내려받음(gh run download). 복구 방법은 docs/RESTORE.md
"""
import os, sys, json, gzip, time, requests

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY}
OUT = os.environ.get("OUT", "backup")
BIG = ["house_trades", "villa_trades"]
want = os.environ.get("TABLES", "all")


def get(url, params=None, headers=None, tries=6):
    for a in range(tries):
        try:
            r = requests.get(url, params=params, headers={**H, **(headers or {})}, timeout=120)
            if r.status_code in (200, 206):
                return r
            err = r.text[:200]
        except Exception as e:
            err = str(e)[:200]
        time.sleep(2 * (a + 1))
    raise RuntimeError(f"요청 실패: {url} {params} {err}")


def count_rows(t):
    try:
        r = get(f"{URL}/rest/v1/{t}", params={"select": "*"}, headers={"Prefer": "count=exact", "Range": "0-0"})
        cr = r.headers.get("Content-Range", "*/0")
        return int(cr.split("/")[-1]) if cr.split("/")[-1].isdigit() else None
    except Exception:
        return None


def dump(t, props):
    path = os.path.join(OUT, f"{t}.ndjson.gz")
    n = 0; last = None; lim = 1000; has_id = "id" in props
    t0 = time.time()
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as f:
        off = 0
        while True:
            params = {"select": "*", "limit": lim}
            if has_id:
                params["order"] = "id.asc"
                if last is not None:
                    params["id"] = f"gt.{last}"
            else:
                params["offset"] = off
            try:
                rows = get(f"{URL}/rest/v1/{t}", params=params).json()
            except RuntimeError as e:
                if lim > 100:
                    lim = max(100, lim // 2); print(f"  {t} 읽기 느림 → 한 번에 {lim}행으로 줄임", flush=True); continue
                raise
            if not rows: break
            for row in rows: f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += len(rows); off += len(rows)
            if has_id: last = rows[-1]["id"]
            if n % 100000 < lim: print(f"  {t}: {n:,}행 ({int(time.time() - t0)}초)", flush=True)
            if len(rows) < lim and not has_id: break
    return n, os.path.getsize(path)


def main():
    os.makedirs(OUT, exist_ok=True)
    spec = get(URL + "/rest/v1/").json()
    defs = spec.get("definitions", {})
    schema = {t: {"columns": {c: {k: v for k, v in p.items() if k in ("type", "format", "description")} for c, p in d.get("properties", {}).items()}, "required": d.get("required", [])} for t, d in defs.items()}
    json.dump(schema, open(os.path.join(OUT, "schema.json"), "w"), ensure_ascii=False, indent=1)
    tables = sorted(defs)
    print(f"테이블 {len(tables)}개: {', '.join(tables)}", flush=True)
    sel = tables if want == "all" else ([t for t in tables if t not in BIG] if want == "others" else [t for t in want.split(",") if t in defs])
    man = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "supabase": URL.split("//")[-1].split(".")[0], "tables": {}}
    for t in sel:
        total = count_rows(t)
        print(f"▶ {t} (서버 행 수 {total if total is not None else '?'})", flush=True)
        n, sz = dump(t, defs[t].get("properties", {}))
        man["tables"][t] = {"rows": n, "serverRows": total, "bytes": sz}
        print(f"  ✅ {t}: {n:,}행 · {sz / 1e6:.1f}MB", flush=True)
    json.dump(man, open(os.path.join(OUT, "manifest.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
