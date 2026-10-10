/* 수도권 연립다세대 전월세(villa_rent) 수집 (2026-10-10, 사용자: "빌라 매매의 핵심은 전세가 - 건물 단위 전세 이력으로 매매가를 가늠")
   지금 villa_rent는 CSV로 올린 2025-01~2026-05(순수 전세 약 10.8만 건)뿐이라 건물 단위 전세가 5%만 잡힘 → 국토부 RHRent API로 과거·현재를 채움.
   - 서울·인천·경기만(빌라는 수도권 한정). YEARS(콤마, 기본 올해)·MONTHS(콤마, 기본 전부, 올해는 이번 달까지).
   - GitHub Actions는 국토부를 직접 못 불러 Vercel 프록시(get-house?action=molitProxy&endpoint=rhRent)를 씀.
   - 한 달 1,000건 넘는 지역은 page로 이어 받음. 키가 이 API 활용신청 전이면(SERVICE KEY 오류) 바로 알려주고 멈춤. */
import { LAWD_CODES, sleep, DELAY_MS, API_KEY, supabase } from './shared-rent.mjs';
import { upsertChunked } from './shared.mjs';

const SITE_URL = process.env.SITE_URL?.trim();
const PROXY_SECRET = process.env.COLLECT_PROXY_SECRET?.trim();
const years = (process.env.YEARS || String(new Date().getFullYear())).split(',').map(s => parseInt(s.trim(), 10)).filter(Boolean);
const months = (process.env.MONTHS || '1,2,3,4,5,6,7,8,9,10,11,12').split(',').map(s => parseInt(s.trim(), 10)).filter(Boolean);
const now = new Date();
const METRO = LAWD_CODES.filter(({ name }) => /^(서울|인천|경기)/.test(name));

const tag = (b, t) => { const m = b.match(new RegExp(`<${t}>([^<]*)<\\/${t}>`)); return m ? m[1].trim() : ''; };
const num = (v) => { const n = parseInt(String(v || '').replace(/,/g, ''), 10); return Number.isNaN(n) ? 0 : n; };

function parse(xml, regionName) {
  const rows = [], re = /<item>([\s\S]*?)<\/item>/g; let m;
  while ((m = re.exec(xml)) !== null) {
    const b = m[1];
    const dd = parseInt(`${tag(b, 'dealYear')}${tag(b, 'dealMonth').padStart(2, '0')}${tag(b, 'dealDay').padStart(2, '0')}`);
    const jibun = tag(b, 'jibun'); let mainNum = null, subNum = null;
    if (jibun) { const p = jibun.split('-'); const a = parseInt(p[0], 10), c = p[1] !== undefined ? parseInt(p[1], 10) : null; mainNum = Number.isNaN(a) ? null : a; subNum = (c === null || Number.isNaN(c) || c === 0) ? null : c; }
    const ar = parseFloat(tag(b, 'excluUseAr').replace(/,/g, ''));
    const fl = parseInt(tag(b, 'floor'), 10), by = parseInt(tag(b, 'buildYear'), 10);
    rows.push({
      region: regionName, dong: tag(b, 'umdNm'), danji: tag(b, 'mhouseNm'), size: Number.isFinite(ar) ? Math.floor(ar) : null,
      deposit: num(tag(b, 'deposit')), monthly_rent: num(tag(b, 'monthlyRent')), deal_date: Number.isFinite(dd) ? dd : null,
      floor: Number.isNaN(fl) ? null : fl, bunji: (jibun === '' || jibun === '0') ? null : jibun, main_num: mainNum, sub_num: subNum,
      build_year: Number.isNaN(by) ? null : by, road_name: tag(b, 'roadNm'), contract_type: tag(b, 'contractType'), house_type: tag(b, 'houseType') || null,
    });
  }
  return rows;
}

async function fetchPage(code, ym, page) {
  const direct = `https://apis.data.go.kr/1613000/RTMSDataSvcRHRent/getRTMSDataSvcRHRent?serviceKey=${encodeURIComponent(API_KEY)}&LAWD_CD=${code}&DEAL_YMD=${ym}&numOfRows=1000&pageNo=${page}`;
  const proxy = SITE_URL && PROXY_SECRET ? `${SITE_URL}/api/get-house?action=molitProxy&endpoint=rhRent&code=${code}&ym=${ym}&page=${page}&secret=${encodeURIComponent(PROXY_SECRET)}` : null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try { const r = await fetch(proxy || direct, { signal: AbortSignal.timeout(25000) }); return await r.text(); }
    catch (e) { if (attempt === 3) { console.error(`❌ ${code}/${ym} p${page} 실패: ${e.message}`); return ''; } await sleep(1000 * attempt); }
  }
  return '';
}

let total = 0, first = true;
for (const y of years) {
  for (const mo of months) {
    if (y > now.getFullYear() || (y === now.getFullYear() && mo > now.getMonth() + 1)) continue;
    const ym = `${y}${String(mo).padStart(2, '0')}`;
    let n = 0;
    for (const { code, name } of METRO) {
      let rows = [];
      for (let page = 1; page <= 5; page++) {
        const xml = await fetchPage(code, ym, page);
        if (first) {
          const rc = tag(xml, 'resultCode'), msg = tag(xml, 'resultMsg') || tag(xml, 'errMsg') || tag(xml, 'returnAuthMsg');
          console.log(`첫 응답 resultCode=${rc} msg=${msg} 길이=${xml.length}`);
          if (rc && rc !== '000' && rc !== '00') { console.error('⛔ 국토부 연립다세대 전월세 API 오류 - 키의 활용신청(RTMSDataSvcRHRent) 승인 여부 확인 필요'); console.error(xml.slice(0, 400)); process.exit(1); }
          if (!/<item>/.test(xml) && /SERVICE|KEY|UNREGISTERED|인증/i.test(xml)) { console.error('⛔ 서비스키 오류\n' + xml.slice(0, 400)); process.exit(1); }
          first = false;
        }
        const r = parse(xml, name); rows.push(...r);
        if (r.length < 1000) break;
        await sleep(DELAY_MS);
      }
      if (rows.length) {
        const uniq = Array.from(new Map(rows.map(r => [`${r.region}_${r.dong}_${r.danji}_${r.size}_${r.floor}_${r.deal_date}`, r])).values());
        await upsertChunked('villa_rent', uniq, 'region,dong,danji,size,floor,deal_date');
        n += uniq.length;
      }
      await sleep(DELAY_MS);
    }
    total += n; console.log(`✅ ${ym} 수도권 ${n}건 (누적 ${total})`);
  }
}
console.log(`🎉 완료 ${total}건`);
