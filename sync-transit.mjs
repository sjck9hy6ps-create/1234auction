/* ════════════════════════════════════
   역세권(지하철역 접근성) 동기화 스크립트 - 2026-08 추가 (역세권/학군 연동 1단계)
   - complex_coords(warmup-locations.mjs가 이미 채워둔 단지별 위경도 캐시)에 있는
     단지 중, 아직 transit_features에 없는 것만 카카오 REST "카테고리로 장소 검색"
     (category_group_code=SW8, 지하철역)으로 반경 내 최단거리 지하철역을 찾아 저장.
   - 새 API 키 불필요: 기존 KAKAO_REST_API_KEY(웜업 스크립트와 동일 키)를 그대로 씀.
   - complex_coords가 좌표를 못 채운 단지는 여기서도 자연히 대상에서 빠짐(좌표 없이는
     지하철역 거리도 계산 불가) → complex_coords 웜업이 먼저 돌아야 이 스크립트도 의미가 있음.
   - 카카오 API 일일 할당량 소진 감지/중단 로직은 warmup-locations.mjs와 동일하게 이식.
   ⚠️ 2026-08(실배포 발견, 우선순위 수정): complex_coords는 house_trades(아파트)+
   villa_trades(연립다세대) 단지를 합쳐 약 20만 개인데, 당시 train-avm.py는 역세권
   피처를 house_trades(아파트)에만 썼음. 첫 배포 때 구분 없이 처리했더니 실행당 상한
   3000개 중 상당수가 지금 당장은 안 쓰이는 연립다세대 단지에 소모되는 걸 실제 로그로
   확인함(197,745개 중 3,000개 처리해도 실제 쓰이는 아파트 커버리지는 그만큼 못 늘어남
   - 무작위 순서라 섞여서 처리됨). 그래서 house_trades 단지를 최우선 처리하도록 순서를
   바꿨었음.
   ⚠️ 2026-08(2차 수정, 빌라 AVM 오차범위 개선 - 사용자 피드백): train-avm.py가 이제
   villa_v1도 attach_transit=True로 역세권을 씀(빌라 홀드아웃 오차 ±36.1%가 아파트
   ±10%보다 훨씬 컸던 원인 중 하나를 줄이기 위함). "아파트 먼저 전부, 그다음 나머지"
   순서를 그대로 두면 아파트 커버리지가 이미 상당히 올라간 지금은 예산이 계속 아파트
   쪽에만 쓰이고 빌라는 영영 뒤로 밀림 - 실행당 예산을 아파트/빌라 절반씩 배정하되, 한쪽
   대상이 그 절반보다 적으면 남는 예산을 반대쪽에서 마저 채우는 방식으로 바꿈(아래
   targets 구성부 참고).
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';

const supabase = createClient(
  process.env.SUPABASE_URL?.trim(),
  process.env.SUPABASE_SERVICE_ROLE_KEY?.trim(),
  { auth: { persistSession: false }, realtime: { transport: ws } }
);
const KAKAO_REST_KEY = process.env.KAKAO_REST_API_KEY?.trim();
const DELAY_MS = 250;
const CONCURRENCY = 3;
const PAGE_SIZE = 1000;
const SEARCH_RADIUS_M = 2000; // 이 반경 밖이면 "역세권 아님"으로 간주(먼 거리 취급)
// 실행당 처리 상한 - 건축물대장 웜업과 같은 KAKAO_REST_API_KEY(앱 단위 할당량)를
// 공유하므로, 이 스크립트가 하루치를 혼자 다 쓰지 않도록 여유 있게 상한을 둠.
const MAX_PER_RUN = parseInt(process.env.MAX_TRANSIT_PER_RUN || '3000', 10);

const sleep = ms => new Promise(r => setTimeout(r, ms));

let consecutive429 = 0;
const MAX_CONSECUTIVE_429 = 5;
let quotaExhausted = false;
async function kakaoFetch(url) {
  if (quotaExhausted) return null;
  let res;
  try {
    res = await fetch(url, { headers: { Authorization: `KakaoAK ${KAKAO_REST_KEY}` } });
  } catch (e) {
    console.error('❌ 카카오 API 네트워크 오류:', e.message);
    return null;
  }
  if (res.status === 429) {
    consecutive429++;
    if (consecutive429 >= MAX_CONSECUTIVE_429 && !quotaExhausted) stopForQuota('호출 제한(429)이 계속 걸림');
    return null;
  }
  if (res.status === 400) {
    let body = null;
    try { body = await res.json(); } catch (e) { /* ignore */ }
    if (body && (body.code === -10 || /API limit has been exceeded/i.test(body.message || ''))) {
      stopForQuota('일일 호출 할당량 초과 (code -10)');
      return null;
    }
    return null;
  }
  consecutive429 = 0;
  if (!res.ok) return null;
  try { return await res.json(); } catch (e) { return null; }
}
function stopForQuota(reason) {
  if (quotaExhausted) return;
  quotaExhausted = true;
  console.error(`\n🛑 ${reason} → 여기서 중단합니다. (다음 실행 때 이어서 처리됩니다)\n`);
}
/* ── 카카오 REST 카테고리 검색: 반경 내 지하철역 중 최단거리 ── */
async function nearestSubway(lat, lon) {
  const url = `https://dapi.kakao.com/v2/local/search/category.json?category_group_code=SW8`
    + `&x=${lon}&y=${lat}&radius=${SEARCH_RADIUS_M}&sort=distance&size=1`;
  const json = await kakaoFetch(url);
  const doc = json?.documents?.[0];
  if (!doc) return null; // 반경 내 지하철역 없음(멀다는 뜻 - null로 저장해 구분)
  // doc.x=경도, doc.y=위도 (카카오 로컬 API 좌표계 - 도보 길찾기 링크 생성에 필요)
  return {
    distM: parseFloat(doc.distance),
    stationName: doc.place_name,
    stationLat: doc.y != null ? parseFloat(doc.y) : null,
    stationLon: doc.x != null ? parseFloat(doc.x) : null,
  };
}
/* warmup-locations.mjs의 buildCacheKey()와 반드시 동일해야 함 */
function buildCacheKey(dong, danji, bunji, roadName, mainNum, subNum) {
  return [dong, danji, bunji, roadName, mainNum, subNum].join('|').toLowerCase();
}
/* house_trades(아파트) 단지의 cache_key만 뽑음 - 지금 역세권 피처를 실제로 쓰는 대상이라
   우선순위를 여기 먼저 둠(모듈 상단 설명 참고). */
async function fetchAptCacheKeys() {
  const set = new Set();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from('house_trades')
      .select('dong,danji,bunji,road_name,main_num,sub_num')
      .range(from, from + PAGE_SIZE - 1);
    if (error) { console.error('❌ house_trades 조회 에러:', error.message); break; }
    if (!data || data.length === 0) break;
    data.forEach(r => set.add(buildCacheKey(r.dong, r.danji, r.bunji, r.road_name, r.main_num, r.sub_num)));
    if (data.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
  }
  return set;
}
async function fetchAllCoords() {
  const map = new Map();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from('complex_coords')
      .select('cache_key,lat,lon')
      .range(from, from + PAGE_SIZE - 1);
    if (error) { console.error('❌ complex_coords 조회 에러:', error.message); break; }
    if (!data || data.length === 0) break;
    data.forEach(r => { if (r.lat != null && r.lon != null) map.set(r.cache_key, { lat: r.lat, lon: r.lon }); });
    if (data.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
  }
  return map;
}
async function fetchExistingTransit() {
  const set = new Set();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from('transit_features')
      .select('cache_key')
      .range(from, from + PAGE_SIZE - 1);
    if (error) { console.error('❌ transit_features 조회 에러:', error.message); break; }
    if (!data || data.length === 0) break;
    data.forEach(r => set.add(r.cache_key));
    if (data.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
  }
  return set;
}
async function saveTransit(cacheKey, distM, stationName, stationLat, stationLon) {
  const { error } = await supabase.from('transit_features').upsert({
    cache_key: cacheKey, dist_subway_m: distM, nearest_station: stationName || null,
    station_lat: stationLat != null ? stationLat : null,
    station_lon: stationLon != null ? stationLon : null,
  }, { onConflict: 'cache_key' });
  if (error) console.error('❌ transit_features 저장 에러:', error.message);
}
async function processQueue(items, worker, concurrency) {
  let idx = 0, done = 0;
  const total = items.length;
  async function runOne() {
    while (idx < items.length) {
      if (quotaExhausted) return;
      const item = items[idx++];
      await worker(item);
      done++;
      if (done % 200 === 0 || done === total) console.log(`   진행: ${done}/${total}`);
    }
  }
  await Promise.all(Array.from({ length: concurrency }, runOne));
}
async function main() {
  if (!KAKAO_REST_KEY) {
    console.error('❌ KAKAO_REST_API_KEY 환경변수가 없습니다.');
    process.exit(1);
  }
  console.log('📦 complex_coords 좌표 목록 불러오는 중...');
  const coords = await fetchAllCoords();
  console.log(`   → 좌표 있는 단지 ${coords.size}개`);
  console.log('📦 이미 처리된 transit_features 목록 불러오는 중...');
  const existing = await fetchExistingTransit();
  console.log(`   → 이미 처리됨 ${existing.size}개`);
  console.log('📦 house_trades(아파트) 단지 목록 불러오는 중(우선순위용)...');
  const aptKeys = await fetchAptCacheKeys();
  console.log(`   → 아파트 단지 ${aptKeys.size}개`);
  const remaining = [...coords.entries()].filter(([key]) => !existing.has(key));
  // ⚠️ 2026-08(2차 수정): villa_v1도 이제 역세권을 쓰므로 아파트 100% 우선이 아니라 절반씩
  // 예산을 배정함 - 한쪽이 배정량보다 적으면 남는 예산을 반대쪽에서 마저 채워 예산을
  // 낭비하지 않음(예: 아파트 미처리분이 절반 예산보다 적으면 남는 만큼 빌라를 더 처리).
  const aptTargets = remaining.filter(([key]) => aptKeys.has(key));
  const otherTargets = remaining.filter(([key]) => !aptKeys.has(key));
  const aptBudget = Math.floor(MAX_PER_RUN / 2);
  const otherBudget = MAX_PER_RUN - aptBudget;
  const aptSlice = aptTargets.slice(0, aptBudget);
  const otherSlice = otherTargets.slice(0, otherBudget);
  let targets = [...aptSlice, ...otherSlice];
  const leftover = MAX_PER_RUN - targets.length;
  if (leftover > 0) {
    if (aptSlice.length < aptTargets.length) {
      targets = targets.concat(aptTargets.slice(aptSlice.length, aptSlice.length + leftover));
    } else if (otherSlice.length < otherTargets.length) {
      targets = targets.concat(otherTargets.slice(otherSlice.length, otherSlice.length + leftover));
    }
  }
  const aptInTargets = targets.filter(([key]) => aptKeys.has(key)).length;
  console.log(`📦 미처리 아파트 단지 ${aptTargets.length}개 / 기타(연립다세대 등) ${otherTargets.length}개`);
  console.log(`📦 이번 실행 처리 대상: ${targets.length}개 (아파트 ${aptInTargets}개 / 기타 ${targets.length - aptInTargets}개, 절반씩 예산배정 후 남는 예산은 반대쪽에서 채움, 실행당 상한 ${MAX_PER_RUN}개)\n`);
  let success = 0, none = 0, fail = 0;
  await processQueue(targets, async ([cacheKey, coord]) => {
    const result = await nearestSubway(coord.lat, coord.lon);
    await sleep(DELAY_MS);
    if (quotaExhausted) return;
    if (result) {
      await saveTransit(cacheKey, result.distM, result.stationName, result.stationLat, result.stationLon);
      success++;
    } else {
      // 반경 내 역이 없다는 것도 유의미한 결과 - null로 저장해서 "먼 거리"로 구분
      await saveTransit(cacheKey, null, null, null, null);
      none++;
    }
  }, CONCURRENCY);
  if (quotaExhausted) {
    console.log(`\n⏸️  할당량 소진으로 중단. 성공(역 발견) ${success}건 / 역없음(반경밖) ${none}건 / 실패 ${fail}건`);
  } else {
    console.log(`\n🎉 완료! 역 발견 ${success}건 / 반경 밖(${SEARCH_RADIUS_M}m) ${none}건 / 실패 ${fail}건`);
    console.log(`   남은 미처리: ${coords.size - existing.size - targets.length}개 (다음 실행에서 이어서 처리)`);
  }
}
main().catch(e => { console.error('❌ 치명적 오류:', e); process.exit(1); });
