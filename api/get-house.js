import { createClient } from '@supabase/supabase-js';
import { LAWD_CODES } from '../scripts/lawd-codes.mjs';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);
const APT_API_KEY = process.env.PUBLIC_DATA_API_KEY;

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.setHeader('Pragma', 'no-cache');

  const lawdCd = req.query.lawdCd;
  if (!lawdCd) return res.status(400).json({ error: 'lawdCd required' });

  // house_trades / villa_trades 모두 lawd_cd 컬럼이 없고 region 텍스트로 저장되어 있어
  // LAWD_CODES로 lawdCd → 지역명 변환이 필요합니다.
  const regionInfo = LAWD_CODES.find(r => r.code === lawdCd);
  const regionName = regionInfo ? regionInfo.name : '';

  console.log('lawdCd:', lawdCd, '/ regionName:', regionName || '(매칭 실패)');

  try {
    // ── 아파트 DB / 연립다세대 DB / 실시간 아파트, 세 요청을 동시에 실행 ──
    // (기존엔 순차 await라 셋의 소요시간이 그대로 합산됐음. Promise.all로 묶어서
    //  전체 대기시간을 "셋의 합"이 아니라 "가장 느린 것 하나" 수준으로 줄입니다.)
    const now    = new Date();
    const thisYm = String(now.getFullYear()) + String(now.getMonth() + 1).padStart(2, '0');

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

    const [aptResult, villaResult, aptRentResult, villaRentResult, realtimeItems] = await Promise.all([
      aptQuery,
      villaQuery,
      aptRentQuery,
      villaRentQuery,
      fetchRealtimeApt(lawdCd, thisYm),
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
    const realtimeNormalized = realtimeItems.map(item => normalizeXMLItem(item, regionName));
    const aptRentNormalized   = aptRentData.map(row => normalizeRentRow(row, 'apt'));
    const villaRentNormalized = villaRentData.map(row => normalizeRentRow(row, 'villa'));

    // ── 5. 합치기 + 중복 제거 (실시간 데이터를 우선 배치해서 DB보다 먼저 dedup 살아남게 함) ──
    const merged = dedup([...realtimeNormalized, ...aptNormalized, ...villaNormalized]);
    const rentMerged = [...aptRentNormalized, ...villaRentNormalized];
    console.log(
      `최종: 아파트=${aptNormalized.length}건 연립다세대=${villaNormalized.length}건 ` +
      `실시간=${realtimeNormalized.length}건 합계=${merged.length}건 / 전세=${rentMerged.length}건`
    );

    return res.status(200).json({ apt: merged, rent: rentMerged });
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
