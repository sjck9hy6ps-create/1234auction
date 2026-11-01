/* 이야기 근거 검증기 (2026-11-01): AI가 쓴 이야기의 숫자·날짜·금액·면적·퍼센트·사건번호·사람 이름('○○ 씨')이 실제 서류 원문에 있는지 대조.
   서류에 없는 값이 이야기에 섞이면(지어낸 내용) 목록으로 알려 줌. 서류에서 계산해 낸 값은 〔계산〕…〔/계산〕으로 감싸면 대조에서 제외하고 따로 표시.
   사용: node tools/story/ground-check.mjs <이야기.json> <서류1.txt> [서류2.txt ...] */
import fs from 'fs';
const W = (s) => String(s).replace(/,/g, '');
const dateKey = (y, m, d) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
function amountsIn(t) {  // 원 단위 정수 집합
  const out = new Set(); let m;
  const re1 = /(\d+(?:,\d{3})*)\s*억\s*(?:(\d+(?:,\d{3})*)\s*만)?\s*원?/g; while ((m = re1.exec(t))) out.add(parseInt(W(m[1]), 10) * 1e8 + (m[2] ? parseInt(W(m[2]), 10) * 1e4 : 0));
  const re2 = /(?<![\d,])(\d+(?:,\d{3})*)\s*만\s*원?/g; while ((m = re2.exec(t))) out.add(parseInt(W(m[1]), 10) * 1e4);
  const re3 = /(?<![\d])(\d{1,3}(?:,\d{3})+)(?![\d])/g; while ((m = re3.exec(t))) out.add(parseInt(W(m[1]), 10));
  const re4 = /(?<![\d,.])(\d{5,})(?![\d,])/g; while ((m = re4.exec(t))) out.add(parseInt(m[1], 10));
  return out;
}
function datesIn(t) {
  const out = new Set(); let m;
  const re = /(\d{4})\s*[-.년]\s*(\d{1,2})\s*[-.월]\s*(\d{1,2})\s*일?/g; while ((m = re.exec(t))) out.add(dateKey(m[1], m[2], m[3]));
  return out;
}
export function groundCheck(storyText, sources) {
  const src = sources.join('\n'), sA = amountsIn(src), sD = datesIn(src), calc = [];
  const body = String(storyText).replace(/〔계산〕([\s\S]*?)〔\/계산〕/g, (_, x) => { calc.push(x); return ' '; }).replace(/〔\/?예상〕/g, ' ');
  const toks = [];
  const add = (type, raw, ok) => toks.push({ type, raw, ok });
  let m;
  const dre = /(\d{4})\s*[-.년]\s*(\d{1,2})\s*[-.월]\s*(\d{1,2})\s*일?/g; while ((m = dre.exec(body))) add('날짜', m[0].trim(), sD.has(dateKey(m[1], m[2], m[3])));
  const are1 = /(\d+(?:,\d{3})*)\s*억\s*(?:(\d+(?:,\d{3})*)\s*만)?\s*원?/g; while ((m = are1.exec(body))) add('금액', m[0].trim(), sA.has(parseInt(W(m[1]), 10) * 1e8 + (m[2] ? parseInt(W(m[2]), 10) * 1e4 : 0)));
  const bodyNoEok = body.replace(/(\d+(?:,\d{3})*)\s*억\s*(?:(\d+(?:,\d{3})*)\s*만)?\s*원?/g, ' ');
  const are2 = /(?<![\d,])(\d+(?:,\d{3})*)\s*만\s*원?/g; while ((m = are2.exec(bodyNoEok))) add('금액', m[0].trim(), sA.has(parseInt(W(m[1]), 10) * 1e4));
  const are3 = /(?<![\d,])(\d{1,3}(?:,\d{3})+)\s*원/g; while ((m = are3.exec(bodyNoEok))) add('금액', m[0].trim(), sA.has(parseInt(W(m[1]), 10)));
  const pre = /(\d+(?:\.\d+)?)\s*%/g; while ((m = pre.exec(body))) add('퍼센트', m[0], new RegExp('(?<![\\d.])' + m[1].replace('.', '\\.') + '\\s*%').test(src));
  const mre = /(\d+(?:\.\d+)?)\s*㎡/g; while ((m = mre.exec(body))) add('면적', m[0], new RegExp('(?<![\\d.])' + m[1].replace('.', '\\.') + '\\s*㎡').test(src));
  const cre = /\d{4}타경\d+/g; while ((m = cre.exec(body))) add('사건번호', m[0], src.includes(m[0]));
  const nre = /([가-힣]{2,4})\s*씨/g; while ((m = nre.exec(body))) { const n = m[1]; const sur = n.charAt(0), masked = new RegExp(sur + 'O{2}').test(src); add('이름', n, src.includes(n) || (n.length >= 3 && src.includes(n.slice(0, 3)))); }
  const bad = toks.filter((t) => !t.ok);
  return { total: toks.length, ok: toks.length - bad.length, unverified: bad, calc };
}
if (process.argv[1] && process.argv[1].endsWith('ground-check.mjs') && process.argv.length >= 4) {
  const story = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')), text = story.sections.map((s) => s.title + '\n' + s.paragraphs.join('\n')).join('\n');
  const r = groundCheck(text, process.argv.slice(3).map((f) => fs.readFileSync(f, 'utf8')));
  console.log(`대조한 값 ${r.total}개 중 서류와 일치 ${r.ok}개 / 서류에서 못 찾은 값 ${r.unverified.length}개 / 계산으로 표시한 값 ${r.calc.length}개`);
  r.unverified.forEach((t) => console.log('  ✗ ' + t.type + ': ' + t.raw));
  r.calc.forEach((c) => console.log('  계산: ' + c.slice(0, 80)));
  process.exit(r.unverified.length ? 1 : 0);
}
