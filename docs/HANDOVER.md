# 인수인계서 (HANDOVER) — 1년 뒤에 이어서 작업하기 위한 안내

> 작성 2026-10-10. 이 문서는 **키 값은 적지 않고 이름·위치만** 적었어요. 프로젝트 메모 37개는 `docs/memory/`에 그대로 있고, 아래 "메모 색인"이 그 목록이에요.

## 1. 이 앱은 무엇인가
개인 부동산 경매 투자 도구(한국어 UI). 사용자는 **부동산 매매사업자**이고, 경매로 낙찰받아 되팔아 수익을 내는 것이 목표예요.
- 지도(카카오맵)에 실거래·경매 배지를 띄우고, **입찰후보** 화면에서 물건별로 `예상매도가 → 필요 마진 → 입찰 상한 → 예상 낙찰가·낙찰 가능성 → 추천 입찰가 → 🚶 임장 후보/패스`를 판정해요.
- 대상: 전국 아파트 + 수도권(서울·인천·경기) 빌라. 매주 낙찰사례·경매 CSV를 올려 모델을 갱신해요.
- 판단 기준: 낙찰 확률이 아니라 **되판 뒤 실제 수익**, 그리고 시세 추정의 정확도·신뢰도(상세는 메모 `app-purpose-sale-price`, `goal-realized-profit-niche`, `first-deal-risk-priority`).

## 2. 구성(스택)
| 구성 | 위치 | 설명 |
|---|---|---|
| 화면 | `public/index.html` (약 2.7만 줄, 한 파일) | 순수 JS. 지도·입찰후보·내 자산·리포트·사이클·낙찰사례 등 전부 이 파일 |
| 서버 함수 | `api/*.js` (Vercel) | `get-house`(지역 실거래), `auction`(경매·낙찰사례 저장), `data-coverage`(분석 결과·미리 계산 조회), `get-building`(건축물대장), `search-complex`, `export-table` 등 |
| 데이터베이스 | Supabase (PostgreSQL) | 실거래 `house_trades` `villa_trades` `single_trades`, 전월세 `house_rent` `villa_rent` `single_rent`, `building_info`(건축물대장), `complex_coords`(좌표), `kapt_complex_info`, `presale_trades`, `leader_follower_cache`(분석 결과·미리 계산 저장소, id별 JSON) 등 |
| 자동 작업 | `.github/workflows/*.yml` + `scripts/*.mjs` + `*.py` | 수집·분석·백테스트·사전 계산. 아래 일정표 |
| 호스팅 | Vercel (`vercel.json`, 서울 리전, `data-coverage` 최대 60초) | 저장소 `main`에 푸시하면 자동 배포(약 1분) |
| 캐시 | Upstash Redis | 일부 응답 캐시. **이곳에 대량 저장 금지**(메모 `redis-limit-incident`) |
| 외부 API | 국토부 실거래(data.go.kr), 건축HUB 건축물대장, 카카오(지도·지오코딩·좌표→법정동), K-apt, 나이스(학군), 한국은행 ECOS, 청약홈 등 | 키는 GitHub 비밀값/Vercel 환경변수 |

## 3. 비밀값·환경변수 (이름만) — **전체 목록과 발급처는 [`docs/SECRETS.md`](SECRETS.md)**, 입력 양식은 `.env.example`
- **GitHub Actions 비밀값(Settings → Secrets):** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `PUBLIC_DATA_API_KEY`(국토부·건축HUB 공용), `KAKAO_REST_API_KEY`, `NEIS_API_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, `COLLECT_PROXY_SECRET`, `SITE_URL`
- **Vercel 환경변수:** 위와 같은 이름들 + `COLLECT_PROXY_SECRET`(Actions가 국토부 API를 Vercel 프록시로 부르게 하는 공유 비밀), 선택: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `ECOS_API_KEY`, `RONE_API_KEY`, `NAVER_CLIENT_ID/SECRET`, `VWORLD_API_KEY`
- 값 자체는 이 저장소에 없어요. 새로 만들 때: Supabase 대시보드(Project Settings → API), data.go.kr 마이페이지, 카카오 개발자 콘솔.
- data.go.kr 활용신청(승인 필요): 아파트 매매(Dev)·전월세, 연립다세대 매매·**전월세(RHRent)**, 단독다가구, 분양권전매, 건축HUB 4종(표제부·공시가·층별·전유공용). **건축HUB 하루 한도: 각 API 10,000건**(메모 `building-info-cache`).
- 공공데이터 API는 GitHub Actions에서 직접 막혀서 `api/get-house?action=molitProxy`(Vercel 경유)로 호출해요.

## 4. 자동 작업 일정(UTC cron, KST = +9시간)
| 파일 | 이름 | cron(UTC) |
|---|---|---|
| `analyze-bidcases.yml` | Analyze bid cases | 0 20 * * 0 |
| `analyze-cycle-forecast.yml` | Analyze cycle forecast | 수동 |
| `analyze-cycle.yml` | Analyze market cycle | 0 18 * * 1 |
| `analyze-downturn.yml` | 하락장 검증 분석 (읽기 전용, 수동) | 수동 |
| `analyze-floor-premium.yml` | 분석 - 층별 가격 차이(1층·2층·3층) | 수동 |
| `analyze-homestay.yml` | 공간대여(도시민박업) 밀집 지역 집계 | 0 21 * * 0 |
| `analyze-leader-criteria.yml` | Analyze leader criteria | 수동 |
| `analyze-liquidity.yml` | Analyze popular complexes | 0 20 * * 1 |
| `analyze-region-liquidity.yml` | 지방 시군구 팔리는 곳 후보 순위 | 30 22 * * 0 |
| `analyze-supply.yml` | 입주 예정 물량 검증·갱신 | 0 22 3 * * |
| `analyze-surge-signals.yml` | Analyze surge signals | 0 21 1 * * |
| `analyze-villa-bidcases.yml` | 분석 - 수도권 빌라 낙찰가 모델 | 수동 |
| `analyze-villa-factors.yml` | 분석 - 수도권 빌라 가격 요인(연식·평형·승강기) | 수동 |
| `backtest-comp-estimate.yml` | 예상매도가(30th percentile) 백테스트 (#481) | 30 20 1 * * |
| `backtest-leader-follower.yml` | 후발주자 신호 백테스트 (#480) | 0 20 1 * * |
| `backtest-villa-dedupe.yml` | 백테스트 - 빌라 중복 거래 정리 | 수동 |
| `backtest-villa-hedonic.yml` | 백테스트 - 빌라 건축물대장 보정 모델 | 수동 |
| `backtest-villa-jeonse.yml` | 백테스트 - 빌라 전세가 활용 | 수동 |
| `backtest-villa-liquidity.yml` | 백테스트 - 빌라 생활권 거래 활발도와 되팔림 | 수동 |
| `backtest-villa-radius.yml` | 백테스트 - 빌라 반경 방식 | 수동 |
| `backtest-villa.yml` | 백테스트 - 수도권 빌라 예상매도가 | 수동 |
| `backup-full.yml` | 전체 백업 (Supabase → 산출물) | 수동 |
| `cleanup-building-empty.yml` | Cleanup empty building cache (1회성) | 수동 |
| `collect-building-info.yml` | 입찰물건 건축물대장 수집 | 10 15 * * * |
| `collect-history-rent.yml` | 아파트 전월세 과거 데이터 수집 (수동) | 수동 |
| `collect-history-villa-range.yml` | 빌라·단독다가구 과거 전국 백필 (연도 여러 개 순서대로) | 수동 |
| `collect-history-villa-region.yml` | 지역 지정 연립다세대·단독다가구 백필 | 수동 |
| `collect-history-villa.yml` | 연간 빌라·단독다가구 데이터 수집 | 수동 |
| `collect-history.yml` | 아파트 매매 과거 데이터 수집 (수동 + 매월 자동) | 0 19 1 * * |
| `collect-presale.yml` | Collect presale trades | 30 2 * * 1 |
| `collect-villa-rent.yml` | 빌라 전월세 수집 (수도권) | 0 20 * * 2 |
| `collect-weekly-rent.yml` | 주간 아파트 전월세 데이터 수집 | 0 2 * * 1 |
| `collect-weekly-villa-single.yml` | 주간 연립다세대·단독다가구 데이터 수집 | 30 1 * * 1 |
| `data-health.yml` | 데이터 자동 점검 (거래 건수·지역코드) + 자동 복구 | 0 0 * * 2 |
| `diag-aptdong.yml` | 진단 - 실거래 동(aptDong) 채움 비율 | 수동 |
| `diag-building.yml` | Diag building info (진단용) | 수동 |
| `diag-coords.yml` | 진단 - 실거래 단지 좌표 매칭 점검 | 수동 |
| `diag-incheon-villa.yml` | 진단 - 인천 새 시군구 빌라 적재 | 수동 |
| `diag-kapt.yml` | Diag K-apt (진단용) | 수동 |
| `diag-resale-area.yml` | 진단 - 낙찰 후 매도 찾기(면적·층·동 불일치 원인) | 수동 |
| `diag-resale-placebo.yml` | 진단 - 확실 판정의 신뢰도(플라시보 검증) | 수동 |
| `diag-resale-tiers.yml` | 진단 - 낙찰 후 매도 판정 확실·유력·불확실 검증 | 수동 |
| `diag-storage.yml` | 진단 - 저장 용량(무료 한도 점검) | 수동 |
| `diag-villa-coverage.yml` | 진단 - 수도권 빌라 적재량 | 수동 |
| `final_test.yml` | 연간 부동산 데이터 수집 | 수동 |
| `match-bid-cases.yml` | 낙찰사례 매도사례 자동매칭 | 0 19 * * 4 |
| `oneoff-2023-recollect.yml` | 1회용 - 2023년 실거래 재수집 후 낙찰사례 재매칭 (2026-10-06 새벽) | 40 15 5 10 * |
| `precompute-board.yml` | 입찰후보 계산 미리 해 두기 | 30 20 * * *, 0 23 * * 0 |
| `sync-kapt.yml` | Sync K-apt complex info | 30 5 * * * |
| `sync-school.yml` | Sync school info (학군 근사치) | 30 6 * * * |
| `sync-transit.yml` | Sync transit (subway distance) | 0 6 * * * |
| `train-avm.yml` | Train AVM model | 0 4 * * 1 |
| `tune-sale-est.yml` | 조정 - 예상매도가 반영 비율 재조정 | 수동 |
| `warm-unsold.yml` | 미분양(청약홈 무순위·잔여세대) 캐시 주간 갱신 | 0 20 * * 0 |
| `warmup-house-cache.yml` | 지역별 거래 캐시 웜업(전체 재생성) | 수동 |
| `warmup-leader-follower.yml` | 대장/후발주자 인기순위 캐시 웜업 (전국, 서울 포함) | 0 19 * * * |
| `warmup-locations.yml` | 전체 지역 좌표·건축물대장 웜업 | 0 18 * * * |
| `weekly.yml` | 주간 부동산 데이터 수집 | 0 1 * * 1 |

- 핵심 흐름: 매주 월요일 새벽 실거래 수집 → 화요일 AVM 학습·사이클 분석 → 일요일 낙찰가 모델(`analyze-bidcases`, 약 65분) → 매일 `precompute-board`(KST 05:30)가 입찰후보 계산을 미리 만들어 `leader_follower_cache`(`board|cache|N`, `board|villa|N`)에 저장 → 앱이 열 때 받아 씀.
- `collect-building-info`(KST 00:10): 건축HUB 한도가 풀린 직후 입찰물건 건축물대장을 먼저 채워요. `warmup-locations`(KST 03:00)는 전국 백로그(상한 5,000건).

## 5. 핵심 파일 지도
- `public/index.html`: 입찰후보 `renderBidBoardLite`(아파트 목록/카드), `renderVillaLite`·`renderVillaDrawer`(빌라), `computeBidBoardRow`/`finalizeBidBoardRow`(아파트 판정), `computePick`·`bidPlanFor`(추천가), `villaSaleEst`·`villaMarginPlan`·`villaWinbid`·`villaBidPlan`·`villaEval`(빌라 계산), `renderAuctionMarkers`·`renderAuctionClusters`·`auctionBadgeWorthy`·`auctionBuildingKey`(지도 경매 배지), `openLinkWindow`·`naverLandUrl`(외부 링크), `favToggle`(즐겨찾기), `precompute` 연동 `srvBoardParts`·`villaFetchServerCalc`.
- `api/data-coverage.js`: 분석 결과 조회 모드 모음(`winbid`, `weeklyReport`, `homestay`, `boardCacheMeta/Chunk(&kind=villa)`, `competition`, `marketCycle` …).
- `scripts/precompute-board.mjs`: 가상 브라우저(playwright)로 앱을 열어 입찰후보·빌라 계산 결과를 서버에 올려요.
- `analyze-bidcases.py`: 아파트 낙찰가 모델(덧셈형 보정표) + 경쟁 예상 + 주간 리포트(추천가↔실제 낙찰 비교). `analyze-villa-bidcases.py`: 빌라 낙찰가 모델(`public/villa-winbid.json`).
- 백테스트 스크립트(`backtest-*.py`)는 규칙을 바꾸기 전에 검증하는 용도예요. **규칙을 바꿀 때는 먼저 백테스트로 확인**하는 것이 이 프로젝트의 관행이에요.

## 6. 핵심 계산 요약 (검증 수치는 메모 참조)
- 아파트 예상매도가: 같은 단지·같은 평형 최근 3개월 중위(5건+) 또는 6개월 하위 40%, 층 보정(승강기 반영), 거래 적으면 주변 단지 보완. 필요 마진: 최소 순이익 1,000만(1층 +20%).
- 아파트 예상 낙찰가: `signal|__winbid__`(주간 갱신), 보통 오차 5~6%. 추천가는 **기대수익(낙찰 가능성×순이익) 최대** 1개.
- 빌라 예상매도가: 같은 건물(24개월, ±6㎡) → 같은 동 → 시군구, 거래 **5건 미만이면 동 값과 50:50**, 같은 집 중복 거래 정리. 보통 오차 약 12.7%(건물 5건+ 6%대). 최소 마진 2,000만+연식·근거·승강기 여유. 이슈 의심(3회+ 유찰·최저가 현저히 낮음)·생활권(반경 500m 최근 6개월 거래 0건)은 임장 후보 제외.
- 시험해서 **효과 없어 버린 것**: 반경 방식, 전세가 혼합, 입주예정 물량, 경쟁 예상에 따른 낙찰가 보정, 단지 이력(후발주자) 반영. (메모 `villa-estimation-experiments`, `supply-pipeline-test`)

## 7. 사용자 방침(꼭 지킬 것)
- **사용자에게는 항상 한국어, 쉬운 말**(통계 용어 피함). 추천가는 1개, 옵션을 늘리지 말 것.
- 코드 수정·커밋·푸시·Actions 실행은 직접 진행(저장소 `main`, 작성자 `srreuk <sjck9hy6ps@privaterelay.appleid.com>`, 커밋 끝에 `Co-Authored-By` 줄).
- API 키는 채팅에 반복하지 말 것(비밀값 사용).
- 실제 목록에 시험 데이터를 넣지 말 것. 데이터 삭제 전 확인.
- 빌라는 수도권만. 낙찰사례 지도 배지는 폐지, 경매 배지는 입찰후보·내 재산(낙찰·매도완료)만.

## 8. 1년 뒤 시작 체크리스트
1. GitHub 저장소 클론 → `npm install` → 로컬 실행 `node server.js` 또는 Vercel 배포 확인.
2. **서비스 살아 있는지 확인:** Supabase 프로젝트(유료 갱신), Vercel, GitHub Actions 일정(60일 활동이 없으면 일정이 멈출 수 있음 → 수동으로 한 번 실행), data.go.kr 키 유효기간(만료 시 재신청), 카카오 앱키.
3. 서비스를 새로 만들어야 하면 `docs/RESTORE.md`(복구 방법)와 PC에 받아 둔 백업(`backups/full-*`)을 사용.
4. `diag-storage`, `data-health` 작업을 수동 실행해 적재 상태를 확인.
5. 낙찰사례·경매 CSV를 올리고 `analyze-bidcases` → `precompute-board` 순서로 수동 실행.
6. 비밀값 목록(3절)을 하나씩 확인하고, 안 되는 API는 활용신청 상태를 확인.

## 9. 알려진 한계·남은 일
- 건축물대장(연식·승강기) 전국 수집은 하루 한도로 오래 걸려요(2026-10 중순 완료 예상). 완료 후 빌라 승강기·연식 보정 모델 재시험.
- 빌라 전월세는 2021~2026 수집 시작(건물 단위 전세 시험 재실행 예정).
- 무료 요금제 이전 계획(Supabase 유료 → 정적 파일, Cloudflare Pages): 메모 `free-tier-migration-plan`.
- 지도 한 건물에 평형별로 나뉜 거래 배지는 아직 합치지 않음.

## 10. 메모 색인 (`docs/memory/` 안에 파일별 상세)
- [Deliver full files](deliver-full-files.md) — always give complete modified files, never find/replace patches
- [Auction app workflow](auction-app-workflow.md) — local clone + gh CLI; Claude commits/pushes/runs Actions itself
- [Bidding targets](bidding-targets.md) — 전국 아파트 + 수도권 빌라; per-segment lens (대장·인기순·돈되는 지역)
- [App purpose: sale price](app-purpose-sale-price.md) — bid = 예상매도가 − 비용 − 마진; focus on resale price & future trend, not bid-rate stats
- [Sale-price backtest baseline](sale-price-backtest-baseline.md) — step-1 as-of accuracy on real auction resales + method
- [Region code issues](region-code-issues.md) — all LAWD code/label fixes done 2026-10-02; how they were found and verified
- [Plain-language UI](plain-language-ui.md) — app text must avoid stats jargon; wording patterns used
- [Data health auto-fix](data-health-autofix.md) — weekly check recollects gaps, writes data-health.json → app banner
- [Map loading speed](map-loading-speed.md) — causes/fixes/measurements for badge load time (Redis gzip, IDB cache, warmup)
- [AVM accuracy diagnosis](avm-accuracy-diagnosis.md) — AVM 17.8% apt error from time-trend design; fixes proposed 2026-10-03
- [Redis limit incident](redis-limit-incident.md) — 2026-10-03 Upstash plan limit blocked auctions; never bulk-cache in that DB
- [Building info cache](building-info-cache.md) — 건축물대장 quota errors were cached as empty (fixed 2026-10-03); backlog ~89k
- [Market cycle analysis](market-cycle-analysis.md) — cycle phase/forecast validation/follower-history signal + 📈 사이클 UI
- [Reply in Korean](reply-in-korean.md) — every user-facing reply must be Korean (user insisted twice)
- [UI redesign (아실 style)](ui-redesign-asil.md) — topbar/chipbar/sidebar/right-tools + simple badges; how it's wired
- [Court reduction rules](court-reduction-rules.md) — 유찰 저감률 법원별 실측(서울20/인천·경기30/광주전남 30→20); user believed 수도권20·지방30
- [Goal: realized profit & niche](goal-realized-profit-niche.md) — judge by profit after resale, not win odds; seek overlooked niche segments, not obvious #1 picks
- [My assets & tax profile](my-assets-tax-profile.md) — 매매사업자; 오피스텔 재고 + 중랑 분양권 예정 → 3번째 주택; 💼 내 자산 tab drives tax calcs
- [User app usage flow](user-app-usage-flow.md) — CSV 등록 → 입찰후보 판정 → 상세 확인 → 최소순익 1천 입찰; 내 자산·낙찰사례 업로드
- [First deal = risk first](first-deal-risk-priority.md) — one win/resale builds starting capital; focus on accuracy+reliability of amounts, not extra conservatism
- [Bulk auction & geocode fix](bulk-auction-geocode-fix.md) — 대전 원인: 같은 건물 대량경매(🏢 rule) + 343 wrong-city coords; buildYear from 건축물대장
- [Listing cap & low floor](listing-cap-low-floor.md) — 네이버 매물 붙여넣기·상한 규칙, 승강기별 저층 보정, 수리비 최소
- [Free-tier migration plan](free-tier-migration-plan.md) — Supabase Pro $25 → move trades to static files (Cloudflare Pages) after collection finishes
- [Supply pipeline test](supply-pipeline-test.md) — 입주 예정 물량 검증 2026-10-05: 효과 일관성 없음, 미적용
- [No fake data in live app](no-fake-data-live.md) — never inject test records into live lists; background saves persist them
- [UI cleanup 2026-10-05](ui-cleanup-2026-10-05.md) — menus/modal items hidden or removed; how to restore
- [Villa market logic](villa-market-logic.md) — 빌라는 신고가 동네·평단가(등급)·평형대 수요로 판단; 관련 도구 유지
- [Winbid model](winbid-model.md) — 🎲 예상 낙찰가: 검증 5~6% 오차, 주간 갱신, 앱 보정 +1.8%, 대부분 추천가 낙찰 35% 미만
- [Resale detection limits](resale-detection-limits.md) — 되팔기 매칭 신뢰도 검증(동·층·6개월·플라시보), 6개월 흔적 지표로 쓰기로 결정, 미적용
- [One price + 임장 screening](one-price-visit-screening.md) — 추천가 1개(기대수익 최대)·임장/패스 단순 화면, 마진율 비교 정정
- [Local-first basis](local-first-basis.md) — 값은 단지·법정동 기준, 표본 부족 때만 전국; 2026-10-09 적용 내역
- [Space rental × villa plan](space-rental-villa-plan.md) — 도시민박업 밀집 동 집계(signal|__homestay__), 빌라 수도권·전국수집 계획
- [Weekly report tracking](weekly-report-tracking.md) — 추천가↔낙찰 누적 비교·사건번호 충돌 정정·성적표·지난 리포트 (2026-10-09)
- [Villa estimation rules](villa-estimation-rules.md) — 빌라 예상매도가·최소마진 2,000만+연식/승강기 여유, 요인 실측(2026-10-10)
- [Board precompute](board-precompute.md) — 입찰후보 사전 계산(가상 브라우저)·화면 반응 개선, 운영 방법
- [Villa estimation experiments](villa-estimation-experiments.md) — 반경·전세가 방식 백테스트(기존보다 나쁨), 대장 기준 비교 결과

