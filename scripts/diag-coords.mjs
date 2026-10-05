/* 진단(2026-10, 사용자: "가장 중요한 건 각 자료와 카카오맵·지도 매칭 - 주소 매칭 오류 점검"):
   실거래 단지(house_trades·villa_trades의 고유 단지)마다 저장된 좌표(complex_coords)가
   ① 그 단지 지역(시군구)과 같은 시도·시군구 코드인지(카카오 좌표→법정동코드로 저장해 둔 sigungu_cd 비교)
   ② 같은 동의 다른 단지들 가운데(중앙값)에서 너무 멀리(3km+) 떨어져 있지 않은지
   ③ 서로 다른 지역 단지가 같은 좌표 키를 나눠 쓰는지(키에 시군구가 없어서 생기는 충돌)
   를 셈. 결과는 요약과 예시만 출력(수정은 하지 않음). */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import { LAWD_CODES } from './lawd-codes.mjs';
const supabase = createClient(process.env.SUPABASE_URL.trim(), process.env.SUPABASE_SERVICE_ROLE_KEY.trim(), { auth: { persistSession: false }, realtime: { transport: ws } });
const PAGE = 1000;
const key = (r) => [r.dong || '', r.danji || '', r.bunji || '', r.road_name || '', r.main_num || 0, r.sub_num || ''].join('|').toLowerCase();
const legacy = (r) => [r.dong, r.danji, r.bunji, r.road_name, r.main_num, r.sub_num].join('|').toLowerCase();
const nameToCodes = new Map();
LAWD_CODES.forEach(({ code, name }) => { const k = name.trim(); if (!nameToCodes.has(k)) nameToCodes.set(k, new Set()); nameToCodes.get(k).add(code); });
// 지역명 → 시도 2자리(코드 개편 전후가 섞여 있어 시도는 이름으로 판단)
const SIDO = { '11': '서울', '26': '부산', '27': '대구', '28': '인천', '29': '광주', '30': '대전', '31': '울산', '36': '세종', '41': '경기', '42': '강원', '51': '강원', '43': '충북', '44': '충남', '45': '전북', '52': '전북', '46': '전남', '12': '전남광주', '47': '경북', '48': '경남', '50': '제주' };
const sidoOfName = (n) => { const s = String(n || '').split(' ')[0]; return s.startsWith('전남광주') ? '전남광주' : s.slice(0, 2); };
const sameSido = (regionName, sgg) => {
  const want = sidoOfName(regionName), got = SIDO[String(sgg || '').slice(0, 2)];
  if (!got) return null;
  if (want === got) return true;
  if ((want === '광주' || want === '전남' || want === '전남광주') && (got === '광주' || got === '전남' || got === '전남광주')) return true;
  return false;
};
async function distinct(table) {
  const map = new Map(); let last = 0;
  for (;;) {
    const { data, error } = await supabase.from(table).select('id,region,dong,danji,bunji,road_name,main_num,sub_num').gt('id', last).order('id').limit(PAGE);
    if (error) { console.error(table, error.message); break; }
    if (!data.length) break;
    data.forEach((r) => { const k = key(r); if (!map.has(k)) map.set(k, r); else { const o = map.get(k); if (o.region !== r.region) (o._regions = o._regions || new Set([o.region])).add(r.region); } last = r.id; });
    if (data.length < PAGE) break;
  }
  return map;
}
async function coords() {
  const map = new Map(); let last = 0;
  for (;;) {
    const { data, error } = await supabase.from('complex_coords').select('id,cache_key,lat,lon,sigungu_cd').gt('id', last).order('id').limit(PAGE);
    if (error) { console.error('coords', error.message); break; }
    if (!data.length) break;
    data.forEach((r) => { map.set(r.cache_key, r); last = r.id; });
    if (data.length < PAGE) break;
  }
  return map;
}
const dist = (a, b, c, d) => { const R = 6371000, x = (c - a) * Math.PI / 180, y = (d - b) * Math.PI / 180; const h = Math.sin(x / 2) ** 2 + Math.cos(a * Math.PI / 180) * Math.cos(c * Math.PI / 180) * Math.sin(y / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(h)); };
const med = (a) => { a = a.slice().sort((x, y) => x - y); return a[a.length >> 1]; };


// ── FIX=1: 틀린 좌표를 시도 확인·같은 동 중심 3km 안 조건으로 다시 찾아 고침(못 찾으면 그대로 두고 보고) ──
const KAKAO = (process.env.KAKAO_REST_API_KEY || '').trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function kfetch(url) { const r = await fetch(url, { headers: { Authorization: `KakaoAK ${KAKAO}` } }); if (!r.ok) return null; return r.json(); }
async function kAddr(q) { const j = await kfetch(`https://dapi.kakao.com/v2/local/search/address.json?query=${encodeURIComponent(q)}`); return (j && j.documents || []).map((d) => ({ lat: +d.y, lon: +d.x })); }
async function kKey(q) { const j = await kfetch(`https://dapi.kakao.com/v2/local/search/keyword.json?query=${encodeURIComponent(q)}`); return (j && j.documents || []).slice(0, 5).map((d) => ({ lat: +d.y, lon: +d.x })); }
async function kRegion(lat, lon) { const j = await kfetch(`https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?x=${lon}&y=${lat}`); const b = (j && j.documents || []).find((d) => d.region_type === 'B'); return b && b.code ? { sgg: b.code.slice(0, 5), bj: b.code.slice(5, 10) } : null; }
async function fixFlagged(flagged, cent, type) {
  let fixed = 0, left = 0; const leftEx = [];
  for (const { r, c } of flagged) {
    const ce = cent.get(r.region + '|' + r.dong);
    const qs = [];
    if (r.dong && r.bunji) qs.push(`${r.region} ${r.dong} ${r.bunji}`);
    if (type === 'apt' && r.road_name && r.main_num) qs.push(`${r.region} ${r.road_name} ${r.main_num}${r.sub_num ? '-' + r.sub_num : ''}`);
    if (r.dong && r.danji) qs.push(`${r.region} ${r.dong} ${r.danji}`);
    let got = null;
    for (const q of qs) {
      for (const f of [kAddr, kKey]) {
        const cands = await f(q); await sleep(200);
        for (const p of cands) {
          if (ce && dist(p.lat, p.lon, ce.lat, ce.lon) > 3000) continue;
          const rg = await kRegion(p.lat, p.lon); await sleep(150);
          if (!rg || sameSido(r.region, rg.sgg) === false) continue;
          got = { ...p, ...rg }; break;
        }
        if (got) break;
      }
      if (got) break;
    }
    if (got) {
      const { error } = await supabase.from('complex_coords').update({ lat: got.lat, lon: got.lon, sigungu_cd: got.sgg, bjdong_cd: got.bj }).eq('cache_key', c.cache_key);
      if (!error) fixed++; else { left++; }
    } else { left++; if (leftEx.length < 15) leftEx.push(`${r.region} ${r.dong} ${r.danji} ${r.bunji}`); }
  }
  console.log(`  🔧 고침 ${fixed} · 못 고침 ${left}` + (leftEx.length ? `\n    ` + leftEx.join('\n    ') : ''));
}

const C = await coords();
console.log(`좌표 ${C.size.toLocaleString()}개`);
for (const table of ['house_trades', 'villa_trades']) {
  const D = await distinct(table);
  let have = 0, none = 0, noCode = 0, wrongSido = 0, wrongSgg = 0, far = 0, collide = 0;
  const ex = { wrongSido: [], far: [], collide: [] };
  const byDong = new Map(); const rows = []; const flagged = [];
  for (const [k, r] of D) {
    const c = C.get(k) || C.get(legacy(r));
    if (r._regions) { collide++; if (ex.collide.length < 8) ex.collide.push(`${[...r._regions].join(' / ')} · ${r.dong} ${r.danji} ${r.bunji}`); }
    if (!c || c.lat == null) { none++; continue; }
    have++;
    rows.push({ r, c });
    const dk = r.region + '|' + r.dong; if (!byDong.has(dk)) byDong.set(dk, []); byDong.get(dk).push(c);
    if (!c.sigungu_cd) { noCode++; continue; }
    const s = sameSido(r.region, c.sigungu_cd);
    if (s === false) { wrongSido++; flagged.push({ r, c, why: 'sido' }); if (ex.wrongSido.length < 12) ex.wrongSido.push(`${r.region} ${r.dong} ${r.danji} ${r.bunji} → 좌표 시군구코드 ${c.sigungu_cd}`); continue; }
    const codes = nameToCodes.get(String(r.region || '').trim());
    if (codes && !codes.has(String(c.sigungu_cd))) wrongSgg++;
  }
  const cent = new Map();
  for (const [dk, arr] of byDong) if (arr.length >= 3) cent.set(dk, { lat: med(arr.map((x) => x.lat)), lon: med(arr.map((x) => x.lon)) });
  for (const { r, c } of rows) {
    const ce = cent.get(r.region + '|' + r.dong); if (!ce) continue;
    const d = dist(c.lat, c.lon, ce.lat, ce.lon);
    if (d > 3000) { far++; flagged.push({ r, c, why: 'far', ce }); if (ex.far.length < 12) ex.far.push(`${r.region} ${r.dong} ${r.danji} ${r.bunji} - 같은 동 중심에서 ${(d / 1000).toFixed(1)}km`); }
  }
  console.log(`\n== ${table}: 고유 단지 ${D.size.toLocaleString()}개`);
  console.log(`  좌표 있음 ${have.toLocaleString()} · 없음 ${none.toLocaleString()} · 법정동코드 없음 ${noCode.toLocaleString()}`);
  console.log(`  ❌ 다른 시도에 찍힘 ${wrongSido.toLocaleString()} · ⚠️ 다른 시군구 코드 ${wrongSgg.toLocaleString()}(코드 개편·경계 포함) · ⚠️ 같은 동 중심에서 3km+ ${far.toLocaleString()} · 🔁 다른 지역과 같은 좌표 키 ${collide.toLocaleString()}`);
  for (const [k, v] of Object.entries(ex)) if (v.length) console.log(`  예시(${k}):\n    ` + v.join('\n    '));
  if (process.env.FIX === '1' && KAKAO) await fixFlagged(flagged, cent, table === 'villa_trades' ? 'villa' : 'apt');
}
