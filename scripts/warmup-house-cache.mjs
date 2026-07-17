/* ════════════════════════════════════
   지역(lawdCd)별 /api/get-house 응답 캐시 웜업 스크립트
   - house_trades / villa_trades 에 실제 거래 데이터가 있는 지역만 골라서
     (전국 전체를 다 돌리지 않음 - 데이터 없는 지역까지 예열하는 건 낭비)
     /api/get-house?lawdCd=...&skipRealtime=1 을 호출해 Redis 캐시를 채웁니다.
   - skipRealtime=1 은 국토부 실시간 API(이번달 신고건) 호출을 건너뛰라는 뜻입니다.
     이 실시간 API는 건축HUB 웜업과 같은 PUBLIC_DATA_API_KEY 일일 할당량을
     공유하므로, 새벽 예열에서까지 쓰면 낮 시간 실사용 할당량을 깎아먹게 됩니다.
     (실시간 데이터는 캐시에 저장되지 않고, 실제 방문 시마다 get-house.js가
      항상 새로 불러와 합치므로 예열 시 스킵해도 신선도에는 문제 없습니다.)
   - 이미 처리한 지역이라도 매번 다시 호출합니다 (캐시 TTL이 10시간이라
     하루 한 번 새로 채워주는 게 목적이라 "이어서 처리" 로직은 필요 없음).
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import { LAWD_CODES } from './lawd-codes.mjs';

const supabase = createClient(
  process.env.SUPABASE_URL?.trim(),
  process.env.SUPABASE_SERVICE_ROLE_KEY?.trim(),
  {
    auth: { persistSession: false },
    // Node 20은 네이티브 WebSocket이 없어 Realtime 클라이언트 초기화가 실패함 → ws로 우회
    realtime: { transport: ws },
  }
);

const SITE_URL = (process.env.SITE_URL?.trim()) || 'https://1234auction.vercel.app';
const PAGE_SIZE = 1000;
const DELAY_MS = 500; // 호출 사이 간격 (서버 부담 방지용 여유 마진)

const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ── house_trades / villa_trades에서 실제 존재하는 고유 region 값 전부 뽑기 ── */
async function fetchDistinctRegions(table) {
  const set = new Set();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from(table)
      .select('region')
      .range(from, from + PAGE_SIZE - 1);
    if (error) {
      console.error(`❌ ${table} region 조회 에러:`, error.message);
      break;
    }
    if (!data || data.length === 0) break;
    data.forEach(row => { if (row.region) set.add(row.region.trim()); });
    if (data.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
  }
  return set;
}

async function warmOneRegion(lawdCd, regionName) {
  const url = `${SITE_URL}/api/get-house?lawdCd=${lawdCd}&skipRealtime=1`;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(30000) });
    if (!res.ok) {
      console.error(`❌ [${regionName} / ${lawdCd}] 실패: HTTP ${res.status}`);
      return false;
    }
    const data = await res.json();
    const cnt = Array.isArray(data.apt) ? data.apt.length : 0;
    console.log(`✅ [${regionName} / ${lawdCd}] 캐시 완료 (${cnt}건)`);
    return true;
  } catch (e) {
    console.error(`❌ [${regionName} / ${lawdCd}] 오류:`, e.message);
    return false;
  }
}

async function main() {
  console.log('🌙 get-house 캐시 웜업 시작:', new Date().toISOString());
  console.log('SITE_URL:', SITE_URL);

  const [aptRegions, villaRegions] = await Promise.all([
    fetchDistinctRegions('house_trades'),
    fetchDistinctRegions('villa_trades'),
  ]);
  const allRegions = new Set([...aptRegions, ...villaRegions]);
  console.log(`📍 실거래 데이터가 있는 지역: ${allRegions.size}곳`);

  // region명 → lawdCd 역매핑 (get-house.js가 쓰는 것과 동일한 LAWD_CODES 기준)
  const targets = [];
  const unmatched = [];
  allRegions.forEach(regionName => {
    const info = LAWD_CODES.find(r => r.name === regionName);
    if (info) targets.push({ lawdCd: info.code, regionName });
    else unmatched.push(regionName);
  });

  if (unmatched.length) {
    console.warn(`⚠️  LAWD_CODES에서 매칭되지 않은 지역명 ${unmatched.length}곳 (예열 건너뜀):`, unmatched.slice(0, 10));
  }

  console.log(`🎯 예열 대상: ${targets.length}개 지역\n`);

  let success = 0, fail = 0;
  for (const t of targets) {
    const ok = await warmOneRegion(t.lawdCd, t.regionName);
    if (ok) success++; else fail++;
    await sleep(DELAY_MS);
  }

  console.log(`\n🌙 웜업 종료: 성공 ${success} / 실패 ${fail} / 전체 ${targets.length}`);
}

main().catch(e => {
  console.error('💥 웜업 스크립트 전체 실패:', e);
  process.exit(1);
});
