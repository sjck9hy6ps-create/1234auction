# 키·비밀값 목록 (이름과 위치만 — 값은 이 저장소에 없어요)

값은 사용자가 직접 채워 넣으세요. 값은 **절대 저장소·채팅에 올리지 마세요.** 아래 표의 "어디에 넣나"에 적힌 곳에 넣어요.
- **GitHub Secrets**: 저장소 → Settings → Secrets and variables → Actions → New repository secret (자동 작업이 읽어요)
- **Vercel Env**: Vercel 프로젝트 → Settings → Environment Variables (앱의 서버 함수 `api/*.js`가 읽어요. 바꾼 뒤 재배포 필요)

## 1. 반드시 필요한 것 (없으면 앱·수집이 멈춰요)
| 이름 | 어디에 넣나 | 무엇에 쓰나 | 어디서 발급 | 쓰는 파일 |
|---|---|---|---|---|
| `SUPABASE_URL` | GitHub + Vercel | 데이터베이스 주소(`https://○○.supabase.co`) | Supabase → Project Settings → API | 거의 모든 `api/*.js`, 모든 수집·분석 작업 |
| `SUPABASE_SERVICE_ROLE_KEY` | GitHub + Vercel | 데이터베이스 전체 읽기·쓰기 키(**가장 민감**, 서버에서만 사용) | Supabase → Project Settings → API → service_role | 위와 동일(78개 파일) |
| `PUBLIC_DATA_API_KEY` | GitHub + Vercel | 공공데이터포털 인증키 — 국토부 실거래(아파트·연립다세대·단독다가구·전월세·분양권) + 건축HUB 건축물대장 4종을 **한 키로 공용** | data.go.kr 마이페이지 → 일반 인증키 + **각 API 활용신청 승인** | `api/get-house.js`, `api/get-building.js`, 수집 작업 23개 |
| `COLLECT_PROXY_SECRET` | GitHub + Vercel (**같은 값**) | GitHub Actions가 국토부 API를 직접 못 부르는 문제를 Vercel 경유(`get-house?action=molitProxy`)로 우회할 때 쓰는 공유 비밀 | 직접 아무 긴 문자열로 정함 | `api/get-house.js` + 수집 작업 19개 |
| `KAKAO_REST_API_KEY` | GitHub | 카카오 지오코딩·좌표→법정동 변환(건축물대장 수집·좌표 웜업·낙찰사례 매칭) | developers.kakao.com → 내 애플리케이션 → REST API 키 | `scripts/warmup-locations.mjs`, `collect-building-info.mjs`, `match-bid-cases.mjs` 등 12개 작업 |
| `SITE_URL` | GitHub (비밀값 또는 workflow 안 값) | 배포된 앱 주소(`https://1234auction.vercel.app`) — 작업이 앱 API를 부를 때 | Vercel 배포 주소 | 수집·분석 작업 32개 |

## 2. 앱 화면에 직접 들어 있는 키 (환경변수 아님)
| 이름 | 위치 | 설명 |
|---|---|---|
| 카카오맵 **JavaScript 키** | `public/index.html` 안 `https://dapi.kakao.com/v2/maps/sdk.js?appkey=…` (약 5314번째 줄) | 지도 표시용. 브라우저에 공개되는 키라서 **카카오 개발자 콘솔의 "플랫폼 → Web 사이트 도메인"에 앱 주소를 등록**하는 방식으로 보호해요. 새로 발급하면 이 줄의 값을 바꾸고 배포하세요. |

## 3. 선택(없으면 해당 기능만 꺼져요)
| 이름 | 어디에 넣나 | 쓰는 기능 | 발급 | 쓰는 파일 |
|---|---|---|---|---|
| `UPSTASH_REDIS_URL`, `UPSTASH_REDIS_TOKEN` | Vercel | 응답 캐시(Upstash Redis). **대량 저장 금지**(무료 한도 초과 사고 있었음) | upstash.com 콘솔 | `api/auction.js`, `api/get-house.js`, `api/parse-auction.js` |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | GitHub | 저장 용량 점검 작업(`diag-storage`)용. 위와 **같은 Redis의 REST 주소·토큰**(이름만 달라요) | upstash.com 콘솔 | `scripts/diag-storage.mjs` |
| `NEIS_API_KEY` | GitHub | 학군 정보(나이스 교육정보) 갱신 `sync-school` | open.neis.go.kr | `.github/workflows/sync-school.yml` |
| `ANTHROPIC_API_KEY` | Vercel | 경매 물건 문서·사진 자동 읽기(AI) `parse-auction` | console.anthropic.com | `api/parse-auction.js` |
| `GEMINI_API_KEY` | Vercel | 등기부 자동 읽기 `parse-registry`(옛 방식, 안 쓰면 생략 가능) | aistudio.google.com | `api/parse-registry.js` |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | Vercel | 네이버 검색 API(경매 물건 주변 정보 검색) | developers.naver.com | `api/parse-auction.js` |
| `ECOS_API_KEY` | Vercel | 한국은행 기준금리(대출이자 계산 참고) | ecos.bok.or.kr | `api/data-coverage.js` |
| `RONE_API_KEY` | Vercel | 한국부동산원 R-ONE 통계(시장 지표) | reb.or.kr/r-one | `api/data-coverage.js` |
| `VWORLD_API_KEY`, `VWORLD_DOMAIN` | Vercel | 공시가격 조회(브이월드). `VWORLD_DOMAIN`은 키 발급 때 등록한 도메인 | vworld.kr → 오픈API | `api/get-official-price.js` |

## 4. 외부 서비스 계정·승인 목록 (키가 아니라 "계정/신청")
- **Supabase**(데이터베이스, 유료 플랜 갱신일 주기적으로 확인) · **Vercel**(호스팅) · **GitHub**(코드·자동 작업) · **Upstash**(Redis 캐시)
- **data.go.kr 활용신청**(승인 상태 확인): 국토부 아파트 매매 상세·아파트 전월세·연립다세대 매매·**연립다세대 전월세**·단독/다가구 매매·분양권 전매 · 건축HUB 건축물대장 4종(표제부, 공동주택가격, 층별개요, 전유공용면적). 일일 한도: 건축HUB 각 10,000건.
- **카카오 개발자**(앱 1개: REST 키 + JavaScript 키 + 도메인 등록) · 나이스 · 한국은행 ECOS · R-ONE · 브이월드 · 네이버 개발자 · Anthropic/Google AI(선택)
- 외부 사이트 로그인은 **앱이 자동 입력하지 않아요**: 법원경매·탱크옥션(유료)·바토너·네이버부동산은 사용자가 직접 로그인.

## 5. 한눈에 보는 입력 장소
- **GitHub Secrets에 넣을 것(9개):** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `PUBLIC_DATA_API_KEY`, `COLLECT_PROXY_SECRET`, `KAKAO_REST_API_KEY`, `SITE_URL`, `NEIS_API_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`
- **Vercel Environment Variables에 넣을 것:** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `PUBLIC_DATA_API_KEY`, `COLLECT_PROXY_SECRET`, `UPSTASH_REDIS_URL`, `UPSTASH_REDIS_TOKEN` + 선택 `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `ECOS_API_KEY`, `RONE_API_KEY`, `VWORLD_API_KEY`, `VWORLD_DOMAIN`
- 이 저장소의 `.env.example`은 위 이름을 빈 값으로 모아 둔 양식이에요(로컬 실행용 `.env`로 복사해 채우면 돼요. `.env`는 `.gitignore`에 들어 있어야 해요).
