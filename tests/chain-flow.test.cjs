// 호가 자동 진행 흐름 시험(가짜 크롬·가짜 화면): node tests/chain-flow.test.cjs  - 페이지가 바뀔 때마다 스크립트를 다시 실행해 이어지는지 확인
const vm = require('vm'), fs = require('fs'), assert = require('assert');
const dir = __dirname + '/../tools/listing-extension/'; const src = (f) => fs.readFileSync(dir + f, 'utf8');
let clock = 1e12, store = {}, marks = [], sent = [], nav = [], typed = [];
let queue = { items: [], handled: {} };
const bgMsg = (m, cb) => {
  let r = null;
  if (m.type === 'whoami') r = { tabId: 7 };
  else if (m.type === 'hqGet') r = { ok: true, q: JSON.parse(JSON.stringify(queue)) };
  else if (m.type === 'hqMark') { queue.handled[m.key] = { s: m.status, note: m.note }; marks.push([m.key, m.status]); r = { ok: true }; }
  else if (m.type === 'send') { sent.push(m.url); r = { ok: true, applied: true }; }
  Promise.resolve().then(() => cb(r));
};
function load(url, bodyText, opts) {
  opts = opts || {};
  const mk = () => ({ style: {}, children: [], appendChild(c) { this.children.push(c); }, set textContent(v) { this._t = v; if (v === '') this.children = []; }, get textContent() { return this._t; }, remove() {}, set onclick(f) { this._c = f; }, get onclick() { return this._c; } });
  const body = mk(); body.innerText = bodyText;
  const L = { pathname: new URL(url).pathname }; Object.defineProperty(L, 'href', { get() { return this._href; }, set(v) { nav.push(v); this._href = v; }, configurable: true }); L._href = url;
  class HTMLInputElement { set value(v) { typed.push(v); this._v = v; } get value() { return this._v; } }
  const inp = Object.create(HTMLInputElement.prototype); Object.assign(inp, { focus() {}, dispatchEvent() {}, getBoundingClientRect: () => ({ left: 100, right: 400, top: 50, bottom: 80, width: 300, height: 30 }) });
  const sug = (opts.sugg || []).map((x, i) => ({ innerText: x.text, children: [], closest: () => null, getBoundingClientRect: () => ({ left: 110, right: 390, top: 100 + i * 40, bottom: 130 + i * 40, width: 280, height: 30 }), click() { if (x.go) L.pathname = x.go; }, dispatchEvent() {} }));
  const doc = { body, createElement: mk, querySelector: () => null, querySelectorAll: (sel) => (sel.indexOf('li,a') === 0 ? sug : ((sel.indexOf('input') >= 0 && !opts.noInput) ? [inp] : [])) };
  const ctx = {
    window: null, document: doc, location: L, console, innerWidth: 1200, innerHeight: 800, HTMLInputElement, Event: class { constructor(t) { this.type = t; } }, MouseEvent: class { constructor(t) { this.type = t; } },
    chrome: { runtime: { sendMessage: bgMsg, lastError: null }, storage: { local: { get: async (k) => ({ [k]: store[k] }), set: async (o) => { Object.assign(store, JSON.parse(JSON.stringify(o))); } } } },
    setTimeout: (fn, ms) => { clock += ms; Promise.resolve().then(fn); return 0; },
    Date: class extends Date { static now() { clock += 1; return clock; } constructor(...a) { super(...(a.length ? a : [clock])); } },
    Promise, JSON, Math, Object, Array, String, RegExp, URL,
  };
  ctx.window = ctx; ctx.self = ctx; ctx.hgCollect = async () => opts.collect === undefined ? { text: '매매 5억\n101동', n: 12 } : opts.collect;
  vm.createContext(ctx); vm.runInContext(src('chain-logic.js'), ctx); vm.runInContext(src('content-chain.js'), ctx);
  return { ctx, doc, done: new Promise((r) => setTimeout.call(global, r, 60)) };
}
const day = (d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'))(new Date(1e12));
const settle = (ms) => new Promise((r) => setTimeout(r, ms || 300));
const state = (o) => { store.hchain = Object.assign({ on: true, owner: 7, day, count: 0, fails: 0 }, o); };
(async () => {
  queue.items = [{ key: 'a|', name: '일곡엘리체프라임', dong: '', url: 'https://new.land.naver.com/complexes/111' }, { key: 'b|', name: '푸른마을', dong: '' }, { key: 'c|', name: '세번째', dong: '' }];
  // 1) 시작
  let p = load('https://new.land.naver.com/', 'x'); await p.done;
  const box = p.doc.body.children[0]; assert.ok(/대기열 3곳 중 3곳 남음/.test(box.children[0].textContent), box.children[0].textContent);
  await box.children[1].children.find((x) => x.textContent.indexOf('자동 진행 시작') >= 0).onclick(); await settle(50);
  assert.strictEqual(nav[nav.length - 1], 'https://new.land.naver.com/complexes/111'); assert.strictEqual(store.hchain.owner, 7);
  console.log('✓ 시작 → 첫 단지(번호 아는 단지)로 바로 이동');
  // 2) 단지 읽기 → 보냄 → 다음(검색)으로
  p = load('https://new.land.naver.com/complexes/111', '매매 5억 9,800'); await p.done; await settle();
  assert.deepStrictEqual(marks[0], ['a|', 'ok']); assert.strictEqual(sent.length, 1); assert.strictEqual(store.hchain.count, 1);
  assert.ok(/search\?sk=/.test(nav[nav.length - 1]), nav[nav.length - 1]); assert.strictEqual(store.hchain.cur.key, 'b|');
  console.log('✓ 단지 읽기 → 앱에 보냄 → 완료 표시 → 다음 단지 검색으로 이동');
  // 3) 검색: 검색창에 이름을 입력 → 자동완성에서 이름이 같은 단지만 눌러 이동 → 읽고 보냄
  typed.length = 0;
  p = load('https://new.land.naver.com/search?sk=x', '검색', { sugg: [{ text: '푸른마을2차\n광주 북구', go: '/complexes/998' }, { text: '푸른마을\n광주 북구 용봉동', go: '/complexes/999' }], collect: { text: '푸른마을 101동\n매매 3억', n: 5 } }); await p.done; await settle(400);
  assert.strictEqual(typed[0], '푸른마을'); assert.strictEqual(sent.length, 2); assert.deepStrictEqual(marks[1], ['b|', 'ok']); assert.strictEqual(store.hchain.cur.key, 'c|');
  console.log('✓ 검색창에 이름 입력 → 자동완성에서 같은 이름 단지(2차 아님)를 눌러 읽고 보냄');
  // 4) 단지 화면이 다른 단지면 보내지 않음(영천마을주공아파트 ↔ 영천마을주공9단지)
  queue.items = [{ key: 'y|', name: '영천마을주공아파트', dong: '월곡동' }]; queue.handled = {}; marks.length = 0; const s1 = sent.length;
  state({ cur: { key: 'y|', name: '영천마을주공아파트', dong: '월곡동', qi: 0, step: 'complex', at: clock } });
  p = load('https://new.land.naver.com/complexes/100570', '매매', { collect: { text: '집주인영천마을주공9단지 910동\n매매2억 5,700\n아파트96/75m²\n확인매물 26.11.19.', n: 1 } }); await p.done; await settle();
  assert.strictEqual(sent.length, s1); assert.deepStrictEqual(marks[0], ['y|', 'fail']); assert.ok(/다른 단지/.test(queue.handled['y|'].note));
  console.log('✓ 다른 단지 화면(9단지)이 열리면 보내지 않고 실패로 기록');
  // 5) 자동완성에 없으면 실패 기록 → 대기열 끝 → 멈춤
  queue.items = [{ key: 'c|', name: '세번째', dong: '' }]; queue.handled = {}; marks.length = 0;
  state({ cur: { key: 'c|', name: '세번째', dong: '', qi: 0, step: 'search', at: clock } });
  p = load('https://new.land.naver.com/search?sk=y', '검색', { sugg: [{ text: '다른단지\n서울', go: '/complexes/1' }] }); await p.done; await settle(400);
  assert.deepStrictEqual(marks[0], ['c|', 'fail']); assert.strictEqual(store.hchain.on, false); assert.ok(/모두 처리/.test(store.hchain.stop), store.hchain.stop);
  assert.ok(/자동완성 후보/.test(queue.handled['c|'].note));
  console.log('✓ 자동완성에 같은 단지가 없으면 후보 글자를 남기고 건너뜀, 대기열이 끝나면 멈춤');
  // 6) 캡차
  queue.handled = {}; queue.items = [{ key: 'a|', name: '일곡엘리체프라임', url: 'https://new.land.naver.com/complexes/111' }]; state({ cur: { key: 'a|', name: '일곡엘리체프라임', at: clock } });
  const n0 = sent.length; p = load('https://new.land.naver.com/complexes/111', '자동입력 방지 문자를 입력해 주세요'); await p.done;
  assert.strictEqual(store.hchain.on, false); assert.ok(/캡차/.test(store.hchain.stop)); assert.strictEqual(sent.length, n0);
  console.log('✓ 캡차 화면이 뜨면 아무것도 보내지 않고 즉시 멈춤');
  // 7) 다른 탭
  state({ owner: 99, cur: { key: 'a|', name: 'x', at: clock } }); const n1 = nav.length; p = load('https://new.land.naver.com/complexes/5', '매매 1억'); await p.done;
  assert.strictEqual(nav.length, n1); assert.strictEqual(sent.length, n0);
  console.log('✓ 시작한 탭이 아닌 다른 네이버 탭에서는 동작하지 않음');
  // 8) 5번 연속 실패 → 멈춤
  queue.handled = {}; state({ fails: 4, cur: { key: 'a|', name: '일곡엘리체프라임', at: clock } });
  p = load('https://new.land.naver.com/complexes/111', '매매 없음', { collect: { text: '', n: 0 } }); await p.done; await settle(200);
  assert.strictEqual(store.hchain.on, false); assert.ok(/연속/.test(store.hchain.stop), store.hchain.stop);
  console.log('✓ 5번 연속 못 읽으면 멈춤');
  // 9) 매물 0건 → 매물 없음(실패 아님)
  queue.handled = {}; queue.items = [{ key: 'n|', name: '삼성아파트', dong: '옥련동' }, { key: 'o|', name: '다음단지' }]; marks.length = 0;
  state({ fails: 1, cur: { key: 'n|', name: '삼성아파트', dong: '옥련동', qi: 0, step: 'complex', at: clock } });
  p = load('https://new.land.naver.com/complexes/55', '삼성아파트 옥련동 단지정보 매매 0 전세 3', { collect: { text: '', n: 0 } }); await p.done; await settle();
  assert.deepStrictEqual(marks[0], ['n|', 'none']); assert.strictEqual(store.hchain.fails, 0); assert.strictEqual(store.hchain.count, 1);
  console.log('✓ 단지 화면은 열렸는데 매물이 0건이면 실패가 아니라 매물 없음으로 처리');
  // 10) 이름 검색 결과 없음 → 이름+동으로 한 번 더 → 그래도 없으면 실패
  queue.handled = {}; queue.items = [{ key: 'd|', name: '새단지', dong: '월곡동' }]; marks.length = 0; typed.length = 0;
  state({ cur: { key: 'd|', name: '새단지', dong: '월곡동', qi: 0, step: 'search', at: clock } });
  p = load('https://new.land.naver.com/search?sk=a', '검색', { sugg: [] }); await p.done; await settle(400);
  assert.strictEqual(typed[0], '새단지'); assert.ok(/sk=%EC%83%88%EB%8B%A8%EC%A7%80%20%EC%9B%94%EA%B3%A1%EB%8F%99/.test(nav[nav.length - 1]), nav[nav.length - 1]); assert.strictEqual(store.hchain.cur.qi, 1);
  p = load('https://new.land.naver.com/search?sk=b', '검색', { sugg: [] }); await p.done; await settle(400);
  assert.strictEqual(typed[1], '새단지 월곡동'); assert.strictEqual(marks[marks.length - 1][1], 'fail');
  console.log('✓ 이름으로 못 찾으면 이름+동으로 한 번 더, 그래도 없으면 실패로 기록');
  // 11) 검색창이 없으면 구조 정보를 남기고 실패
  queue.handled = {}; queue.items = [{ key: 'z|', name: '파주한양수자인리버팰리스아파트', dong: '당동리' }]; marks.length = 0;
  state({ cur: { key: 'z|', name: '파주한양수자인리버팰리스아파트', dong: '당동리', qi: 0, step: 'search', at: clock } });
  p = load('https://new.land.naver.com/search?sk=z', '검색', { noInput: true }); await p.done; await settle(500);
  p = load('https://new.land.naver.com/search?sk=z2', '검색', { noInput: true }); await p.done; await settle(500);   // 이름 → 이름+동 두 번 시도
  assert.ok(/검색창을 못 찾음 구조:/.test(queue.handled['z|'].note), queue.handled['z|'].note || '(note 없음, 다른 검색어로 재시도 중일 수 있음)');
  console.log('✓ 검색창을 못 찾으면 화면 구조 정보를 기록에 남김');
  console.log('모두 통과');
  process.exit(0);
})().catch((e) => { console.error('실패:', e); process.exit(1); });
