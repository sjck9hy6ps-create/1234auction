# 시험

- `npm run test:rights` : 탱크옥션 상세 → 권리분석 읽기 회귀 시험. 실제 수집 원문(`tests/fixtures-private/*.txt`, 실명이 있어 git 제외)을 읽어 원문에서 따로 읽은 값(임차인·등기·금액·날짜)과 대조하고, `tests/snapshots/rights-snapshot.json`(이전 확인 결과)과도 비교해요.
- 읽기 코드(`rightsParseFull` 등)를 고칠 때마다 돌리세요. 의도한 변경이면 `node tests/rights-regression.cjs --update`로 기준 결과를 갱신해요.
- 새 사건 원문을 시험에 넣으려면 `tests/fixtures-private/YYYY-번호.txt`로 저장하고 `--update`.
