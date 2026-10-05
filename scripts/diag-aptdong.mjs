// 진단(2026-10): 국토부 아파트 매매 실거래 응답에 동(aptDong)·등기일자(rgstDate)·해제(cdealType)·거래당사자(buyerGbn/slerGbn)가
// 실제로 채워져 있는지, 연도별로 확인 - 낙찰 후 되팔기 매칭을 "같은 동·같은 층"으로 좁힐 수 있는지 판단용
const SITE = process.env.SITE_URL, SECRET = process.env.COLLECT_PROXY_SECRET;
const tags = ['aptDong', 'rgstDate', 'cdealType', 'buyerGbn', 'slerGbn', 'dealingGbn'];
const codes = (process.env.CODES || '26200,29155,30110').split(',');
const yms = (process.env.YMS || '202106,202206,202306,202406,202506,202608').split(',');
for (const code of codes) for (const ym of yms) {
  const url = `${SITE}/api/get-house?action=molitProxy&endpoint=aptTrade&code=${code}&ym=${ym}&secret=${encodeURIComponent(SECRET)}`;
  try {
    const xml = await fetch(url).then((r) => r.text());
    const items = xml.split('<item>').slice(1);
    const fill = {};
    tags.forEach((t) => { fill[t] = items.filter((it) => { const m = it.match(new RegExp(`<${t}>([^<]*)</${t}>`)); return m && m[1].trim() !== ''; }).length; });
    const ex = items[0] ? tags.map((t) => { const m = items[0].match(new RegExp(`<${t}>([^<]*)</${t}>`)); return `${t}=${m ? m[1].trim() : '(없음)'}`; }).join(' ') : '';
    console.log(`${code} ${ym}: ${items.length}건 · ` + tags.map((t) => `${t} ${items.length ? Math.round(fill[t] / items.length * 100) : 0}%`).join(' · ') + (ex ? `  예) ${ex}` : ''));
  } catch (e) { console.log(code, ym, '실패', e.message); }
}
