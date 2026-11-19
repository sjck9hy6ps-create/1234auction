// 호가 자동 진행 흐름 시험(가짜 크롬·가짜 화면): node tests/chain-flow.test.cjs  - 페이지가 바뀔 때마다 스크립트를 다시 실행해 이어지는지 확인
const vm = require('vm'), fs = require('fs'), assert = require('assert');
const dir = __dirname + '/../tools/listing-extension/'; const src = (f) => fs.readFileSync(dir + f, 'utf8');
let clock = 1e12, store = {}, marks = [], sent = [], nav = [], queue = { items: [{ key: 'a|', name: '일곡엘리체프라임', dong: '', url: 'https://new.land.naver.com/complexes/111' }, { key: 'b|', name: '푸른마을', dong: '' }, { key: 'c|', name: '세번째', dong: '' }], handled: {} };
const bgMsg = (m, cb) => {
  let r = null;
  if (m.type === 'whoami') r = { tabId: 7 };
  else if (m.type === 'hqGet') r = { ok: true, q: JSON.parse(JSON.stringify(queue)) };
  else if (m.type === 'hqMark') { queue.handled[m.key] = { s: m.status }; marks.push([m.key, m.status]); r = { ok: true }; }
  else if (m.type === 'send') { sent.push(m.url); r = { ok: true, applied: true }; }
  Promise.resolve().then(() => cb(r));
};
function load(url, bodyText, opts) {
  opts = opts || {};
  const els = []; const mk = () => ({ style: {}, children: [], appendChild(c) { this.children.push(c); }, set textContent(v) { this._t = v; if (v === '') this.children = []; }, get textContent() { return this._t; }, remove() {}, set onclick(f) { this._c = f; }, get onclick() { return this._c; } });
  const body = mk(); body.innerText = bodyText;
  const loc = { href: url, pathname: new URL(url).pathname, set _h(v) {} };
  const L = { href: url, pathname: new URL(url).pathname }; Object.defineProperty(L, 'href', { get() { return this._href; }, set(v) { nav.push(v); this._href = v; }, configurable: true }); L._href = url;
  const doc = { body, createElement: mk, querySelectorAll: (sel) => (opts.links || []).map((l) => ({ href: l.href, innerText: l.text, textContent: l.text, closest: () => ({ innerText: l.ctx || '' }) })) };
  const ctx = {
    window: null, document: doc, location: L, console,
    chrome: { runtime: { sendMessage: bgMsg, lastError: null }, storage: { local: { get: async (k) => ({ [k]: store[k] }), set: async (o) => { Object.assign(store, JSON.parse(JSON.stringify(o))); } } } },
    setTimeout: (fn, ms) => { clock += ms; Promise.resolve().then(fn); return 0; },
    Date: class extends Date { static now() { clock += 1; return clock; } constructor(...a) { super(...(a.length ? a : [clock])); } },
    Promise, JSON, Math, Object, Array, String, RegExp, URL,
  };
  ctx.window = ctx; ctx.self = ctx; ctx.hgCollect = async () => opts.collect === undefined ? { text: '매매 5억\n101동', n: 12 } : opts.collect;
  vm.createContext(ctx); vm.runInContext(src('chain-logic.js'), ctx); vm.runInContext(src('content-chain.js'), ctx);
  return { ctx, doc, done: new Promise((r) => setTimeout.call(global, r, 60)) };
}
const click = async (box, label) => { const b = box.children[1].children.find((x) => x.textContent.indexOf(label) >= 0); assert.ok(b, label + ' 버튼 없음'); await b.onclick(); await new Promise((r) => setTimeout(r, 30)); };
(async () => {
  // 1) 대기열 있고 진행 중 아님 → 시작 버튼
  let p = load('https://new.land.naver.com/', 'x'); await p.done;
  const box = p.doc.body.children[0]; assert.ok(/대기열 3곳 중 3곳 남음/.test(box.children[0].textContent), box.children[0].textContent);
  await click(box, '자동 진행 시작'); assert.strictEqual(nav[nav.length - 1], 'https://new.land.naver.com/complexes/111'); assert.strictEqual(store.hchain.owner, 7);
  console.log('✓ 시작 → 첫 단지(번호 아는 단지)로 바로 이동');
  // 2) 단지 페이지: 읽고 보내고 완료 표시 → 다음(검색)으로 이동
  p = load('https://new.land.naver.com/complexes/111', '매매 5억 9,800'); await p.done; await new Promise((r) => setTimeout(r, 100));
  assert.deepStrictEqual(marks[0], ['a|', 'ok']); assert.strictEqual(sent.length, 1); assert.strictEqual(store.hchain.count, 1);
  assert.ok(/search\?sk=/.test(nav[nav.length - 1]), nav[nav.length - 1]); assert.strictEqual(store.hchain.cur.key, 'b|');
  console.log('✓ 단지 읽기 → 앱에 보냄 → 완료 표시 → 다음 단지 검색으로 이동');
  // 3) 검색 화면: 이름 맞는 링크로 들어감
  p = load('https://new.land.naver.com/search?sk=x', '검색', { links: [{ href: 'https://new.land.naver.com/complexes/999', text: '푸른마을', ctx: '' }] }); await p.done; await new Promise((r) => setTimeout(r, 100));
  assert.strictEqual(nav[nav.length - 1], 'https://new.land.naver.com/complexes/999');
  console.log('✓ 검색 결과에서 이름이 맞는 단지로 들어감');
  // 4) 같은 단지 페이지 새로고침 → 중복 전송 안 함(sent 플래그는 다음 단계에서 설정되므로 정상 흐름 먼저)
  p = load('https://new.land.naver.com/complexes/999', '매매 3억', { collect: { text: '매매 3억', n: 5 } }); await p.done; await new Promise((r) => setTimeout(r, 100));
  assert.strictEqual(sent.length, 2); assert.strictEqual(store.hchain.cur.key, 'c|');
  console.log('✓ 두 번째 단지 완료 후 세 번째로');
  // 5) 세 번째: 검색에서 못 찾으면 실패 기록 후 다음으로(대기열 끝) → 멈춤
  p = load('https://new.land.naver.com/search?sk=y', '검색', { links: [] }); await p.done; await new Promise((r) => setTimeout(r, 200));
  assert.deepStrictEqual(marks[marks.length - 1], ['c|', 'fail']); assert.strictEqual(store.hchain.on, false); assert.ok(/모두 처리/.test(store.hchain.stop), store.hchain.stop);
  console.log('✓ 단지를 못 찾으면 건너뛰고, 대기열이 끝나면 멈춤');
  // 6) 캡차 화면 → 즉시 멈춤
  queue.handled = {}; store.hchain = { on: true, owner: 7, day: new Date(clock).toISOString().slice(0, 10), count: 0, fails: 0, cur: { key: 'a|', name: '일곡엘리체프라임', at: clock } };
  const day = (d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'))(new Date(clock)); store.hchain.day = day;
  const n0 = sent.length; p = load('https://new.land.naver.com/complexes/111', '자동입력 방지 문자를 입력해 주세요'); await p.done;
  assert.strictEqual(store.hchain.on, false); assert.ok(/캡차/.test(store.hchain.stop)); assert.strictEqual(sent.length, n0);
  console.log('✓ 캡차 화면이 뜨면 아무것도 보내지 않고 즉시 멈춤');
  // 7) 다른 탭에서는 동작 안 함
  store.hchain = { on: true, owner: 99, day, count: 0, fails: 0, cur: { key: 'a|', name: 'x', at: clock } }; const n1 = nav.length; p = load('https://new.land.naver.com/complexes/5', '매매 1억'); await p.done;
  assert.strictEqual(nav.length, n1); assert.strictEqual(sent.length, n0);
  console.log('✓ 시작한 탭이 아닌 다른 네이버 탭에서는 동작하지 않음');
  // 8) 3번 연속 실패 → 멈춤
  queue.handled = {}; store.hchain = { on: true, owner: 7, day, count: 0, fails: 2, cur: { key: 'a|', name: '일곡엘리체프라임', at: clock } };
  p = load('https://new.land.naver.com/complexes/111', '매매 없음', { collect: { text: '', n: 0 } }); await p.done; await new Promise((r) => setTimeout(r, 200));
  assert.strictEqual(store.hchain.on, false); assert.ok(/연속/.test(store.hchain.stop), store.hchain.stop);
  console.log('✓ 3번 연속 못 읽으면 멈춤');
  console.log('모두 통과');
  process.exit(0);
})().catch((e) => { console.error('실패:', e); process.exit(1); });
