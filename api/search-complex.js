import { createClient } from '@supabase/supabase-js';
import { LAWD_CODES } from '../scripts/lawd-codes.mjs';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

function normalizeSearchStr(s) {
  return (s || '').replace(/\s/g, '').toLowerCase();
}

/* ════════════════════════════════════
   반경 검색 모드 (?mode=radius) - 경매물건 예상전세가 계산용
   - 특정 좌표 반경 안의 연립다세대 순수 전세 거래를 찾아서 돌려줌
   - 새 api 파일을 만들지 않고 기존 search-complex.js에 얹음 (Vercel Hobby
     12개 함수 한도 때문에 새 api/*.js 파일은 만들지 않기로 한 규칙)
   - complex_coords(웜업 스크립트가 전국 단지 좌표를 미리 채워둔 테이블)에서
     반경 안의 단지를 먼저 찾고, 그 단지들의 dong/danji(또는 dong/bunji)로
     villa_rent를 매칭해서 실제 전세 거래를 가져오는 2단계 방식.
════════════════════════════════════ */
function toRad(deg) { return (deg * Math.PI) / 180; }
function haversineMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
function m2ToPyung(m2) { return (m2 || 0) / 3.305785; }

async function handleRadiusSearch(req, res) {
  const lat = parseFloat(req.query.lat);
  const lon = parseFloat(req.query.lon);
  const radius = parseFloat(req.query.radius) || 1000;
  const pyung = parseFloat(req.query.pyung) || null; // 목표 평형, ±4평 이내만
  const buildYear = parseInt(req.query.buildYear, 10) || null; // 목표 준공연도, 있을 때만 ±4년 필터

  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return res.status(400).json({ error: 'lat/lon이 필요합니다.', results: [] });
  }

  const latDelta = radius / 111000;
  const lonDelta = radius / (111000 * Math.cos((lat * Math.PI) / 180));

  try {
    // ── 1. 반경 안의 단지 좌표 후보 (bbox로 넉넉히 가져온 뒤 실제 거리로 다시 거름) ──
    const { data: coordRows, error: coordErr } = await supabase
      .from('complex_coords')
      .select('cache_key,lat,lon,sigungu_cd')
      .gte('lat', lat - latDelta).lte('lat', lat + latDelta)
      .gte('lon', lon - lonDelta).lte('lon', lon + lonDelta)
      .limit(2000);
    if (coordErr) throw coordErr;

    // cache_key 형식: dong|danji|bunji|road_name|main_num|sub_num (warmup-locations.mjs의 buildCacheKey와 동일)
    const nearby = (coordRows || [])
      .map((r) => {
        const dist = haversineMeters(lat, lon, r.lat, r.lon);
        if (dist > radius) return null;
        const parts = String(r.cache_key).split('|');
        if (parts.length < 6) return null;
        return { dong: parts[0], danji: parts[1], bunji: parts[2], sigunguCd: r.sigungu_cd, dist: Math.round(dist) };
      })
      .filter(Boolean);
    if (!nearby.length) return res.status(200).json({ results: [] });

    // ── 2. sigungu_cd(법정동코드 앞5자리) → villa_rent.region 텍스트 매칭 ──
    const regionNames = [...new Set(nearby.map((n) => n.sigunguCd).filter(Boolean))]
      .map((code) => (LAWD_CODES.find((r) => r.code === code) || {}).name)
      .filter(Boolean);
    if (!regionNames.length) return res.status(200).json({ results: [] });

    // 같은 dong+danji 조합의 최소거리를 기록해뒀다가, 결과 행에 "몇 m 거리인지" 붙여줌
    const distByDanjiKey = new Map();
    const distByBunjiKey = new Map();
    nearby.forEach((n) => {
      const dk = (n.dong + '|' + n.danji).toLowerCase();
      const bk = (n.dong + '|' + n.bunji).toLowerCase();
      if (!distByDanjiKey.has(dk) || distByDanjiKey.get(dk) > n.dist) distByDanjiKey.set(dk, n.dist);
      if (!distByBunjiKey.has(bk) || distByBunjiKey.get(bk) > n.dist) distByBunjiKey.set(bk, n.dist);
    });

    const { data: rentRows, error: rentErr } = await supabase
      .from('villa_rent')
      .select('region,dong,danji,bunji,road_name,size,deposit,monthly_rent,floor,build_year,deal_date')
      .in('region', regionNames)
      .limit(20000);
    if (rentErr) throw rentErr;

    const results = (rentRows || [])
      .filter((row) => {
        if (row.monthly_rent > 0) return false; // 순수 전세만 (보증부 월세 제외)
        const dk = (row.dong + '|' + (row.danji || '')).toLowerCase();
        const bk = (row.dong + '|' + (row.bunji || '')).toLowerCase();
        if (!distByDanjiKey.has(dk) && !distByBunjiKey.has(bk)) return false;
        if (pyung) {
          if (!row.size) return false;
          if (Math.abs(m2ToPyung(row.size) - pyung) > 4) return false;
        }
        if (buildYear) {
          if (!row.build_year) return false;
          if (Math.abs(buildYear - row.build_year) > 4) return false;
        }
        return true;
      })
      .map((row) => {
        const dk = (row.dong + '|' + (row.danji || '')).toLowerCase();
        const bk = (row.dong + '|' + (row.bunji || '')).toLowerCase();
        const dist = distByDanjiKey.has(dk) ? distByDanjiKey.get(dk) : distByBunjiKey.get(bk);
        return {
          region: row.region, dong: row.dong, danji: row.danji, bunji: row.bunji, road_name: row.road_name,
          size: row.size, deposit: row.deposit, floor: row.floor, build_year: row.build_year,
          deal_date: row.deal_date, dist: dist != null ? dist : null,
        };
      })
      .sort((a, b) => (a.dist || 0) - (b.dist || 0))
      .slice(0, 200);

    return res.status(200).json({ results });
  } catch (err) {
    console.error('search-complex 반경검색 에러:', err.message);
    return res.status(500).json({ error: err.message, results: [] });
  }
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');

  if (req.query.mode === 'radius') {
    return handleRadiusSearch(req, res);
  }

  const q = (req.query.q || '').trim();
  if (!q || q.length < 2) return res.status(200).json({ results: [] });

  try {
    // danji/dong/bunji 중 하나라도 부분일치하면 후보로 넉넉히 가져온 뒤,
    // 공백 무시 부분일치로 다시 한번 정확히 걸러냅니다.
    const [aptResult, villaResult] = await Promise.all([
      supabase
        .from('house_trades')
        .select('region,dong,danji,bunji,road_name,main_num,sub_num,deal_date')
        .or(`danji.ilike.%${q}%,dong.ilike.%${q}%,bunji.ilike.%${q}%`)
        .order('deal_date', { ascending: false })
        .limit(500),
      supabase
        .from('villa_trades')
        .select('region,dong,danji,bunji,road_name,main_num,sub_num,deal_date')
        .or(`danji.ilike.%${q}%,dong.ilike.%${q}%,bunji.ilike.%${q}%`)
        .order('deal_date', { ascending: false })
        .limit(500),
    ]);

    if (aptResult.error) {
      console.error('house_trades 검색 에러:', aptResult.error.message);
      throw aptResult.error;
    }
    if (villaResult.error) {
      console.error('villa_trades 검색 에러:', villaResult.error.message);
    }

    const qNorm = normalizeSearchStr(q);
    const rows = [
      ...(aptResult.data || []).map(r => ({ ...r, buildingType: 'apt' })),
      ...(villaResult.error ? [] : (villaResult.data || []).map(r => ({ ...r, buildingType: 'villa' }))),
    ];

    const filtered = rows.filter(row => {
      const danjiNorm     = normalizeSearchStr(row.danji);
      const dongBunjiNorm = normalizeSearchStr((row.dong || '') + (row.bunji || ''));
      return danjiNorm.includes(qNorm) || dongBunjiNorm.includes(qNorm);
    });

    // 단지 단위로 중복 제거 (같은 danji+dong+region 조합은 최신 거래 1건만 대표로)
    const groupMap = new Map();
    filtered.forEach(row => {
      const key = `${row.buildingType}|${row.region}|${row.dong}|${row.danji || ''}|${row.bunji || ''}`;
      const existing = groupMap.get(key);
      if (!existing || String(row.deal_date) > String(existing.deal_date)) {
        groupMap.set(key, row);
      }
    });

    const results = Array.from(groupMap.values())
      .sort((a, b) => normalizeSearchStr(a.danji || '').length - normalizeSearchStr(b.danji || '').length)
      .slice(0, 30)
      .map(row => ({
        buildingType: row.buildingType,
        region: row.region,
        dong: row.dong,
        danji: row.danji,
        bunji: row.bunji,
        road_name: row.road_name,
        main_num: row.main_num,
        sub_num: row.sub_num,
      }));

    return res.status(200).json({ results });
  } catch (err) {
    console.error('search-complex 에러:', err.message);
    return res.status(500).json({ error: err.message, results: [] });
  }
}
