"""백업(NDJSON.gz)을 Supabase에 다시 넣기 (docs/RESTORE.md 참고). 표는 미리 만들어 둬야 해요. 사용: python3 scripts/restore-from-backup.py <백업폴더> [표이름...]
⚠️ 아직 실제 복구로 시험해 보지 않은 도구예요(2026-10-10 작성) - 처음엔 작은 표 하나로 먼저 확인하세요."""
import os, sys, json, gzip, glob, requests, time
URL = os.environ["SUPABASE_URL"].rstrip("/"); KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
folder = sys.argv[1]; only = set(sys.argv[2:])
for path in sorted(glob.glob(os.path.join(folder, "*.ndjson.gz"))):
    t = os.path.basename(path).replace(".ndjson.gz", "")
    if only and t not in only: continue
    n = 0; batch = []
    def flush():
        global batch, n
        if not batch: return
        for a in range(5):
            r = requests.post(f"{URL}/rest/v1/{t}", headers=H, data=json.dumps(batch), timeout=120)
            if r.status_code < 300: break
            print("재시도", t, r.status_code, r.text[:150]); time.sleep(3 * (a + 1))
        else: raise SystemExit(f"{t} 넣기 실패")
        n += len(batch); batch = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            batch.append(json.loads(line))
            if len(batch) >= 1000:
                flush()
                if n % 50000 == 0: print(f"{t}: {n:,}행", flush=True)
    flush(); print(f"✅ {t}: {n:,}행")
