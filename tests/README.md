# 시험

- `npm run test:rights` : 탱크옥션 상세 → 권리분석 읽기 회귀 시험. 실제 수집 원문(`tests/fixtures-private/*.txt`, 실명이 있어 git 제외)을 읽어 원문에서 따로 읽은 값(임차인·등기·금액·날짜)과 대조하고, `tests/snapshots/rights-snapshot.json`(이전 확인 결과)과도 비교해요.
- 읽기 코드(`rightsParseFull` 등)를 고칠 때마다 돌리세요. 의도한 변경이면 `node tests/rights-regression.cjs --update`로 기준 결과를 갱신해요.
- 새 사건 원문을 시험에 넣으려면 `tests/fixtures-private/YYYY-번호.txt`로 저장하고 `--update`.

## 계산 자동 검증 (calc-regression.mjs)

취득세·소득세·재산세·종부세·중개수수료·인지세 표, 장부 계산(비용·이자·부가세·세금·건보료·결손금 이월·매도 후 고정), 입찰 추천가↔순이익 일치, 무작위 장부 600건, 세율 파일(tax-rates.json) 형식을 점검합니다.
- 실행: `node tests/calc-regression.mjs` (내 컴퓨터는 `npm i --no-save playwright-core` + `CHROME_PATH` 지정)
- GitHub Actions `verify-calcs`가 public·api 변경 push, PR, 매일 새벽에 자동 실행합니다.
- 법이 바뀌어 기준값을 고칠 때는 이 파일의 기대값도 함께 고쳐야 합니다.

## 화면 조작 자동 시험 (ui-regression.mjs)

가상 브라우저에서 실제로 클릭·입력해 장부 입력 화면을 점검합니다(저장·서버 요청은 하지 않음): 기본 정보 카드→팝업 입력, 비용 카드→팝업 금액 입력, 비용 추가, 초안 자동 보관·새로고침 복원, 모바일 폭에서 설명 버튼 겹침 여부.
- 실행: `npm run test:ui` (내 컴퓨터는 `CHROME_PATH` 지정). `node_modules`는 이제 git에서 빠졌으니 설치 후 되돌릴 필요 없음.
