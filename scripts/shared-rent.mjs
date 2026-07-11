import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import { LAWD_CODES } from './shared.mjs';

export { LAWD_CODES };

const supabaseUrl = process.env.SUPABASE_URL?.trim();
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();
export const supabase = createClient(supabaseUrl, supabaseKey, {
  auth: { persistSession: false },
  // Node 20은 네이티브 WebSocket이 없어 최신 supabase-js의 Realtime 클라이언트
  // 초기화가 실패함 → ws 패키지를 명시적으로 transport로 지정해 우회
  realtime: { transport: ws }
});

export const DELAY_MS = 300;
export const API_KEY  = process.env.PUBLIC_DATA_API_KEY?.trim();
export const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ── 전월세 XML 파서 ──
   ⚠ 국토부 RTMSDataSvcAptRent의 표준 태그명을 기준으로 작성했습니다.
   샌드박스 네트워크 제한으로 실제 응답을 직접 확인하지 못했으니,
   scripts/collect-history-rent.mjs를 1개월치만 시범 실행해서
   콘솔에 찍히는 첫 row 샘플로 필드명이 맞는지 확인해보세요. */
export function parseXMLRent(xml, regionName) {
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

    // jibun이 "100-1" 형태 문자열로만 오고 별도 bonbun/bubun 태그가 없을 수 있어
    // 지번 문자열을 직접 분리합니다.
    const jibun = getTag(b, 'jibun') || '';
    let mainNum = null, subNum = null;
    if (jibun) {
      const parts = jibun.split('-');
      const m1 = parseInt(parts[0], 10);
      const m2 = parts[1] !== undefined ? parseInt(parts[1], 10) : null;
      mainNum = Number.isNaN(m1) ? null : m1;
      subNum  = (m2 === null || Number.isNaN(m2) || m2 === 0) ? null : m2;
    }

    rows.push({
      region:     regionName,
      dong:       getTag(b, 'umdNm') || '',
      danji:      getTag(b, 'aptNm') || '',
      size: (() => {
        const v = getTag(b, 'excluUseAr');
        if (!v) return null;
        const n = parseFloat(v.replace(/,/g, ''));
        return Number.isFinite(n) ? Math.floor(n) : null;
      })(),
      deposit: (() => {
        const v = (getTag(b, 'deposit') || '').replace(/,/g, '').trim();
        if (v === '') return 0;
        const n = parseInt(v, 10);
        return Number.isNaN(n) ? 0 : n;
      })(),
      monthly_rent: (() => {
        const v = (getTag(b, 'monthlyRent') || '').replace(/,/g, '').trim();
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
      bunji:      (jibun === '' || jibun === '0') ? null : jibun,
      main_num:   mainNum,
      sub_num:    subNum,
      build_year: (() => {
        const v = getTag(b, 'buildYear').trim();
        const n = parseInt(v, 10);
        return v === '' || Number.isNaN(n) ? null : n;
      })(),
      road_name:     getTag(b, 'roadNm') || '',
      contract_type: getTag(b, 'contractType') || '',
    });
  }
  return rows;
}

// ── API 호출 ──
export async function fetchMonthRent(code, name, ym) {
  const url = `https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent`
    + `?serviceKey=${encodeURIComponent(API_KEY)}&LAWD_CD=${code}&DEAL_YMD=${ym}&numOfRows=1000&pageNo=1`;
  try {
    const res  = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const text = await res.text();
    return parseXMLRent(text, name);
  } catch (e) {
    console.error(`❌ ${code}/${ym} 전월세 실패:`, e.message);
    return [];
  }
}

// ── upsert ──
export async function upsertRent(rows) {
  if (!rows.length) return;
  const uniqueRows = Array.from(
    new Map(rows.map(r => [
      `${r.region}_${r.dong}_${r.danji}_${r.size}_${r.floor}_${r.deal_date}`, r
    ])).values()
  );
  const { error } = await supabase.from('house_rent').upsert(uniqueRows, {
    onConflict: 'region,dong,danji,size,floor,deal_date'
  });
  if (error) console.error('❌ house_rent upsert 에러:', error.message);
}
