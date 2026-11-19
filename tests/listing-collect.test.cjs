// 호가 읽기(content.js) 시험: 실제 네이버 페이지 글로 매물 나누기가 맞는지 - node tests/chain-collect.test.cjs (tests/fixtures-private/naver-*.txt 필요, 없으면 건너뜀)
const vm = require('vm'), fs = require('fs'), assert = require('assert');
const fx = (f) => { try { return fs.readFileSync(__dirname + '/fixtures-private/' + f, 'utf8'); } catch (e) { return null; } };
const collect = async (page) => {
  const mk = () => ({ style: {}, children: [], appendChild(c) { this.children.push(c); } });
  const body = mk(); body.innerText = page;
  const ctx = { document: { body, getElementById: () => null, createElement: mk, querySelectorAll: () => [] }, getComputedStyle: () => ({ overflowY: 'visible' }), console, setTimeout: (fn) => { Promise.resolve().then(fn); return 0; }, chrome: { runtime: { sendMessage() {} } }, innerHeight: 800, WheelEvent: class {}, scrollBy() {}, Promise, Map, Math, JSON, String, RegExp, Array, Object };
  ctx.window = ctx; vm.createContext(ctx); vm.runInContext(fs.readFileSync(__dirname + '/../tools/listing-extension/content.js', 'utf8'), ctx);
  return ctx.hgCollect();
};
(async () => {
  const bora = fx('naver-bora.txt'), yc = fx('naver-yeongcheon9.txt'); if (!bora || !yc) { console.log('건너뜀(실제 페이지 글 파일 없음)'); return; }
  let r = await collect(bora); assert.strictEqual(r.n, 8, '보라맨션은 8건이어야 함(전엔 18건): ' + r.n); assert.strictEqual(r.expected, 8);
  assert.ok(!/지역 선택|📖|총 2동/.test(r.text), '매물 밖 글자가 섞이면 안 됨'); assert.strictEqual(new Set(r.text.split(/\n\n/)).size, 8);
  console.log('✓ 보라맨션(동 이름 비동·에이동): 8건, 겹침·잡글자 없음');
  r = await collect(yc); assert.strictEqual(r.n, 20, '요약 줄은 매물이 아님: ' + r.n); assert.strictEqual(r.expected, 54);
  console.log('✓ 영천마을주공9단지: 화면에 20건(첫 분량)이 보이고 화면 표시 건수 54건을 읽음(스크롤이 되면 더 늘어남)');
})().catch((e) => { console.error('실패:', e); process.exit(1); });
