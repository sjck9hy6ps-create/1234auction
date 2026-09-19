/* ════════════════════════════════════
   대장/후발주자 인기순위(mode=leaderFollower) 캐시 웜업 스크립트
   - 2026-09(사용자 피드백: "배지표기가 느린게 내가 느리다고 표현하는거 같아"): 지도가
     새 시/군/구를 자동으로 처음 조회할 때(index.html autoLoadLeaderFollowerForRegion),
     leader_follower_cache에 그 지역 캐시가 없으면 전체이력(2017-09~) 기반 시차상관+
     복합점수 계산을 새로 도는데 이게 최대 26초 가까이 걸림(#465/#466 참고) - 그 시간
     동안은 배지에 순위(대장/2/3/4)가 안 붙어 보임.
   - get-house 캐시 웜업(warmup-house-cache.mjs)과 똑같은 방식: 실제 서비스 API를
     그대로 호출해서 서버 캐시를 미리 채워둠 - 이러면 사용자가 낮에 그 지역을 처음
     봐도 이미 캐시가 있어(≈0.4초) 배지가 거의 바로 뜸.
   - 대상 지역 목록은 새로 만들지 않고, 프론트 드롭다운이 쓰는 것과 동일한
     mode=regionList(전국 시/군/구)를 그대로 재사용함 - 대상 목록이 둘로 갈라져
     있으면 나중에 서로 안 맞는 문제가 생기기 쉬움.
   - ⚠️ 2026-09(사용자 요청: "서울지역 포함해서 전국 웜업하는 워크플로우로 다시
     만들어줘"): leaderFollower API가 원래 서울을 거부했었는데(당시 사유: "서울은
     이미 다른 지표로 충분히 다뤄지고 있다") 그 제한을 없애서, mode=regionList도
     이제 서울 자치구를 포함해 내려줌 - 이 스크립트는 그 목록을 그대로 순회하므로
     별도 수정 없이 자동으로 서울까지 웜업 대상에 포함됨.
   - leaderFollower API 자체가 24시간 캐시(leader_follower_cache, s-maxage=21600)라
     이미 오늘 계산된 지역은 그냥 캐시를 읽기만 하고 끝남(≈0.4초) - 그래서 매일 돌려도
     실제로 무거운 재계산이 일어나는 지역은 "캐시가 만료됐거나 이번이 처음인" 지역뿐임.
   - Vercel 함수 제한시간(vercel.json: api/data-coverage.js maxDuration=30)에 맞춰
     요청 타임아웃도 30초로 둠 - 그 안에 못 끝나면 실패로 기록하고 다음 지역으로
     넘어감(그 지역은 다음 실행 때 다시 시도됨. 사용자가 먼저 방문해서 트리거해도
     결과는 같음 - autoLoadLeaderFollowerForRegion도 실패를 조용히 무시하도록 돼 있음).
════════════════════════════════════ */
const SITE_URL = (process.env.SITE_URL?.trim()) || 'https://1234auction.vercel.app';
const DELAY_MS = 300; // 호출 사이 간격(서버 부담 방지용 여유 마진) - 계산 자체가 오래 걸리는
                       // 지역이 많아 이 간격이 전체 소요시간에 미치는 영향은 작음.
const TIMEOUT_MS = 30000; // vercel.json의 maxDuration(30초)과 맞춤.

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

async function warmOneRegion(region) {
  const url = `${SITE_URL}/api/data-coverage?mode=leaderFollower&type=apt&region=${encodeURIComponent(region)}`;
  const startedAt = Date.now();
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      console.error(`❌ [${region}] 실패: HTTP ${res.status} (${elapsed}초) ${body && body.error ? '- ' + body.error : ''}`);
      return false;
    }
    const data = await res.json();
    const leaderCount = Array.isArray(data.leaders) ? data.leaders.length : 0;
    console.log(`✅ [${region}] 캐시 완료 (법정동 ${leaderCount}곳, ${elapsed}초)`);
    return true;
  } catch (e) {
    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
    console.error(`❌ [${region}] 오류(${elapsed}초):`, e.message);
    return false;
  }
}

async function main() {
  console.log('🌙 대장/후발주자 캐시 웜업 시작:', new Date().toISOString());
  console.log('SITE_URL:', SITE_URL);

  const targets = await fetchRegionList();
  console.log(`🎯 예열 대상: ${targets.length}개 지역 (전국, 서울 포함)\n`);

  let success = 0, fail = 0;
  for (const region of targets) {
    const ok = await warmOneRegion(region);
    if (ok) success++; else fail++;
    await sleep(DELAY_MS);
  }

  console.log(`\n🌙 웜업 종료: 성공 ${success} / 실패 ${fail} / 전체 ${targets.length}`);
}

main().catch(e => {
  console.error('💥 웜업 스크립트 전체 실패:', e);
  process.exit(1);
});
