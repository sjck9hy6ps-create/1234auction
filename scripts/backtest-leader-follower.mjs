/* ════════════════════════════════════
   후발주자 신호 백테스트 스크립트 (#480, 2026-09 분기별 세분화)
   - 사용자 요청(1차): "기존 참고자료들의 신뢰도를 높일 수 있는 방법이 더 중요할 거 같아" →
     "올해데이터를 제외하고 작년데이터는 모두 백데이터화 시켜. 백데이터에 자동수집되는
     올해 내용을 덮어씌워 계산을 새로 하는 방법이 필요해."
   - 사용자 요청(2차, 분기별 세분화): "업로드된 17년도 자료부터 시작점을 잡아줘. 과거
     자료를 매번 반복해서 확인한다면 로딩속도가 느려지니, 17년도부터 25년도까지의
     자료를 백데이터로 활용하고, 올해부터 자료를 누적적용해줘. 분기별 흐름이 조금더
     디테일해 나에게 필요한 정보로 더 활용될거같아" → 대장→후발주자로 이어지는 "시차"
     자체가 실제로 맞는지(대장이 오른 뒤 몇 개월 뒤에 후발주자가 따라오는지)를 검증하려면
     올해 1년을 통째로 뭉쳐서 1점만 보는 걸로는 부족함 - 분기(Q1~Q4) 단위로 쪼개서
     "연초~해당 분기말 누적" 기준 적중률 추이를 봄.
   - 방식: mode=backtestSignalRegion(지역별로 작년 12/31 기준 후발주자 예측 + 이미
     수집된 올해 실거래를 분기별 원본 버킷으로 함께 반환)을 warmup-leader-follower.mjs와
     동일한 방식(순차 호출, 지역 사이 딜레이)으로 전국을 순회해 모은 뒤, 이 스크립트에서
     분기 경계로 누적 집계함. 컷오프 계산(2017~작년 전체, computeLeaderFollowerFresh의
     무거운 부분)은 지역당 여전히 1번만 호출되므로 속도 저하 없음 - 서버가 이미 받아온
     분기별 원본 값을 이 스크립트가 누적으로 재구성만 함.
   - 판정 기준: 어떤 법정동의 대장 아파트 A와 "후발주자로 예측된" 단지 B가 있을 때,
     작년 말 기준 예측이 맞았다면 각 분기 시점까지 누적된 B의 상승률이 A의 상승률보다
     높아야 함(격차가 줄어드는 방향). 이 조건이 실제로 만족된 비율을 분기별로 "적중률"로,
     비교 기준선으로 순위는 있지만 후발주자 자격은 없었던(qualifies=false) 단지들의 같은
     지표도 함께 계산해서 "후발주자 표식이 실제로 의미가 있는지"를 판단할 수 있게 함.
   - 표본 필터: 해당 분기까지 누적 실거래가 3건 미만인 단지는 그 분기에서 "검증 불가"로
     제외함(거래가 뜸한 지방 소규모 단지는 몇 건만으로 오르내림을 판단하면 노이즈가 큼).
════════════════════════════════════ */
const SITE_URL = (process.env.SITE_URL?.trim()) || 'https://1234auction.vercel.app';
const DELAY_MS = 300;
const TIMEOUT_MS = 60000; // vercel.json maxDuration(60초)과 맞춤 - warmup-leader-follower.mjs와 동일
const MIN_ACTUAL_COUNT = 3; // 누적 실거래 최소 건수(이보다 적으면 검증 불가로 제외)
const NUM_QUARTERS = 4;

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
  const url = `${SITE_URL}/api/data-coverage?mode=backtestSignalRegion&type=${type}&region=${encodeURIComponent(region)}`;
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

// 이 단지의 "누적 상승률(%)" - 컷오프 시점 평단가(recentPpp) 대비 연초~해당 분기말 누적 평단가
function pctChange(before, after) {
  if (!before || !after) return null;
  return ((after / before) - 1) * 100;
}

// actualByQuarter([{q,avg,count}, ...] 분기별 비누적 원본)를 "연초~분기 q말 누적"
// 가중평균 배열(길이 NUM_QUARTERS)로 변환함. 아직 도래하지 않았거나 거래가 없는 분기는
// null로 남김(사용자 요청 "올해부터 자료를 누적적용" - 연말까지 기다리지 않고 분기가
// 지날 때마다 그 시점까지 쌓인 데이터로 바로 검증할 수 있게 함).
function toCumulative(byQuarter) {
  const cum = new Array(NUM_QUARTERS).fill(null); // { sum, count }
  let runningSum = 0, runningCount = 0;
  for (let q = 0; q < NUM_QUARTERS; q++) {
    const b = (byQuarter || []).find(x => x.q === q);
    if (b && b.count > 0) { runningSum += b.avg * b.count; runningCount += b.count; }
    cum[q] = runningCount > 0 ? { avg: runningSum / runningCount, count: runningCount } : null;
  }
  return cum;
}

async function main() {
  console.log('📊 후발주자 신호 백테스트 시작(분기별 누적):', new Date().toISOString());
  console.log('SITE_URL:', SITE_URL);

  const targets = await fetchRegionList();
  console.log(`🎯 대상: ${targets.length}개 지역 (apt만)\n`);

  let cutoff = null;
  // 분기별로 별도 배열 - qRows[q] = { follower: [...], nonFollower: [...] }
  const qRows = Array.from({ length: NUM_QUARTERS }, () => ({ follower: [], nonFollower: [] }));
  let regionsChecked = 0;

  for (const region of targets) {
    const data = await backtestOneRegion(region, 'apt');
    await sleep(DELAY_MS);
    if (!data) continue;
    regionsChecked++;
    if (cutoff == null) cutoff = data.cutoff;

    // dong -> leader 누적 배열 매핑 먼저 구성
    const leaderCumByDong = {};
    (data.results || []).filter(r => r.role === 'leader').forEach(r => {
      leaderCumByDong[r.dong] = toCumulative(r.actualByQuarter);
    });

    (data.results || []).forEach(r => {
      if (r.role !== 'follower' && r.role !== 'nonfollower') return;
      const leaderCum = leaderCumByDong[r.dong];
      if (!leaderCum) return; // 대장 쪽 표본이 부족해 비교 기준 자체가 없음
      const myCum = toCumulative(r.actualByQuarter);
      for (let q = 0; q < NUM_QUARTERS; q++) {
        const lc = leaderCum[q], mc = myCum[q];
        if (!lc || lc.count < MIN_ACTUAL_COUNT || !mc || mc.count < MIN_ACTUAL_COUNT) continue;
        const leaderPct = pctChange(r.leaderRecentPpp, lc.avg);
        const myPct = pctChange(r.recentPpp, mc.avg);
        if (leaderPct == null || myPct == null) continue;
        const catchupDiffPct = myPct - leaderPct; // 양수면 "대장보다 더 올라 격차가 줄었다" = 예측 적중
        const row = { region, dong: r.dong, danji: r.danji, catchupDiffPct };
        if (r.role === 'follower') qRows[q].follower.push(row); else qRows[q].nonFollower.push(row);
      }
    });
  }

  function summarize(rows) {
    if (!rows.length) return { sampleSize: 0, hitRate: null, avgCatchUpPct: null };
    const hits = rows.filter(r => r.catchupDiffPct > 0).length;
    const avg = rows.reduce((a, r) => a + r.catchupDiffPct, 0) / rows.length;
    return {
      sampleSize: rows.length,
      hitRate: Math.round((hits / rows.length) * 1000) / 10,
      avgCatchUpPct: Math.round(avg * 10) / 10,
    };
  }

  const byQuarter = {};
  console.log('\n📊 분기별(연초~분기말 누적) 집계 결과');
  console.log('컷오프:', cutoff, '/ 검사한 지역 수:', regionsChecked);
  for (let q = 0; q < NUM_QUARTERS; q++) {
    const followerSummary = summarize(qRows[q].follower);
    const nonFollowerSummary = summarize(qRows[q].nonFollower);
    console.log(`Q${q + 1} 누적 - 후발주자:`, followerSummary, '/ 비교기준:', nonFollowerSummary);
    byQuarter[`q${q + 1}`] = {
      sampleSizeFollower: followerSummary.sampleSize,
      sampleSizeNonFollower: nonFollowerSummary.sampleSize,
      hitRateFollower: followerSummary.hitRate,
      hitRateNonFollower: nonFollowerSummary.hitRate,
      avgFollowerCatchUpPct: followerSummary.avgCatchUpPct,
      avgNonFollowerCatchUpPct: nonFollowerSummary.avgCatchUpPct,
    };
  }

  // 전체 요약(기존 호환 컬럼)은 "지금까지 도달한 가장 최근 분기"의 누적값을 그대로 씀 -
  // 연말 이전엔 자연스럽게 Q1/Q2/Q3 등 진행 중인 분기 값이 되고, 연말이 지나면 Q4(=작년의
  // "올해 전체"와 동일한 의미)가 됨.
  let latestQ = -1;
  for (let q = NUM_QUARTERS - 1; q >= 0; q--) {
    if (qRows[q].follower.length > 0 || qRows[q].nonFollower.length > 0) { latestQ = q; break; }
  }
  const latest = latestQ >= 0 ? byQuarter[`q${latestQ + 1}`] : {
    sampleSizeFollower: 0, sampleSizeNonFollower: 0, hitRateFollower: null, hitRateNonFollower: null,
    avgFollowerCatchUpPct: null, avgNonFollowerCatchUpPct: null,
  };

  const payload = {
    signalType: 'leaderFollower_apt',
    cutoff,
    regionsChecked,
    ...latest,
    byQuarter,
  };

  const saveRes = await fetch(`${SITE_URL}/api/data-coverage?mode=saveSignalBacktestStats`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!saveRes.ok) {
    const body = await saveRes.json().catch(() => null);
    throw new Error(`결과 저장 실패: HTTP ${saveRes.status} ${body && body.error ? '- ' + body.error : ''}`);
  }
  console.log('\n💾 결과 저장 완료(최신 분기: Q' + (latestQ + 1) + ' 기준 요약 + 분기별 상세)');
}

main().catch(e => {
  console.error('💥 백테스트 스크립트 전체 실패:', e);
  process.exit(1);
});
