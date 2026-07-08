import { createClient } from '@supabase/supabase-js';

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

  // ── 환경변수 체크 ──
  console.log('SUPABASE_URL:', process.env.SUPABASE_URL ? '✅ 있음' : '❌ 없음');
  console.log('SUPABASE_SERVICE_ROLE_KEY:', process.env.SUPABASE_SERVICE_ROLE_KEY ? '✅ 있음' : '❌ 없음');
  console.log('lawdCd:', lawdCd);

  try {
    // ── 1. DB 조회 ──
    console.log('DB 조회 시작...');
    const { data, error } = await supabase   // ← data로 정확히 받기
      .from('house_trades')
      .select('*')
      .eq('lawd_cd', lawdCd)
      .order('deal_year',  { ascending: false })
      .order('deal_month', { ascending: false });

    // 에러 상세 출력
    if (error) {
      console.error('Supabase 에러 코드:', error.code);
      console.error('Supabase 에러 메시지:', error.message);
      console.error('Supabase 에러 상세:', error.details);
      throw error;
    }

    console.log('DB 조회 완료. 건수:', data ? data.length : 0);
    if (data && data.length > 0) {
      console.log('첫번째 row 샘플:', JSON.stringify(data[0]));
    }

    // ── 2. 실시간 ──
    const now    = new Date();
    const thisYm = String(now.getFullYear()) + String(now.getMonth() + 1).padStart(2, '0');
    const realtimeItems = await fetchRealtimeApt(lawdCd, thisYm);

    // ── 3. 정규화 ──
    const dbNormalized       = (data || []).map(normalizeDBRow);
    const realtimeNormalized = realtimeItems.map(normalizeXMLItem);

    // ── 4. 합치기 + 중복 제거 ──
    const merged = dedup([...realtimeNormalized, ...dbNormalized]);

    console.log(`최종: DB=${dbNormalized.length}건 실시간=${realtimeNormalized.length}건 합계=${merged.length}건`);

    return res.status(200).json({ apt: merged, rent: [] });

  } catch (err) {
    console.error('핸들러 에러:', err.message);
    console.error('스택:', err.stack);
    return res.status(500).json({ error: err.message });
  }
}

/* ════════════════════════════════════
   국토부 실시간 API
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
    console.log(`실시간 \${ym} \${lawdCd}: \${items.length}건`);
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

/* ── XML → 정규화 ── */
function normalizeXMLItem(item) {
  const year  = parseInt(item._get('dealYear'))  || 0;
  const month = parseInt(item._get('dealMonth')) || 0;
  const day   = parseInt(item._get('dealDay'))   || 0;

  return {
    danji:      item._get('aptNm'),
    deal_date:  String(year) + String(month).padStart(2,'0') + String(day).padStart(2,'0'),
    price:      parseInt((item._get('dealAmount') || '0').replace(/,/g, '')) || 0,
    size:       parseFloat(item._get('excluUseAr')) || 0,
    floor:      parseInt(item._get('floor')) || 0,
    build_year: parseInt(item._get('buildYear')) || null,
    road_name:  (item._get('roadNm') + ' ' + item._get('roadNmBonbun')).trim(),
    region:     '',
    bunji:      item._get('jibun'),
    main_num:   parseInt(item._get('jibun')) || 0,
    sub_num:    null,
    lat:        null,
    lon:        null,
    source:     'realtime',
  };
}

/* ── DB row → 정규화 ── */
function normalizeDBRow(row) {
  const year  = row.deal_year  || 0;
  const month = row.deal_month || 0;
  const day   = row.deal_day   || 0;
  const dateStr = String(year)
    + String(month).padStart(2, '0')
    + String(day).padStart(2, '0');

  return {
    danji:      row.apartment_name || '',
    deal_date:  dateStr,
    price:      row.deal_amount    || 0,
    size:       row.exclusive_area || 0,
    floor:      row.floor          || 0,
    build_year: row.build_year     || null,
    road_name:  row.road_name      || '',
    region:     '',
    bunji:      '',
    main_num:   0,
    sub_num:    null,
    lat:        row.lat            || null,
    lon:        row.lon            || null,
    source:     'db',
  };
}

/* ── 중복 제거 ── */
function dedup(rows) {
  const seen = new Set();
  return rows.filter(row => {
    const key = `${row.danji}|${row.deal_date}|${row.price}|${row.size}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
