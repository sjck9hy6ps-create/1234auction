/* ════════════════════════════════════
   아파트 분양권·입주권 전매 실거래 수집 (2026-10)
   사용자 요청: 신축 단지(예: 광주 송정크레지움센트럴)는 일반 매매 실거래가 아직 없어 예상매도가·인기 판단을 못 함 -
   분양권·입주권 전매 거래로 신축 시세를 잡음. 국토부 "아파트 분양권전매 실거래가 자료"(RTMSDataSvcSilvTrade).
   ⚠️ data.go.kr에서 이 API도 별도로 활용신청이 되어 있어야 함(일반 매매 API와 별개).
   저장: 새 테이블을 만들지 않고 leader_follower_cache에 시군구별 JSON('presale|<시군구>')으로 둠 - 최근 36개월만 유지.
   거래금액은 분양가+웃돈을 합친 총액(국토부 신고 기준).
   실행: PRESALE_MONTHS(기본 3) 개월치를 받아 기존 저장분과 합침. 처음엔 36으로 한 번 돌려 채움.
   ════════════════════════════════════ */
import { supabase, LAWD_CODES, sleep, DELAY_MS } from './shared.mjs';

const MONTHS = parseInt(process.env.PRESALE_MONTHS || '3', 10);
const KEEP_MONTHS = 36;
const SITE_URL = process.env.SITE_URL?.trim();
const PROXY_SECRET = process.env.COLLECT_PROXY_SECRET?.trim();
const ONLY = (process.env.PRESALE_ONLY || '').trim(); // 시군구 코드 하나만(시험용)

function tag(block, t) {
  const m = block.match(new RegExp(`<${t}>([^<]*)</${t}>`));
  return m ? m[1].trim() : '';
}
function parse(xml) {
  const out = [];
  const code = tag(xml, 'resultCode');
  if (code && code !== '00' && code !== '000') return { rows: out, error: code + ' ' + tag(xml, 'resultMsg') };
  const re = /<item>([\s\S]*?)<\/item>/g;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const b = m[1];
    if (/^O$/i.test(tag(b, 'cdealType'))) continue; // 계약 해제된 거래 제외
    const y = tag(b, 'dealYear'), mo = tag(b, 'dealMonth').padStart(2, '0'), d = tag(b, 'dealDay').padStart(2, '0');
    const price = parseInt(tag(b, 'dealAmount').replace(/,/g, ''), 10);
    const size = parseFloat(tag(b, 'excluUseAr').replace(/,/g, ''));
    if (!price || !size) continue;
    out.push([tag(b, 'umdNm'), tag(b, 'aptNm'), tag(b, 'jibun'), Math.round(size * 10) / 10, price,
      parseInt(y + mo + d, 10), parseInt(tag(b, 'floor'), 10) || null, tag(b, 'ownershipGbn') || '분양권']);
  }
  return { rows: out, error: null };
}
async function fetchMonth(code, ym) {
  if (!SITE_URL || !PROXY_SECRET) throw new Error('SITE_URL/COLLECT_PROXY_SECRET 필요');
  const url = `${SITE_URL}/api/get-house?action=molitProxy&endpoint=presale&code=${code}&ym=${ym}&secret=${encodeURIComponent(PROXY_SECRET)}`;
  for (let i = 1; i <= 3; i++) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(20000) });
      return parse(await r.text());
    } catch (e) { if (i < 3) await sleep(1500 * i); else return { rows: [], error: e.message }; }
  }
}

const now = new Date();
const months = [];
for (let i = 0; i < MONTHS; i++) {
  const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
  months.push(String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0'));
}
const keepFrom = (() => { const d = new Date(now.getFullYear(), now.getMonth() - KEEP_MONTHS + 1, 1); return parseInt(String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0') + '01', 10); })();
console.log(`📅 분양권 수집 ${months.length}개월 (${months[months.length - 1]}~${months[0]})`);

let total = 0, errors = 0, firstError = null, saved = 0;
const codes = ONLY ? LAWD_CODES.filter(c => c.code === ONLY) : LAWD_CODES;
for (const { code, name } of codes) {
  const fresh = [];
  for (const ym of months) {
    const { rows, error } = await fetchMonth(code, ym);
    if (error) { errors++; if (!firstError) firstError = `${name} ${ym}: ${error}`; }
    fresh.push(...rows);
    await sleep(DELAY_MS);
  }
  if (errors && errors === months.length && !fresh.length && firstError && /SERVICE|KEY|등록|30|20/i.test(firstError)) {
    console.error('❌ API 오류 - 활용신청/키 확인 필요:', firstError);
    process.exit(1);
  }
  const id = `presale|${name}`;
  const { data: prev } = await supabase.from('leader_follower_cache').select('payload').eq('id', id).maybeSingle();
  const map = new Map();
  ((prev && prev.payload && prev.payload.trades) || []).forEach(t => { if (t[5] >= keepFrom) map.set(t.slice(0, 7).join('|'), t); });
  fresh.forEach(t => map.set(t.slice(0, 7).join('|'), t));
  const trades = [...map.values()].sort((a, b) => b[5] - a[5]);
  total += fresh.length;
  if (!trades.length) continue;
  const { error } = await supabase.from('leader_follower_cache').upsert({
    id, payload: { region: name, updatedAt: now.toISOString(), fields: ['dong', 'danji', 'jibun', 'size', 'price', 'date', 'floor', 'kind'], trades },
    fetched_at: now.toISOString(),
  }, { onConflict: 'id' });
  if (error) console.error(`❌ ${name} 저장 실패: ${error.message}`); else saved++;
  console.log(`  ${name}: 새로 ${fresh.length}건, 보관 ${trades.length}건`);
}
console.log(`🎉 완료: 새로 받은 거래 ${total}건, 저장한 시군구 ${saved}곳, 오류 ${errors}회${firstError ? ' (첫 오류: ' + firstError + ')' : ''}`);
