---
name: avm-accuracy-diagnosis
description: AVM (train-avm.py + data-coverage avmEstimate) diagnosed 2026-10-03 — causes of poor accuracy and the proposed fixes
metadata:
  type: project
---

Scored on Aug–Oct 2026 real trades (광주, 부산 해운대, 서울 서초, 안산 상록) via the API:
- Apartments: median error 17.8%, biased +17% high, 42% of trades off by more than 20%. The danji level is just as bad.
- Villas (grid level): median error 16%, bias about 0, 38% off by more than 20%.
- For comparison, the comp-based 예상매도가 is about 6% median error.

Causes:
1. train-avm.py models time as a linear time_trend plus national month dummies over 2017~. avmFeatureVector predicts "today" with the month dummies at 0 and only the linear trend, so regional cycles are ignored.
2. Group (danji/grid) effects are constant across 9 years.
3. Villas use a 1km grid, so different buildings get mixed.
4. The shown ±15% range comes from a random 80/20 split, which is optimistic for predicting today.

Test: a leave-one-out 시군구 recent-bias correction took apartments from 17.8% to 7.0% median error (within ±10%: 25%→65%). It did not help villas (15.9→15.4).

Proposed fixes, awaiting user OK:
- 시군구×quarter time effects, predicting with the latest quarter.
- A recent-window group effect.
- Villa building-level (dong+지번) effect.
- A time-split holdout for the displayed range.
- Show AVM as secondary when own-complex comps exist.

DONE 2026-10-03: AVM v2 is live.
- Changes: AVM_DEFAULT_VERSION='v2', the frontend sends &ver=v2, and train-avm.yml trains v2 weekly. Models are stored as apt_v2/villa_v2; feature_ranges.region_time_effects holds the latest quarter per 시군구.
- Time-split holdout: apartments median 6.2%, within ±10% 69%, bias −1.8%. Villas: building level 16%, grid 16%, overall 21% (the default_fallback rows in the holdout inflate this).
- API check on recent trades: apartments 12.2%→5.9%, villas 15.9%→12.5%, villas at building level 7.2%.
- 옥천 (진월동) is now 1.19억, versus 1.87억 before; its actual trades were 1.11–1.3억.
- The UI greys AVM out as a secondary value when the own complex has recent trades.
