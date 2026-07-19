import { createClient } from '@supabase/supabase-js';
import { LAWD_CODES } from '../scripts/lawd-codes.mjs';
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);
const APT_API_KEY = process.env.PUBLIC_DATA_API_KEY;

// ════════════════════════════════════
// 지역(lawdCd) 단위 응답 캐시 (Upstash Redis)
// - 캐시에는 "국토부 DB 배치 수집분(house_trades/villa_trades/전세)"만 저장합니다.
//   이번달 실시간 신고건(국토부 실시간 API)은 캐시에 절대 포함하지 않고,
//   실제 사용자가 화면을 조회할 때마다 매번 새로 불러와서 캐시된 DB분과 합쳐서 응답합니다.
//   → 새벽 웜업이 이 캐시를 미리 채워둬도, 실제 방문 시엔 항상 최신 실시간 신고건이 반영됩니다.
// - ?skipRealtime=1 로 호출하면(새벽 웜업 전용) 실시간 API 호출 자체를 생략하고
//   DB분만 조회해서 캐시에 채워 넣습니다. 실시간 API가 건축HUB 웜업과 같은 일일 할당량을
//   쓰는 키라서, 웜업 때는 이 할당량을 쓰지 않기 위함입니다.
// ════════════════════════════════════
const REDIS_URL = process.env.UPSTASH_REDIS_URL;
const REDIS_TOKEN = process.env.UPSTASH_REDIS_TOKEN;
const CACHE_TTL_SECONDS = 10 * 60 * 60; // 10시간

async function getCachedHouseData(lawdCd) {
  if (!REDIS_URL || !REDIS_TOKEN) return null;
  try {
    const r = await fetch(`${REDIS_URL}/get/house_${lawdCd}`, {
      headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) return null;
    const data = await r.json();
    if (!data || !data.result) return null;
    const parsed = JSON.parse(data.result);
    if (!parsed || !Array.isArray(parsed.apt)) return null;
    return parsed;
  } catch (e) {
    console.error('get-house Redis 캐시 조회 실패:', e.message);
    return null;
  }
}

async function setCachedHouseData(lawdCd, payload) {
  if (!REDIS_URL || !REDIS_TOKEN) return;
  try {
    const r = await fetch(`${REDIS_URL}/set/house_${lawdCd}?EX=${CACHE_TTL_SECONDS}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${REDIS_TOKEN}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) {
      const errText = await r.text();
      console.error('get-house Redis 캐시 저장 실패:', errText);
    }
  } catch (e) {
    console.error('get-house Redis 캐시 저장 실패:', e.message);
  }
}

// ── 캐시 전체 비우기 (CSV 대량 업로드 후 backup.html의 "지도 캐시 전체 삭제" 버튼용) ──
// Upstash REST는 GET/SET처럼 자주 쓰는 명령은 /get/{key}, /set/{key} 같은 단축 경로를 제공하지만,
// KEYS처럼 흔치 않은 명령은 기본 URL에 명령 배열을 그대로 POST하는 범용 방식으로 호출해야 함.
async function redisCommand(cmdArray) {
  const r = await fetch(REDIS_URL, {
    method: 'POST',
    headers: { Authorization: `Bearer ${REDIS_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(cmdArray),
    signal: AbortSignal.timeout(8000),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || 'Redis 명령 실패');
  return data.result;
}
async function clearHouseCache() {
  if (!REDIS_URL || !REDIS_TOKEN) throw new Error('UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN 환경변수가 없습니다.');
  const keys = await redisCommand(['KEYS', 'house_*']);
  if (!Array.isArray(keys) || !keys.length) return { cleared: 0 };
  // 여러 키를 한 번에 지우기 - pipeline 엔드포인트로 DEL 명령을 묶어서 보냄
  const pipelineBody = keys.map((k) => ['DEL', k]);
  const r = await fetch(`${REDIS_URL}/pipeline`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${REDIS_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(pipelineBody),
    signal: AbortSignal.timeout(8000),
  });
  if (!r.ok) {
    const errText = await r.text();
    throw new Error('캐시 삭제 실패: ' + errText);
  }
  return { cleared: keys.length };
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.setHeader('Pragma', 'no-cache');

  // CSV 대량 업로드 후 backup.html에서 이 액션으로 지역별 캐시를 통째로 비움
  // (평소 지도 조회 흐름과 무관한 관리용 액션이라 lawdCd 없이도 처리)
  if (req.query.action === 'clearCache') {
    try {
      const result = await clearHouseCache();
      return res.status(200).json(result);
    } catch (e) {
      return res.status(500).json({ error: e.message });
    }
  }

  const lawdCd = req.query.lawdCd;
  if (!lawdCd) return res.status(400).json({ error: 'lawdCd required' });

  // 새벽 자동 예열 요청만 이 플래그를 붙여서 호출합니다 (실시간 API 할당량 절약용)
  const skipRealtime = req.query.skipRealtime === '1' || req.query.skipRealtime === 'true';

  // house_trades / villa_trades 모두 lawd_cd 컬럼이 없고 region 텍스트로 저장되어 있어
  // LAWD_CODES로 lawdCd → 지역명 변환이 필요합니다.
  const regionInfo = LAWD_CODES.find(r => r.code === lawdCd);
  const regionName = regionInfo ? regionInfo.name : '';

  console.log('lawdCd:', lawdCd, '/ regionName:', regionName || '(매칭 실패)', '/ skipRealtime:', skipRealtime);

  try {
    // ── 1. DB 배치 수집분(apt/villa/전세)은 캐시가 있으면 그대로 재사용 ──
    let dbPayload = null;
    if (!skipRealtime) {
      dbPayload = await getCachedHouseData(lawdCd);
      if (dbPayload) console.log('get-house DB캐시 히트:', lawdCd);
    }

    if (!dbPayload) {
      // ── 아파트 DB / 연립다세대 DB / 전세 DB, 세 요청을 동시에 실행 ──
      let aptQuery       = Promise.resolve({ data: [], error: null });
      let villaQuery     = Promise.resolve({ data: [], error: null });
      let aptRentQuery   = Promise.resolve({ data: [], error: null });
      let villaRentQuery = Promise.resolve({ data: [], error: null });

      if (regionName) {
        aptQuery = supabase
          .from('house_trades')
          .select('*')
          .eq('region', regionName)
          .order('deal_date', { ascending: false });

        villaQuery = supabase
          .from('villa_trades')
          .select('*')
          .eq('region', regionName)
          .order('deal_date', { ascending: false });
        // 단독/다가구(single_trades)는 지도에 표시하지 않기로 했으므로 조회하지 않음

        // 전세가(house_rent/villa_rent) - 전세가 기반 시세추정(연립다세대) 등에 사용
        aptRentQuery = supabase
          .from('house_rent')
          .select('*')
          .eq('region', regionName)
          .order('deal_date', { ascending: false });

        villaRentQuery = supabase
          .from('villa_rent')
          .select('*')
          .eq('region', regionName)
          .order('deal_date', { ascending: false });
      } else {
        console.warn('LAWD_CODES에서 lawdCd(' + lawdCd + ')에 매칭되는 지역명을 찾지 못해 DB 조회를 건너뜁니다.');
      }

      const [aptResult, villaResult, aptRentResult, villaRentResult] = await Promise.all([
        aptQuery,
        villaQuery,
        aptRentQuery,
        villaRentQuery,
      ]);

      if (aptResult.error) {
        console.error('house_trades 조회 에러:', aptResult.error.message);
        throw aptResult.error;
      }
      const aptData = aptResult.data || [];
      console.log('아파트 조회 완료. 건수:', aptData.length);

      let villaData = [];
      if (villaResult.error) {
        console.error('villa_trades 조회 에러:', villaResult.error.message);
      } else {
        villaData = villaResult.data || [];
        console.log('연립다세대 조회 완료. 건수:', villaData.length);
      }

      let aptRentData = [];
      if (aptRentResult.error) {
        console.error('house_rent 조회 에러:', aptRentResult.error.message);
      } else {
        aptRentData = aptRentResult.data || [];
      }

      let villaRentData = [];
      if (villaRentResult.error) {
        console.error('villa_rent 조회 에러:', villaRentResult.error.message);
      } else {
        villaRentData = villaRentResult.data || [];
      }
      console.log('전세가 조회 완료. 아파트=' + aptRentData.length + '건 연립다세대=' + villaRentData.length + '건');

      // ── 정규화 ──
      const aptNormalized      = aptData.map(row => normalizeRow(row, 'apt'));
      const villaNormalized    = villaData.map(row => normalizeRow(row, 'villa'));
      const aptRentNormalized   = aptRentData.map(row => normalizeRentRow(row, 'apt'));
      const villaRentNormalized = villaRentData.map(row => normalizeRentRow(row, 'villa'));

      // ── 합치기 + 중복 제거 (DB 배치 수집분만, 실시간은 여기 포함하지 않음) ──
      const merged = dedup([...aptNormalized, ...villaNormalized]);
      const rentMerged = [...aptRentNormalized, ...villaRentNormalized];
      console.log(
        `DB분 최종: 아파트=${aptNormalized.length}건 연립다세대=${villaNormalized.length}건 ` +
        `합계=${merged.length}건 / 전세=${rentMerged.length}건`
      );

      dbPayload = { apt: merged, rent: rentMerged };
      // 다음 조회(다른 기기 포함)를 위해 DB분만 캐시에 저장 (실시간은 절대 캐시하지 않음)
      await setCachedHouseData(lawdCd, dbPayload);
    }

    // 새벽 웜업 요청은 캐시만 채우면 끝 - 실시간 API는 호출하지 않고 바로 응답
    if (skipRealtime) {
      return res.status(200).json(dbPayload);
    }

    // ── 실시간(이번달 신규 신고건)은 캐시 여부와 무관하게 방문할 때마다 항상 새로 불러와서 합침 ──
    const now    = new Date();
    const thisYm = String(now.getFullYear()) + String(now.getMonth() + 1).padStart(2, '0');
    const realtimeItems = await fetchRealtimeApt(lawdCd, thisYm);
    const realtimeNormalized = realtimeItems.map(item => normalizeXMLItem(item, regionName));
    const finalApt = dedup([...realtimeNormalized, ...dbPayload.apt]);
    console.log(`실시간 반영: +${realtimeNormalized.length}건 (최종 ${finalApt.length}건)`);

    return res.status(200).json({ apt: finalApt, rent: dbPayload.rent });
  } catch (err) {
    console.error('핸들러 에러:', err.message);
    console.error('스택:', err.stack);
    return res.status(500).json({ error: err.message });
  }
}

/* ════════════════════════════════════
   국토부 실시간 API (아파트만 - 연립다세대/단독다가구는 배치 수집으로 커버)
════════════════════════════════════ */
async function fetchRealtimeApt(lawdCd, ym) {
  if (!APT_API_KEY) {
    console.warn('APT_API_KEY 없음 - 실시간 스킵');
    return [];
  }
  try {
    const url = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
      + '?serviceKey=' + encodeURIComponent(APT_API_KEY)
      + '&LAWD_CD=' + lawdCd
      + '&DEAL_YMD=' + ym
      + '&numOfRows=1000'
      + '&pageNo=1';
    const response = await fetch(url, { signal: AbortSignal.timeout(8000) });
    const text     = await response.text();
    if (text.includes('<errMsg>') || text.includes('SERVICE_KEY_IS_NOT_REGISTERED_ERROR')) {
      console.warn('국토부 API 에러:', text.slice(0, 200));
      return [];
    }
    const items = parseXMLItems(text);
    console.log(`실시간 ${ym} ${lawdCd}: ${items.length}건`);
    return items;
  } catch (e) {
    console.error('실시간 API 실패:', e.message);
    return [];
  }
}

/* ── XML 파싱 ── */
function parseXMLItems(xmlText) {
  const items = [];
  const itemRegex = /<item>([\s\S]*?)<\/item>/g;
  let match;
  while ((match = itemRegex.exec(xmlText)) !== null) {
    const block = match[1];
    items.push({
      _get: function(tag) {
        const r = new RegExp('<' + tag + '>([^<]*)<\\/' + tag + '>');
        const m = block.match(r);
        return m ? m[1].trim() : '';
      }
    });
  }
  return items;
}

/* ── XML(실시간 아파트) → 정규화
   villa 파서(shared-villa.mjs)와 동일하게 bonbun/bubun을 지번 본번/부번으로 매핑해서
   DB에 쌓인 house_trades의 main_num/sub_num과 의미가 일치하도록 맞췄습니다. ── */
function normalizeXMLItem(item, regionName) {
  const year  = parseInt(item._get('dealYear'))  || 0;
  const month = parseInt(item._get('dealMonth')) || 0;
  const day   = parseInt(item._get('dealDay'))   || 0;
  const bunjiRaw = item._get('jibun');
  const bonbun   = item._get('bonbun');
  const bubun    = item._get('bubun');
  return {
    danji:      item._get('aptNm'),
    dong:       item._get('umdNm') || '',
    deal_date:  String(year) + String(month).padStart(2,'0') + String(day).padStart(2,'0'),
    price:      parseInt((item._get('dealAmount') || '0').replace(/,/g, '')) || 0,
    size:       parseFloat(item._get('excluUseAr')) || 0,
    floor:      parseInt(item._get('floor')) || 0,
    build_year: parseInt(item._get('buildYear')) || null,
    road_name:  item._get('roadNm') || '',
    region:     regionName || '',
    bunji:      (bunjiRaw === '' || bunjiRaw === '0') ? '' : bunjiRaw,
    main_num:   parseInt(bonbun, 10) || 0,
    sub_num:    (bubun === '' || parseInt(bubun, 10) === 0) ? null : parseInt(bubun, 10),
    source:     'realtime',
    buildingType: 'apt',
  };
}

/* ── house_trades / villa_trades 공통 정규화 (스키마 동일) ── */
function normalizeRow(row, buildingType) {
  return {
    danji:      row.danji || '',
    dong:       row.dong  || '',
    deal_date:  String(row.deal_date || ''),
    price:      row.price || 0,
    size:       row.size  || 0,
    floor:      row.floor || 0,
    build_year: row.build_year || null,
    road_name:  row.road_name  || '',
    region:     row.region || '',
    bunji:      row.bunji     || '',
    main_num:   row.main_num  || 0,
    sub_num:    row.sub_num   || null,
    source:     'db',
    buildingType,
  };
}

/* ── house_rent / villa_rent 공통 정규화 (스키마 동일, price 대신 deposit/monthly_rent) ── */
function normalizeRentRow(row, buildingType) {
  return {
    danji:        row.danji || '',
    dong:         row.dong  || '',
    deal_date:    String(row.deal_date || ''),
    deposit:      row.deposit || 0,
    monthly_rent: row.monthly_rent || 0,
    size:         row.size  || 0,
    floor:        row.floor || 0,
    build_year:   row.build_year || null,
    road_name:    row.road_name  || '',
    region:       row.region || '',
    bunji:        row.bunji     || '',
    main_num:     row.main_num  || 0,
    sub_num:      row.sub_num   || null,
    buildingType,
  };
}

/* ── 중복 제거 ── */
function dedup(rows) {
  const seen = new Set();
  return rows.filter(row => {
    const key = `${row.buildingType}|${row.danji}|${row.deal_date}|${row.price}|${row.size}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
