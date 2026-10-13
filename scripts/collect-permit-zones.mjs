/* 토지거래허가구역 판정 수집(2026-10-13, 사용자: 허가구역을 앱에 적용하고 3개월에 한 번은 새로 갱신).
   등록한 경매물건 좌표가 VWorld 'LT_C_UQ141(토지거래계약에관한허가구역)' 안에 있는지 점으로 조회(앱 서버 프록시 경유 - GitHub에서 VWorld 직접 호출은 502로 막힘).
   - 전체 갱신(FULL): 이전 전체 갱신이 90일을 넘었거나 처음이거나 FORCE_FULL=1 → 모든 물건을 다시 조회(정부가 수시로 지정·해제하므로)
   - 증분: 그 외엔 아직 조회 안 한 새 물건만 조회
   결과: leader_follower_cache 'signal|__permit__' { refreshedAt(마지막 전체 갱신), checkedAt, n, checked:[id...], flagged:{id:[구역명, 지정연도, 번호, 시군구]} }
   법적 의미(2026-10 확인): 경매 낙찰은 허가·실거주 의무 대상이 아님. 다만 낙찰 후 되팔 때는 매수인이 허가를 받아야 하고 주거용은 2년 실거주(임대·갭투자 불가) → 매수자가 줄어 환금성 주의. */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const SECRET = (process.env.COLLECT_PROXY_SECRET || '').trim();
const supabase = createClient(process.env.SUPABASE_URL?.trim(), process.env.SUPABASE_SERVICE_ROLE_KEY?.trim(), { auth: { persistSession: false }, realtime: { transport: ws } });
const FULL_DAYS = 90, ROW = 'signal|__permit__';
if (!SECRET) { console.error('COLLECT_PROXY_SECRET 없음'); process.exit(1); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const { data: prevRow } = await supabase.from('leader_follower_cache').select('payload').eq('id', ROW).maybeSingle();
const prev = prevRow && prevRow.payload && prevRow.payload.refreshedAt ? prevRow.payload : null;
const ageDays = prev ? (Date.now() - new Date(prev.refreshedAt).getTime()) / 86400000 : 9999;
const full = !prev || ageDays >= FULL_DAYS || process.env.FORCE_FULL === '1';
console.log(full ? `전체 갱신(이전 갱신 ${prev ? Math.round(ageDays) + '일 전' : '없음'})` : `증분(이전 전체 갱신 ${Math.round(ageDays)}일 전)`);

const auctions = await fetch(`${SITE}/api/auction`).then((r) => r.json());
const items = (Array.isArray(auctions) ? auctions : []).filter((a) => a && !a.isBacktest && a.id != null && Number(a.lat) && Number(a.lon));
const checkedSet = new Set(full ? [] : (prev.checked || []));
const todo = items.filter((a) => !checkedSet.has(String(a.id)));
console.log(`경매물건 ${items.length}건 중 조회 대상 ${todo.length}건`);

async function zoneAt(lat, lon) {
  for (let t = 0; t < 3; t++) {
    try {
      const q = new URLSearchParams({ action: 'vworldProxy', secret: SECRET, kind: 'data', service: 'data', request: 'GetFeature', data: 'LT_C_UQ141', format: 'json', size: '5',
        geomFilter: `POINT(${lon} ${lat})`, geometry: 'false', attribute: 'true', crs: 'EPSG:4326' });
      const r = await fetch(`${SITE}/api/get-house?${q}`, { signal: AbortSignal.timeout(60000) }).then((x) => x.json());
      const j = JSON.parse(r.body || '{}'); const st = j.response && j.response.status;
      if (st === 'NOT_FOUND') return { ok: true, z: null };
      if (st !== 'OK') { await sleep(1500 * (t + 1)); continue; }
      const f = ((((j.response || {}).result || {}).featureCollection || {}).features || [])[0];
      const p = (f && f.properties) || {};
      return { ok: true, z: [p.uname || '토지거래허가구역', p.dyear || '', p.dnum || '', [p.sido_name, p.sigg_name].filter(Boolean).join(' ')] };
    } catch (e) { await sleep(1500 * (t + 1)); }
  }
  return { ok: false };
}
const flagged = full ? {} : { ...(prev.flagged || {}) };
const checked = new Set(checkedSet); let fail = 0, idx = 0;
async function worker() {
  while (idx < todo.length) {
    const a = todo[idx++];
    const r = await zoneAt(Number(a.lat), Number(a.lon));
    if (!r.ok) { fail++; continue; }
    checked.add(String(a.id)); if (r.z) flagged[String(a.id)] = r.z; else delete flagged[String(a.id)];
    if (idx % 500 === 0) console.log(`  진행 ${idx}/${todo.length}`);
  }
}
await Promise.all(Array.from({ length: 6 }, worker));
if (todo.length && fail > todo.length * 0.2) { console.error(`조회 실패가 너무 많아(${fail}/${todo.length}) 저장하지 않음`); process.exit(1); }
const nowIso = new Date().toISOString();
const payload = { refreshedAt: full ? nowIso : prev.refreshedAt, checkedAt: nowIso, n: checked.size, checked: [...checked], flagged, layer: 'LT_C_UQ141' };
const { error } = await supabase.from('leader_follower_cache').upsert({ id: ROW, payload, fetched_at: nowIso }, { onConflict: 'id' });
if (error) { console.error('저장 실패:', error.message); process.exit(1); }
console.log(`✅ 허가구역 판정 저장: 조회 ${todo.length}건(실패 ${fail}) · 허가구역 안 ${Object.keys(flagged).length}건 / 전체 ${checked.size}건 · 전체 갱신 ${payload.refreshedAt.slice(0, 10)}`);
