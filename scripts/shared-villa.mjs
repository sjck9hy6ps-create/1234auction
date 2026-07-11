import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.SUPABASE_URL?.trim();
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();

export const supabase = createClient(supabaseUrl, supabaseKey, {
  auth: { persistSession: false }
});

export const DELAY_MS = 300;
export const API_KEY  = process.env.PUBLIC_DATA_API_KEY?.trim();

export const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── 파서 (연립다세대 단지명: mhouseNm) ──
export function parseXMLVilla(xml, regionName) {
  const rows  = [];
  const regex = /<item>([\s\S]*?)<\/item>/g;
  const getTag = (block, tag) => {
    const m = block.match(new RegExp(`<${tag}>([^<]*)<\/${tag}>`));
    return m ? m[1].trim() : '';
  };

  let match;
  while ((match = regex.exec(xml)) !== null) {
    const b = match[1];

    const y  = getTag(b, 'dealYear');
    const mm = getTag(b, 'dealMonth').padStart(2, '0');
    const dd = getTag(b, 'dealDay').padStart(2, '0');
    const dealDateInt = parseInt(`${y}${mm}${dd}`);

    rows.push({
      region:     regionName,
      dong:       getTag(b, 'umdNm')     || '',
      danji:      getTag(b, 'mhouseNm')  || '',   // 연립다세대 단지명 필드
      size: (() => {
        const v = getTag(b, 'excluUseAr');
        if (!v) return null;
        const n = parseFloat(v.replace(/,/g, ''));
        return Number.isFinite(n) ? Math.floor(n) : null;
      })(),
      price: (() => {
        const v = getTag(b, 'dealAmount').replace(/,/g, '').trim();
        if (v === '') return 0;
        const n = parseInt(v, 10);
        return Number.isNaN(n) ? 0 : n;
      })(),
      deal_date:  Number.isFinite(dealDateInt) ? dealDateInt : null,
      floor: (() => {
        const v = getTag(b, 'floor').trim();
        if (v === '') return null;
        const n = parseInt(v, 10);
        return Number.isNaN(n) ? null : n;
      })(),
      bunji: (() => {
  const v = getTag(b, 'jibun').trim();
  return (v === '' || v === '0') ? null : v;
})(),
main_num: (() => {
  const v = getTag(b, 'bonbun').trim();
  const n = parseInt(v, 10);
  if (v === '' || Number.isNaN(n) || n === 0) return null;
  return n;
})(),
sub_num: (() => {
  const v = getTag(b, 'bubun').trim();
  const n = parseInt(v, 10);
  if (v === '' || Number.isNaN(n) || n === 0) return null;
  return n;
})(),

      build_year: (() => {
        const v = getTag(b, 'buildYear').trim();
        const n = parseInt(v, 10);
        return v === '' || Number.isNaN(n) ? null : n;
      })(),
      road_name:  getTag(b, 'roadNm')    || '',
    });
  }
  return rows;
}

// ── 파서 (단독/다가구 — 단지명 없음, 지번으로 식별) ──
export function parseXMLSingle(xml, regionName) {
  const rows  = [];
  const regex = /<item>([\s\S]*?)<\/item>/g;
  const getTag = (block, tag) => {
    const m = block.match(new RegExp(`<${tag}>([^<]*)<\/${tag}>`));
    return m ? m[1].trim() : '';
  };

  let match;
  while ((match = regex.exec(xml)) !== null) {
    const b = match[1];

    const y  = getTag(b, 'dealYear');
    const mm = getTag(b, 'dealMonth').padStart(2, '0');
    const dd = getTag(b, 'dealDay').padStart(2, '0');
    const dealDateInt = parseInt(`${y}${mm}${dd}`);

    // 단독/다가구는 단지명이 없으므로 dong+jibun 조합으로 식별
    const dong  = getTag(b, 'umdNm') || '';
    const jibun = getTag(b, 'jibun') || '';
    const danji = dong && jibun ? `${dong} \${jibun}` : (dong || jibun || '');

    rows.push({
      region:     regionName,
      dong:       dong,
      danji:      danji,
      size: (() => {
        // 단독/다가구는 totalFloorAr(연면적) 또는 plottageAr(대지면적) 사용
        const v = getTag(b, 'totalFloorAr') || getTag(b, 'plottageAr');
        if (!v) return null;
        const n = parseFloat(v.replace(/,/g, ''));
        return Number.isFinite(n) ? Math.floor(n) : null;
      })(),
      price: (() => {
        const v = getTag(b, 'dealAmount').replace(/,/g, '').trim();
        if (v === '') return 0;
        const n = parseInt(v, 10);
        return Number.isNaN(n) ? 0 : n;
      })(),
      deal_date:  Number.isFinite(dealDateInt) ? dealDateInt : null,
      floor:      null,   // 단독/다가구는 층 개념 없음
      bunji: (() => {
  const v = getTag(b, 'jibun').trim();
  return (v === '' || v === '0') ? null : v;
})(),
main_num: (() => {
  const v = getTag(b, 'bonbun').trim();
  const n = parseInt(v, 10);
  if (v === '' || Number.isNaN(n) || n === 0) return null;
  return n;
})(),
sub_num: (() => {
  const v = getTag(b, 'bubun').trim();
  const n = parseInt(v, 10);
  if (v === '' || Number.isNaN(n) || n === 0) return null;
  return n;
})(),

      build_year: (() => {
        const v = getTag(b, 'buildYear').trim();
        const n = parseInt(v, 10);
        return v === '' || Number.isNaN(n) ? null : n;
      })(),
      road_name:  getTag(b, 'roadNm') || '',
    });
  }
  return rows;
}

// ── API 호출 ──
export async function fetchMonthVilla(code, name, ym) {
  const url = `https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade`
    + `?serviceKey=${encodeURIComponent(API_KEY)}&LAWD_CD=${code}&DEAL_YMD=${ym}&numOfRows=1000&pageNo=1`;
  try {
    const res  = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const text = await res.text();
    return parseXMLVilla(text, name);
  } catch (e) {
    console.error(`❌ ${code}${ym} 연립다세대 실패:`, e.message);
    return [];
  }
}

export async function fetchMonthSingle(code, name, ym) {
  const url = `https://apis.data.go.kr/1613000/RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade`
    + `?serviceKey=${encodeURIComponent(API_KEY)}&LAWD_CD=${code}&DEAL_YMD=${ym}&numOfRows=1000&pageNo=1`;
  try {
    const res  = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const text = await res.text();
    return parseXMLSingle(text, name);
  } catch (e) {
    console.error(`❌ \${code}/${ym} 단독/다가구 실패:`, e.message);
    return [];
  }
}

// ── upsert ──
export async function upsertVilla(rows) {
  if (!rows.length) return;
  const uniqueRows = Array.from(
    new Map(rows.map(r => [
      `${r.region}_${r.dong}_${r.danji}_${r.size}_${r.floor}_${r.deal_date}`, r
    ])).values()
  );
  const { error } = await supabase.from('villa_trades').upsert(uniqueRows, {
    onConflict: 'region,dong,danji,size,floor,deal_date'
  });
  if (error) console.error('❌ villa_trades upsert 에러:', error.message);
}

export async function upsertSingle(rows) {
  if (!rows.length) return;
  const uniqueRows = Array.from(
    new Map(rows.map(r => [
      `${r.region}_${r.dong}_${r.danji}_${r.size}_${r.floor}_${r.deal_date}`, r
    ])).values()
  );
  const { error } = await supabase.from('single_trades').upsert(uniqueRows, {
    onConflict: 'region,dong,danji,size,floor,deal_date'
  });
  if (error) console.error('❌ single_trades upsert 에러:', error.message);
}
