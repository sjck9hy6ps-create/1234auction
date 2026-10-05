// 진단(2026-10): 무료 한도 점검 - Supabase 테이블별 행 수(추정)와 Upstash Redis 사용량
const U = process.env.SUPABASE_URL.replace(/\/$/, ''), K = process.env.SUPABASE_SERVICE_ROLE_KEY;
const tables = ['house_trades', 'villa_trades', 'single_trades', 'house_rent', 'villa_rent', 'building_info', 'complex_coords', 'leader_follower_cache', 'kapt_complex_info', 'presale_trades'];
for (const t of tables) {
  try {
    const r = await fetch(`${U}/rest/v1/${t}?select=*&limit=1`, { method: 'HEAD', headers: { apikey: K, Authorization: `Bearer ${K}`, Prefer: 'count=estimated' } });
    console.log(t, r.status, r.headers.get('content-range'));
  } catch (e) { console.log(t, 'err', e.message); }
}
const RU = process.env.UPSTASH_REDIS_REST_URL, RT = process.env.UPSTASH_REDIS_REST_TOKEN;
if (RU && RT) {
  for (const c of [['DBSIZE'], ['INFO', 'memory']]) {
    const r = await fetch(RU, { method: 'POST', headers: { Authorization: `Bearer ${RT}` }, body: JSON.stringify(c) }).then((x) => x.json()).catch((e) => ({ error: e.message }));
    console.log(c.join(' '), JSON.stringify(r).slice(0, 400));
  }
} else console.log('Redis 비밀값 없음(건너뜀)');
