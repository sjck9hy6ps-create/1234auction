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

async function main() {
  console.log('📊 예상매도가(30th percentile) 백테스트 시작:', new Date().toISOString());
  console.log('SITE_URL:', SITE_URL);

  const targets = await fetchRegionList();
  console.log(`🎯 대상: ${targets.length}개 지역 (apt만, #481 v1)\n`);

  let cutoff = null;
  const pctErrs = [];
  let regionsChecked = 0;

  for (const region of targets) {
    const data = await backtestOneRegion(region, 'apt');
    await sleep(DELAY_MS);
    if (!data) continue;
    regionsChecked++;
    if (cutoff == null) cutoff = data.cutoff;

    (data.results || []).forEach(r => {
      if (r.actualCount < MIN_ACTUAL_COUNT || !r.actualPpp || !r.predictedPpp) return; // 검증 불가
      const pctErr = Math.abs((r.actualPpp / r.predictedPpp) - 1) * 100;
      pctErrs.push(pctErr);
    });
  }

  pctErrs.sort((a, b) => a - b);
  const n = pctErrs.length;
  const mapePct = n ? Math.round((pctErrs.reduce((a, b) => a + b, 0) / n) * 10) / 10 : null;
  const medianApePct = n
    ? Math.round((n % 2 ? pctErrs[(n - 1) / 2] : (pctErrs[n / 2 - 1] + pctErrs[n / 2]) / 2) * 10) / 10
    : null;

  console.log('\n📊 집계 결과');
  console.log('컷오프:', cutoff, '/ 검사한 지역 수:', regionsChecked);
  console.log('표본 수:', n, '/ 평균오차율(MAPE):', mapePct, '% / 중앙값오차율:', medianApePct, '%');

  const payload = {
    signalType: 'compEstimate_apt',
    cutoff,
    regionsChecked,
    sampleSize: n,
    mapePct,
    medianApePct,
  };

  const saveRes = await fetch(`${SITE_URL}/api/data-coverage?mode=saveCompEstBacktestStats`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!saveRes.ok) {
    const body = await saveRes.json().catch(() => null);
    throw new Error(`결과 저장 실패: HTTP ${saveRes.status} ${body && body.error ? '- ' + body.error : ''}`);
  }
  console.log('\n💾 결과 저장 완료');
}

main().catch(e => {
  console.error('💥 백테스트 스크립트 전체 실패:', e);
  process.exit(1);
});
