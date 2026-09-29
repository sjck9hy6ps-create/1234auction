/* ════════════════════════════════════
   예상매도가(비교물건 30th percentile) 대규모 히스토리 백테스트 스크립트 (#481)
   - 사용자 요청 "기존 참고자료들의 신뢰도를 높일 수 있는 방법이 더 중요할 거 같아" →
     "전부 순서대로 진행"의 세 번째 항목. #479(후발주자 백테스트)와 완전히 같은 방식(작년
     1/1~12/31을 백데이터로 고정, 올해 실거래로 검증)을 예상매도가 로직에 적용함.
   - getCompEstValueHeadless()가 실제 서빙에서 쓰는 핵심 통계(IQR 이상치 제거 후
     30th percentile)만 그대로 재현해서, "이 통계 방법 자체가 실제로 얼마나 잘 맞는지"를
     전국 단위로 검증함. 개별 목표물건과의 평형/층/연식/거리 유사도 가중치(실서빙 로직의
     나머지 절반)는 지역 전체를 순회하는 대규모 백테스트 특성상 재현하지 않음 - 이 단순화는
     의도적이며, index.html 안내문에도 명시함.
   - 집계 로직을 서버(data-coverage.js) 쪽에 넣지 않은 이유는 #479와 동일: 한 번의
     요청/지역으로 끝내야 Vercel 타임아웃을 피할 수 있고, 여러 지역을 모아 비교하는 집계
     자체는 가벼운 연산이라 스크립트 쪽에서 처리하는 게 안전함.
   - 표본 필터: 작년 표본이 5건 미만인 단지는 애초에 서버가 예측 대상에서 제외함
     (mode=backtestCompEstRegion, MIN_PRE_SAMPLE). 올해 실거래가 3건 미만인 단지도
     "검증 불가"로 보고 통계에서 제외함(거래가 뜸한 지방 소규모 단지는 1~2건만으로
     오차율을 판단하면 노이즈가 큼 - #479와 동일 기준).
════════════════════════════════════ */
const SITE_URL = (process.env.SITE_URL?.trim()) || 'https://1234auction.vercel.app';
const DELAY_MS = 300;
const TIMEOUT_MS = 60000; // vercel.json maxDuration(60초)과 맞춤 - warmup/backtest 스크립트들과 동일
const MIN_ACTUAL_COUNT = 3; // 올해 실거래 최소 건수(이보다 적으면 검증 불가로 제외)

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function fetchRegionList() {
  const res = await fetch(`${SITE_URL}/api/data-coverage?mode=regionList`);
  if (!res.ok) throw new Error(`regionList 조회 실패: HTTP ${res.status}`);
  const data = await res.json();
  if (!data || !data.bySido) throw new Error('regionList 응답에 bySido가 없습니다.');
  const targets = [];
  Object.keys(data.bySido).forEach(sido => {
    (data.bySido[sido] || []).forEach(gu => targets.push(`${sido} ${gu}`));
  });
  return targets;
}

async function backtestOneRegion(region, type) {
  const url = `${SITE_URL}/api/data-coverage?mode=backtestCompEstRegion&type=${type}&region=${encodeURIComponent(region)}`;
  const startedAt = Date.now();
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      console.error(`❌ [${region}] 실패: HTTP ${res.status} (${elapsed}초) ${body && body.error ? '- ' + body.error : ''}`);
      return null;
    }
    const data = await res.json();
    console.log(`✅ [${region}] 완료 (${(data.results || []).length}건, ${elapsed}초)`);
    return data;
  } catch (e) {
    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
    console.error(`❌ [${region}] 오류(${elapsed}초):`, e.message);
    return null;
  }
}

// ⚠️ 2026-09(사용자 요청 "빌라 백테스트 진행해줘" - #488 신뢰도 작업의 연장): v1(#481)은
// apt만 돌렸음 - 사용자가 아파트/빌라 신뢰도를 따로 물어봤을 때 빌라 쪽은 실측 수치가
// 아예 없어서 "느낌상" 답할 수밖에 없었음. 서버(mode=backtestCompEstRegion)는 처음부터
// type=villa를 이미 지원하고 있었으므로(data-coverage.js), 이 스크립트만 apt 하나로
// 고정돼 있던 걸 두 타입 다 순회하도록 바꿈 - 지역 목록/딜레이/저장 방식은 완전히 동일하게
// 재사용하고, 타입별로 별도 signalType('compEstimate_apt' / 'compEstimate_villa')로 저장해
// 기존 apt 통계를 덮어쓰지 않음.
// ⚠️ 2026-09(#492 "편향 계산 추가" + #493 "보수적/중간값 나란히"): 기존엔 30th percentile
// (실서빙값) 기준 절대오차(부호 없음)만 쟀음. 이번에 (1) 부호 있는 오차(signed - 실제/예측 기준,
// 양수면 실제가 예측보다 높았다는 뜻)를 같이 재서 "쏠림 방향"을 알 수 있게 하고, (2) 50th
// percentile(진짜 중앙값, 서버가 predictedMedianPpp로 같이 내려줌) 기준 오차도 나란히 재서
// 두 방식 중 어느 쪽이 실제로 더 잘 맞는지 비교할 수 있게 함.
function summarizeErrors(rows, predictedField) {
  const absErrs = [], signedErrs = [];
  rows.forEach(r => {
    const predicted = r[predictedField];
    if (r.actualCount < MIN_ACTUAL_COUNT || !r.actualPpp || !predicted) return;
    const signedPct = ((r.actualPpp / predicted) - 1) * 100; // 양수=실제가 예측보다 높음
    signedErrs.push(signedPct);
    absErrs.push(Math.abs(signedPct));
  });
  function med(arr) {
    if (!arr.length) return null;
    const s = arr.slice().sort((a, b) => a - b);
    const n = s.length;
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  }
  function mean(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null; }
  const round1 = v => v === null ? null : Math.round(v * 10) / 10;
  return {
    n: absErrs.length,
    mapePct: round1(mean(absErrs)),
    medianApePct: round1(med(absErrs)),
    meanBiasPct: round1(mean(signedErrs)),
    medianBiasPct: round1(med(signedErrs)),
  };
}

async function runOneType(targets, type) {
  let cutoff = null;
  const allRows = [];
  let regionsChecked = 0;

  for (const region of targets) {
    const data = await backtestOneRegion(region, type);
    await sleep(DELAY_MS);
    if (!data) continue;
    regionsChecked++;
    if (cutoff == null) cutoff = data.cutoff;
    (data.results || []).forEach(r => allRows.push(r));
  }

  const p30 = summarizeErrors(allRows, 'predictedPpp');       // 실서빙값(30th, 보수적)
  const p50 = summarizeErrors(allRows, 'predictedMedianPpp'); // 진짜 중앙값(50th, 참고 비교용)

  console.log(`\n📊 [${type}] 집계 결과 (30th percentile - 실서빙 기준)`);
  console.log('컷오프:', cutoff, '/ 검사한 지역 수:', regionsChecked);
  console.log('표본 수:', p30.n, '/ MAPE:', p30.mapePct, '% / 중앙값오차율:', p30.medianApePct,
    '% / 평균쏠림(부호):', p30.meanBiasPct, '% / 중앙값쏠림(부호):', p30.medianBiasPct, '%');
  console.log(`📊 [${type}] 참고: 50th percentile(진짜 중앙값) 기준`);
  console.log('표본 수:', p50.n, '/ MAPE:', p50.mapePct, '% / 중앙값오차율:', p50.medianApePct,
    '% / 평균쏠림(부호):', p50.meanBiasPct, '% / 중앙값쏠림(부호):', p50.medianBiasPct, '%');

  const payload = {
    signalType: `compEstimate_${type}`,
    cutoff,
    regionsChecked,
    sampleSize: p30.n,
    mapePct: p30.mapePct,
    medianApePct: p30.medianApePct,
    meanBiasPct: p30.meanBiasPct,
    medianBiasPct: p30.medianBiasPct,
    mapePctP50: p50.mapePct,
    medianApePctP50: p50.medianApePct,
    meanBiasPctP50: p50.meanBiasPct,
    medianBiasPctP50: p50.medianBiasPct,
  };

  const saveRes = await fetch(`${SITE_URL}/api/data-coverage?mode=saveCompEstBacktestStats`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!saveRes.ok) {
    const body = await saveRes.json().catch(() => null);
    throw new Error(`[${type}] 결과 저장 실패: HTTP ${saveRes.status} ${body && body.error ? '- ' + body.error : ''}`);
  }
  console.log(`💾 [${type}] 결과 저장 완료`);
}

async function main() {
  console.log('📊 예상매도가(30th percentile) 백테스트 시작:', new Date().toISOString());
  console.log('SITE_URL:', SITE_URL);

  const targets = await fetchRegionList();
  console.log(`🎯 대상: ${targets.length}개 지역 × apt/villa 2종\n`);

  await runOneType(targets, 'apt');
  await runOneType(targets, 'villa');
}

main().catch(e => {
  console.error('💥 백테스트 스크립트 전체 실패:', e);
  process.exit(1);
});
