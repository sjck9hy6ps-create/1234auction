"""백업 폴더 검증(2026-10-12) - 복구가 실제로 가능한지 확인: 각 .ndjson.gz가 끝까지 읽히는지, 줄마다 JSON인지, manifest.json의 건수와 맞는지.
사용: python scripts/verify-backup.py <백업 폴더(예: backups/full-20261011)>   (전체를 읽어 큰 파일은 몇 분 걸림, --sample 이면 앞 2만 줄만)"""
import sys, os, gzip, json, glob
root = sys.argv[1] if len(sys.argv) > 1 else "."
sample = "--sample" in sys.argv
bad = 0
for man in sorted(glob.glob(os.path.join(root, "**", "manifest.json"), recursive=True)):
    d = os.path.dirname(man)
    try: mf = json.load(open(man))
    except Exception as e: print("❌ manifest 읽기 실패", man, e); bad += 1; continue
    counts = (mf.get("counts") or mf.get("tables") or {}) if isinstance(mf, dict) else {}
    for f in sorted(glob.glob(os.path.join(d, "*.ndjson.gz"))):
        name = os.path.basename(f).replace(".ndjson.gz", "")
        n = 0; ok = True
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    json.loads(line); n += 1
                    if sample and n >= 20000: break
        except Exception as e:
            ok = False; print("❌", f, "읽기 실패:", str(e)[:80]); bad += 1
        exp = counts.get(name); exp = exp.get("rows") if isinstance(exp, dict) else exp
        note = "" if sample or exp is None else (" ✔ 건수 일치" if exp == n else f" ⚠️ manifest {exp} ≠ 읽은 {n}")
        if ok and not sample and exp is not None and exp != n: bad += 1
        if ok: print("✅", name, n, "줄" + note)
print("\n문제 있음" if bad else "\n모두 정상", f"({bad}건)")
sys.exit(1 if bad else 0)
