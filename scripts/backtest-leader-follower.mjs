/* ════════════════════════════════════
   후발주자 신호 백테스트 스크립트 (#480)
   - 사용자 요청: "기존 참고자료들의 신뢰도를 높일 수 있는 방법이 더 중요할 거 같아" →
     "올해데이터를 제외하고 작년데이터는 모두 백데이터화 시켜. 백데이터에 자동수집되는
     올해 내용을 덮어씌워 계산을 새로 하는 방법이 필요해."
   - 방식: mode=backtestSignalRegion(지역별로 작년 12/31 기준 후발주자 예측 + 이미
     수집된 올해 실거래로 실제 결과를 함께 반환)을 warmup-leader-follower.mjs와 동일한
     방식(순차 호출, 지역 사이 딜레이)으로 전국을 순회해 모은 뒤, 이 스크립트에서 집계함.
     집계 로직을 서버(data-coverage.js) 쪽에 넣지 않은 이유: 한 번의 요청/지역으로
     끝내야 Vercel 타임아웃(#468에서 이미 겪은 문제)을 피할 수 있고, 여러 지역을 모아
     비교하는 집계 자체는 가벼운 연산이라 스크립트 쪽에서 처리하는 게 안전함.
   - 판정 기준: 어떤 법정동의 대장 아파트 A와 "후발주자로 예측된" 단지 B가 있을 때,
     작년 말 기준 예측이 맞았다면 올해 B의 상승률이 A의 상승률보다 높아야 함(격차가
     줄어드는 방향). 이 조건이 실제로 만족된 비율을 "적중률"로, 비교 기준선으로 순위는
     있지만 후발주자 자격은 없었던(qualifies=false) 단지들의 같은 지표도 함께 계산해서
     "후발주자 표식이 실제로 의미가 있는지"(기준선보다 유의미하게 높은지)를 판단할 수
     있게 함.
   - 표본 필터: 올해 실거래가 3건 미만인 단지는 "검증 불가"로 보고 통계에서 제외함
     (거래가 뜸한 지방 소규모 단지는 1~2건만으로 오르내림을 판단하면 노이즈가 큼).
════════════════════════════════════ */
const SITE_URL = (process.env.SITE_URL?.trim()) || 'https://1234auction.vercel.app';
const DELAY_MS = 300;
const TIMEOUT_MS = 60000; // vercel.json maxDuration(60초)과 맞춤 - warmup-leader-follower.mjs와 동일
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

// 이 단지의 "올해 상승률(%)" - 컷오프 시점 평단가(recentPpp) 대비 올해 실제 평단가(actualPpp)
function pctChange(before, after) {
  if (!before || !after) return null;
  return ((after / before) - 1) * 100;
}

async function main() {
  console.log('📊 후발주자 신호 백테스트 시작:', new Date().toISOString());
  console.log('SITE_URL:', SITE_URL);

  const targets = await fetchRegionList();
  console.log(`🎯 대상: ${targets.length}개 지역 (apt만, #480 v1)\n`);

  let cutoff = null;
  const followerRows = [];    // { catchupDiffPct }
  const nonFollowerRows = [];
  let regionsChecked = 0;

  for (const region of targets) {
    const data = await backtestOneRegion(region, 'apt');
    await sleep(DELAY_MS);
    if (!data) continue;
    regionsChecked++;
    if (cutoff == null) cutoff = data.cutoff;

    // dong -> leader actualPct 매핑 먼저 구성
    const leaderPctByDong = {};
    (data.results || []).filter(r => r.role === 'leader').forEach(r => {
      const pct = pctChange(r.recentPpp, r.actualPpp);
      if (pct != null && r.actualCount >= MIN_ACTUAL_COUNT) leaderPctByDong[r.dong] = pct;
    });

    (data.results || []).forEach(r => {
      if (r.role !== 'follower' && r.role !== 'nonfollower') return;
      if (r.actualCount < MIN_ACTUAL_COUNT) return; // 올해 표본 부족 - 검증 불가
      const leaderPct = leaderPctByDong[r.dong];
      if (leaderPct == null) return; // 대장 쪽 표본이 부족해 비교 기준 자체가 없음
      const myPct = pctChange(r.recentPpp, r.actualPpp);
      if (myPct == null) return;
      const catchupDiffPct = myPct - leaderPct; // 양수면 "대장보다 더 올라 격차가 줄었다" = 예측 적중
      const row = { region, dong: r.dong, danji: r.danji, catchupDiffPct };
      if (r.role === 'follower') followerRows.push(row); else nonFollowerRows.push(row);
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

  const followerSummary = summarize(followerRows);
  const nonFollowerSummary = summarize(nonFollowerRows);

  console.log('\n📊 집계 결과');
  console.log('컷오프:', cutoff, '/ 검사한 지역 수:', regionsChecked);
  console.log('후발주자(qualifies=true):', followerSummary);
  console.log('비교기준(순위는 있으나 후발주자 아님):', nonFollowerSummary);

  const payload = {
    signalType: 'leaderFollower_apt',
    cutoff,
    regionsChecked,
    sampleSizeFollower: followerSummary.sampleSize,
    sampleSizeNonFollower: nonFollowerSummary.sampleSize,
    hitRateFollower: followerSummary.hitRate,
    hitRateNonFollower: nonFollowerSummary.hitRate,
    avgFollowerCatchUpPct: followerSummary.avgCatchUpPct,
    avgNonFollowerCatchUpPct: nonFollowerSummary.avgCatchUpPct,
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
  console.log('\n💾 결과 저장 완료');
}

main().catch(e => {
  console.error('💥 백테스트 스크립트 전체 실패:', e);
  process.exit(1);
});
