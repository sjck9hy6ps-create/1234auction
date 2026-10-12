# 규칙 검증(백테스트) 방법 — 2026-10-12

새 규칙(추천가·인수·월세 기준 등)을 앱에 넣기 전에 과거 낙찰 사례로 "그 규칙으로 입찰했다면 손해 비율·순이익이 어땠나"를 확인하는 순서.

1. 최근 `analyze-bidcases` 실행의 아티팩트 `bidcases-R`를 내려받음: `gh run download <실행번호> -n bidcases-R`
2. `python scripts/backtest/prep-rows.py bidcases-R.csv.gz rows.json 10000` (예상매도가 1억 미만 사례만; 마지막 인자로 상한 변경)
3. `curl -s "https://1234auction.vercel.app/api/auction?kind=bidCases" -o bc.json`, 같은 방식으로 `kind=myAssets` → `ma.json`(내 세금 설정을 계산에 반영)
4. `node scripts/backtest/run-rule.cjs rows.json bc.json ma.json [rule.cjs]` — 규칙 파일을 안 주면 "순이익 1천만 기준 vs 순이익률 10·12·15%" 비교가 나옴
   - 규칙 파일: `module.exports = { groups(ctx, a, E, M, h0, solve) { return [[이름, 입찰상한(만원)]]; } }`
5. 읽는 법: 손해 비율·순이익 중앙값을 기존 규칙과 나란히 비교. 되팔림이 확인된 사례만 셈(못 판 물건 제외) → 절대값보다 규칙 간 차이를 봄. 표본이 30건 아래면 우연일 수 있음.

`scripts/lib/load-app.cjs`는 `public/index.html`의 계산 함수를 Node에서 그대로 불러옴(`APP_HTML`로 옛 버전 비교 가능: `git show <커밋>:public/index.html > old.html`).
참고: 2026-10-11 저가 아파트 순이익률 10% 추천가 규칙은 이 방식으로 검증해 손해 30~42%(기존 18~21%)로 폐기.
