import { createClient } from '@supabase/supabase-js';

const rawUrl = process.env.SUPABASE_URL;
const supabaseUrl = rawUrl?.trim();
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();

export const supabase = createClient(supabaseUrl, supabaseKey, {
  auth: { persistSession: false }
});

export const API_KEY = process.env.PUBLIC_DATA_API_KEY?.trim();

// --- 전국 시군구 코드 (250여 개) ---
export const LAWD_CODES = [
  '11110','11140','11170','11200','11215','11230','11260','11290','11305','11320','11350','11380','11410','11440','11470','11500','11530','11545','11560','11590','11620','11650','11680','11710','11740',
  '26110','26140','26170','26200','26230','26260','26290','26320','26350','26380','26410','26440','26470','26500','26530','26710',
  '27110','27140','27170','27200','27230','27260','27290','27710','27720',
  '28110','28140','28170','28185','28200','28237','28245','28260','28710','28720',
  '29110','29140','29155','29170','29200',
  '30110','30140','30170','30200','30230',
  '31110','31140','31170','31200','31710',
  '36110',
  '41111','41113','41115','41117','41131','41133','41135','41150','41171','41173','41190','41210','41220','41250','41271','41273','41281','41285','41287','41290','41310','41360','41370','41390','41410','41430','41450','41461','41463','41465','41480','41500','41550','41570','41590','41610','41630','41650','41670','41800','41820','41830',
  '42110','42130','42150','42170','42190','42210','42230','42720','42730','42750','42760','42770','42780','42790','42800','42810','42820','42830',
  '43111','43112','43113','43114','43130','43150','43720','43730','43740','43745','43750','43760','43770','43800',
  '44131','44133','44150','44180','44200','44210','44230','44250','44270','44710','44760','44770','44790','44800','44810','44825',
  '45111','45113','45130','45140','45180','45190','45210','45710','45720','45730','45740','45750','45770','45790','45800',
  '46110','46130','46150','46170','46230','46710','46720','46730','46770','46780','46790','46800','46810','46820','46830','46840','46860','46870','46880','46890','46900','46910',
  '47111','47113','47130','47150','47170','47190','47210','47230','47250','47280','47290','47720','47730','47750','47760','47770','47820','47830','47840','47850','47900','47920','47930','47940',
  '48121','48123','48125','48127','48129','48170','48220','48240','48250','48270','48310','48330','48720','48730','48740','48750','48780','48790','48820','48840','48850','48860','48870','48880','48890',
  '50110','50130'
];

export const sleep = ms => new Promise(r => setTimeout(r, ms));

export function parseXML(xml, lawdCd) {
  const rows = [];
  const regex = /<item>([\s\S]*?)<\/item>/g;
  const getTag = (block, tag) => {
    const m = block.match(new RegExp(`<${tag}>([^<]*)<\/${tag}>`));
    return m ? m[1].trim() : '';
  };

  let match;
  while ((match = regex.exec(xml)) !== null) {
    const b = match[1];
    
    // deal_date (YYYY-MM-DD)
    const y = getTag(b, 'dealYear');
    const m = getTag(b, 'dealMonth').padStart(2, '0');
    const d = getTag(b, 'dealDay').padStart(2, '0');
    const dealDate = `${y}-${m}-${d}`;

    rows.push({
      region: lawdCd,                                     // region
      bunji: getTag(b, 'jibun'),                          // bunji
      load_name: getTag(b, 'roadNm'),                     // load_name
      main_num: getTag(b, 'bonbun'),                      // main_num
      "sub-num": getTag(b, 'bubun'),                      // sub-num
      danji: getTag(b, 'aptNm'),                          // danji
      floor: parseInt(getTag(b, 'floor')) || null,        // floor
      size: parseFloat(getTag(b, 'excluUseAr')) || null,  // size
      deal_date: dealDate,                                // deal_date
      price: parseInt(getTag(b, 'dealAmount').replace(/,/g, '')) || 0, // price
      build_year: parseInt(getTag(b, 'buildYear')) || null // build_year
    });
  }
  return rows;
}

export async function fetchMonth(lawdCd, ym) {
  const url = `https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev?serviceKey=${encodeURIComponent(API_KEY)}&LAWD_CD=${lawdCd}&DEAL_YMD=${ym}&numOfRows=1000&pageNo=1`;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const text = await res.text();
    return parseXML(text, lawdCd);
  } catch (e) {
    console.error(`❌ \${lawdCd}/${ym} 실패:`, e.message);
    return [];
  }
}

export async function upsertBatch(rows) {
  if (rows.length === 0) return;
  const { error } = await supabase.from('house_trades').upsert(rows, { 
    onConflict: 'region,danji,size,floor,deal_date' 
  });
  if (error) console.error('upsert 에러:', error.message);
}
