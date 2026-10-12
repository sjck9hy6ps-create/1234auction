# 데이터 복구 방법

백업 파일은 `scripts/backup-full.py`가 만든 **NDJSON.gz**(한 줄에 한 행의 JSON, gzip 압축)와 `schema.json`(컬럼·타입), `manifest.json`(행 수·크기)이에요. 사용자 PC의 `backups/full-날짜/` 폴더에 있어요.

## 1. 새 Supabase 프로젝트 만들기
1. supabase.com에서 새 프로젝트 생성(서울 리전 권장).
2. `schema.json`을 보고 표를 만들어요(`docs/schema-from-backup.sql`은 참고용 초안이에요 - 기본키·인덱스는 PostgREST 정보에 없어 사람이 확인해야 해요). 기본키는 대부분 `id`, 실거래·전월세는 `(region,dong,danji,size,floor,deal_date)` 유일 키(코드의 `onConflict` 참고: `scripts/shared*.mjs`).
3. 자주 쓰는 인덱스: 실거래 표의 `region`, `deal_date`; `building_info`의 `(sigungu_cd,bjdong_cd,bun,ji,bld_nm)`; `complex_coords.cache_key`.

## 2. 데이터 넣기
```bash
export SUPABASE_URL=https://새프로젝트.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=...        # 새 프로젝트의 service_role 키
python3 scripts/restore-from-backup.py backups/full-날짜 house_trades villa_trades   # 표 이름 생략하면 전부
```
- 1,000행씩 upsert해요. 중간에 멈추면 다시 실행해도 돼요(같은 키는 덮어씀).

## 3. 앱 연결
- Vercel 환경변수 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`를 새 값으로 바꾸고 재배포.
- GitHub 비밀값도 같은 이름으로 갱신. 그다음 `precompute-board`, `analyze-bidcases`를 수동 실행하면 계산 결과가 다시 만들어져요.

## 4. 백업에 없는 것
- 비밀값(키) - 각 서비스에서 다시 발급.
- Vercel/GitHub 설정은 저장소(`vercel.json`, `.github/workflows`)에 있어요.
- ⚠️ **앱에 직접 올린 자료는 Supabase가 아니라 Upstash Redis에 있어요** - 경매물건(`auctions`, 즐겨찾기·인수금액·권리분석 포함), 낙찰사례(`bidCases`), 임장메모(`siteNotes`), 내 자산(`myAssets`). 이건 다시 채워지지 않으니 따로 백업해야 해요: `sh scripts/backup-app-data.sh`(키 필요 없음). 복구: `python3 scripts/restore-app-data.py 백업폴더`.
- 그 밖의 Redis 내용은 일부 응답 캐시라 다시 채워져요.
- Supabase 표 `building_info_cache`, `dong_boundaries`는 서비스 키로 읽을 권한이 없어 백업에서 빠졌어요(2026-10-11 확인, 필요하면 Supabase에서 권한을 열어야 함).

## 5. 백업을 한 곳에 모으는 방법 (2026-10-12)

백업은 두 종류라 따로 받아야 하지만, **PC의 `backups/` 한 폴더**에 날짜별로 모아 두면 됩니다.

| 종류 | 받는 방법 | 폴더 |
|---|---|---|
| Supabase 거래·분석 자료 | Actions "전체 백업" 실행 → `gh run download <번호> -D backups/full-YYYYMMDD` | `backups/full-YYYYMMDD/part-*` |
| 앱 자료(경매물건·낙찰사례·메모·내 자산, Redis) | `sh scripts/backup-app-data.sh backups/full-YYYYMMDD/part-app-data` | 위 폴더 안 `part-app-data` |

- 권장 주기: 한 달에 한 번(또는 큰 규칙 변경 전). GitHub 산출물은 7일 뒤 자동 삭제되므로 받은 뒤엔 PC 백업만 남음 — 산출물을 직접 지우지 않아도 됨.
- **받은 직후 복구 가능 검사**: `python scripts/verify-backup.py backups/full-YYYYMMDD` (모든 파일이 끝까지 읽히고 건수가 manifest와 맞는지 확인. 큰 폴더는 `--sample`로 빠르게).
- 복구 연습: 위 1~3단계를 새 무료 Supabase 프로젝트에 한 번 해 보면 실제 절차를 검증할 수 있음(분기 1회 권장).
