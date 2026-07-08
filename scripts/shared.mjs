import { createClient } from '@supabase/supabase-js';

// 1. 환경 변수 상태를 무조건 로그로 출력 (가장 먼저 실행됨)
const rawUrl = process.env.SUPABASE_URL;
console.log("--- 시스템 체크 시작 ---");
console.log("URL 존재 여부:", rawUrl ? "있음" : "없음 (비어있음)");
if (rawUrl) console.log("URL 앞부분 확인:", rawUrl.substring(0, 10));
console.log("--- 시스템 체크 종료 ---");

const supabaseUrl = rawUrl?.trim();
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();

if (!supabaseUrl || !supabaseUrl.startsWith('http')) {
  throw new Error(`[설정오류] SUPABASE_URL이 비어있거나 형식이 틀림: "${supabaseUrl}"`);
}

export const supabase = createClient(supabaseUrl, supabaseKey);

export const API_KEY = process.env.PUBLIC_DATA_API_KEY?.trim();
export const BATCH_SIZE = 500;
export const DELAY_MS   = 200;

export const LAWD_CODES = ['11110','11140']; // 테스트를 위해 짧게 줄임 (나중에 다시 늘리셔도 됩니다)

export const sleep = ms => new Promise(r => setTimeout(r, ms));

export function parseXML(xml, lawdCd) {
  const rows  = [];
  const regex = /<item>([\s\S]*?)<\/item>/g;
  const getTag = (block, tag) => {
    const m = block.match(new RegExp(`<${tag}>([^<]*)<\/${tag}>`));
    return m ? m[1].trim() : '';
  };
  let match;
  while ((match = regex.exec(xml)) !== null) {
    const b = match[1];
    rows.push({
      lawd_cd: lawdCd,
      deal_year: parseInt(getTag(b, 'dealYear')) || null,
      deal_month: parseInt(getTag(b, 'dealMonth')) || null,
      deal_day: parseInt(getTag(b, 'dealDay')) || null,
      apartment_name: getTag(b, 'aptNm'),
      exclusive_area: parseFloat(getTag(b, 'excluUseAr')) || null,
      deal_amount: parseInt(getTag(b, 'dealAmount').replace(/,/g, '')) || 0,
      floor: parseInt(getTag(b, 'floor')) || null,
      build_year: parseInt(getTag(b, 'buildYear')) || null,
      road_name: getTag(b, 'roadNm'),
    });
  }
  return rows;
}

export async function fetchMonth(lawdCd, ym, retryCount = 0) {
  if (!API_KEY) return [];
  const url = `https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev?serviceKey=${encodeURIComponent(API_KEY)}&LAWD_CD=${lawdCd}&DEAL_YMD=${ym}&numOfRows=1000&pageNo=1`;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(10000) });
    const text = await res.text();
    if (text.includes('LIMIT_EXCEEDED')) {
      if (retryCount >= 3) return [];
      await sleep(60000);
      return fetchMonth(lawdCd, ym, retryCount + 1);
    }
    return parseXML(text, lawdCd);
  } catch (e) {
    return [];
  }
}

export async function upsertBatch(rows) {
  if (rows.length === 0) return;
  const { error } = await supabase.from('house_trades').upsert(rows, { onConflict: 'lawd_cd,deal_year,deal_month,deal_day,apartment_name,exclusive_area,floor' });
  if (error) console.error('upsert 에러:', error.message);
}
