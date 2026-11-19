// 호가 읽기·펼치기(content.js) 시험 - node tests/listing-collect.test.cjs
// ① 실제 네이버 페이지 글로 매물 나누기(tests/fixtures-private/naver-*.txt 필요, 없으면 건너뜀) ② 가짜 스크롤 목록으로 끝까지 펼치기 ③ 자동으로 움직이지 않음
const vm = require('vm'), fs = require('fs'), assert = require('assert');
const fx = (f) => { try { return fs.readFileSync(__dirname + '/fixtures-private/' + f, 'utf8'); } catch (e) { return null; } };
const code = fs.readFileSync(__dirname + '/../tools/listing-extension/content.js', 'utf8');
const mk = () => ({ style: {}, children: [], appendChild(c) { this.children.push(c); } });
function load(opts) {
  const body = mk(); const timers = [];
  if (opts.page !== undefined) body.innerText = opts.page; else Object.defineProperty(body, 'innerText', { get: opts.text });
  const ctx = {
    document: { body, getElementById: () => null, createElement: mk, documentElement: { scrollHeight: 1000 }, querySelectorAll: opts.qsa || (() => []) },
    getComputedStyle: () => ({ overflowY: 'auto' }), console, setTimeout: (fn) => { Promise.resolve().then(fn); return 0; }, setInterval: (fn) => { timers.push(fn); return 0; },
    chrome: { runtime: { sendMessage() {} } }, location: { pathname: opts.path || '/complexes/1' }, innerHeight: 800, WheelEvent: class {}, Event: class {}, scrollTo() {}, scrollBy() {}, addEventListener() {}, Promise, Map, Math, JSON, String, RegExp, Array, Object,
  };
  ctx.window = ctx; vm.createContext(ctx); vm.runInContext(code, ctx);
  return { ctx, body, timers };
}
// 가짜 목록: 처음 20건, 맨 아래로 내릴 때마다 20건씩 더(전체 54건)
function fakeList(mode) {
  let N = 20; const TOTAL = 54;
  const text = () => { let t = '효형\n아파트 / 99세대\n'; for (let i = 0; i < N; i++) t += `집주인효형 ${100 + i}동\n매매${2 + (i % 3)}억 ${500 + i},000\n아파트77/59m², ${i + 1}/13층, 남서향\n확인매물 26.11.${10 + (i % 9)}.\n`; return t + `지역 선택\n${TOTAL}\n개 매물이 있습니다\n매매\n매물만 보기`; };
  const grow = () => { N = Math.min(TOTAL, N + 20); };
  const list = { scrollHeight: mode === 'scroll' ? 5000 : 600, clientHeight: 600, className: 'item_list', tagName: 'DIV', parentElement: null, set scrollTop(v) { if (mode === 'scroll' && v >= this.scrollHeight - this.clientHeight) grow(); }, get scrollTop() { return 0; }, dispatchEvent() {} };
  const last = { get innerText() { return `매매${2 + ((N - 1) % 3)}억 ${500 + N - 1},000`; }, children: [], parentElement: list, scrollIntoView() {}, dispatchEvent() {} };
  const more = { innerText: '매물 더보기', children: [], click: grow };
  const qsa = (sel) => (sel === 'div,li,span,a,p,dd' ? [last] : (sel === 'button,a,div,span' && mode === 'more' ? [more] : []));
  return { text, qsa, count: () => N };
}
(async () => {
  const bora = fx('naver-bora.txt'), yc = fx('naver-yeongcheon9.txt');
  if (bora && yc) {
    let r = await load({ page: bora }).ctx.hgCollect(); assert.strictEqual(r.n, 8, '보라맨션은 8건이어야 함(전엔 18건): ' + r.n); assert.strictEqual(r.expected, 8);
    assert.ok(!/지역 선택|📖|총 2동/.test(r.text), '매물 밖 글자가 섞이면 안 됨'); assert.strictEqual(new Set(r.text.split(/\n\n/)).size, 8);
    console.log('✓ 보라맨션(동 이름 비동·에이동): 8건, 겹침·잡글자 없음');
    r = await load({ page: yc }).ctx.hgCollect(); assert.strictEqual(r.n, 20, '요약 줄은 매물이 아님: ' + r.n); assert.strictEqual(r.expected, 54);
    console.log('✓ 영천마을주공9단지: 화면에 20건(첫 분량)이 보이고 화면 표시 건수 54건을 읽음');
  } else console.log('(실제 페이지 글 파일 없음: 건너뜀)');
  // ② 스크롤 영역을 내리면 20건씩 더 불러오는 목록 → 54건까지
  let f = fakeList('scroll'), L = load({ text: f.text, qsa: f.qsa });
  let r = await L.ctx.hgExpand(); assert.strictEqual(r.n, 54); assert.strictEqual(r.expected, 54); assert.ok(/item_list/.test(r.info), r.info);
  console.log('✓ 마지막 매물을 감싸는 스크롤 영역을 맨 아래로 내려 20→40→54건까지 펼침');
  // ③ 스크롤 영역이 없고 '매물 더보기' 버튼으로만 더 불러오는 목록
  f = fakeList('more'); L = load({ text: f.text, qsa: f.qsa }); r = await L.ctx.hgExpand(); assert.strictEqual(r.n, 54);
  console.log("✓ 스크롤 영역이 없어도 '매물 더보기' 버튼을 눌러 54건까지 펼침");
  // ④ 아무것도 누르지 않으면 자동으로 움직이지 않음(타이머·자동 펼치기 없음)
  f = fakeList('scroll'); L = load({ text: f.text, qsa: f.qsa, path: '/complexes/777' }); await new Promise((r) => setTimeout(r, 100));
  assert.strictEqual(L.timers.length, 0); assert.strictEqual(f.count(), 20);
  console.log('✓ 단지 화면에 들어가도 버튼을 누르기 전에는 아무것도 스크롤하지 않음(자동 펼치기 없음)');
  console.log('모두 통과');
})().catch((e) => { console.error('실패:', e); process.exit(1); });
