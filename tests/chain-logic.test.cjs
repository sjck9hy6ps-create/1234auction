// 호가 자동 진행 핵심 로직 시험(네이버 화면 없이): node tests/chain-logic.test.cjs
const vm = require('vm'), fs = require('fs'), ctx = { module: { exports: {} } }; vm.runInNewContext(fs.readFileSync(__dirname + '/../tools/listing-extension/chain-logic.js', 'utf8'), ctx); const L = ctx.module.exports; const assert = require('assert'); let n = 0; const t = (name, fn) => { fn(); n++; console.log('✓', name); };
const links = [
  { href: 'https://new.land.naver.com/complexes/111', text: '일곡엘리체프라임', ctx: '광주 북구 일곡동 아파트' },
  { href: 'https://new.land.naver.com/complexes/222', text: '일곡엘리체', ctx: '광주 북구 용봉동' },
  { href: 'https://new.land.naver.com/complexes/333', text: '일곡동 푸르지오', ctx: '광주 북구 일곡동' },
  { href: 'https://new.land.naver.com/articles/9', text: '일곡엘리체프라임', ctx: '' },
];
t('이름이 정확히 같은 단지 선택', () => assert.strictEqual(L.pickComplexLink(links, { name: '일곡엘리체프라임', dong: '일곡동' }), 'https://new.land.naver.com/complexes/111'));
t('(주상복합)·아파트 접미사·공백 무시', () => assert.strictEqual(L.pickComplexLink([{ href: '/complexes/5', text: '두산위브 더 제니스', ctx: '' }], { name: '두산위브더제니스(주상복합)아파트', dong: '' }), '/complexes/5'));
t('이름이 없으면 엉뚱한 단지를 열지 않음(null)', () => assert.strictEqual(L.pickComplexLink(links, { name: '전혀다른단지', dong: '' }), null));
t('짧은 이름 부분일치 금지(2글자)', () => assert.strictEqual(L.pickComplexLink([{ href: '/complexes/7', text: '푸르지오', ctx: '' }], { name: '푸르', dong: '' }), null));
t('동이 맞는 쪽 우선', () => assert.strictEqual(L.pickComplexLink([{ href: '/complexes/1', text: '현대아파트', ctx: '서울 강남구 압구정동' }, { href: '/complexes/2', text: '현대아파트', ctx: '경기 수원시 영통동' }], { name: '현대아파트', dong: '영통동' }), '/complexes/2'));
t('단지 링크가 아닌 것은 무시', () => assert.strictEqual(L.pickComplexLink([{ href: '/articles/1', text: '일곡엘리체프라임', ctx: '' }], { name: '일곡엘리체프라임' }), null));
const q = { items: [{ key: 'a|x', name: 'A' }, { key: 'b|y', name: 'B' }, { name: 'C', dong: 'z' }] };
t('처리 안 한 첫 항목', () => assert.strictEqual(L.nextItem(q, { 'a|x': 1 }).key, 'b|y'));
t('키 없는 항목은 이름|동으로 키 생성', () => assert.strictEqual(L.nextItem(q, { 'a|x': 1, 'b|y': 1 }).key, 'c|z'));
t('모두 처리하면 null', () => assert.strictEqual(L.nextItem(q, { 'a|x': 1, 'b|y': 1, 'c|z': 1 }), null));
t('로그인 주소 감지', () => assert.ok(L.blockedReason('https://nid.naver.com/nidlogin.login', '')));
t('캡차 문구 감지', () => assert.ok(L.blockedReason('https://new.land.naver.com/complexes/1', '자동입력 방지 문자를 입력해 주세요')));
t('접속 제한 문구 감지', () => assert.ok(L.blockedReason('https://new.land.naver.com/x', '과도한 접속으로 이용이 제한되었습니다')));
t('정상 화면은 통과', () => assert.strictEqual(L.blockedReason('https://new.land.naver.com/complexes/1', '매매 5억 9,800 101동 12/20층'), null));
t('쉬는 시간 20~60초 범위', () => { for (let i = 0; i < 200; i++) { const v = L.jitter(20000, 60000); assert.ok(v >= 20000 && v <= 60000); } assert.strictEqual(L.jitter(20000, 60000, 0), 20000); assert.strictEqual(L.jitter(20000, 60000, 1), 60000); });
t('하루 30곳 도달 시 멈춤', () => { assert.strictEqual(L.shouldStop({ count: 29, fails: 0 }, 30, 3), null); assert.ok(L.shouldStop({ count: 30, fails: 0 }, 30, 3)); });
t('3번 연속 실패 시 멈춤', () => { assert.strictEqual(L.shouldStop({ count: 5, fails: 2 }, 30, 3), null); assert.ok(L.shouldStop({ count: 5, fails: 3 }, 30, 3)); });
t('날짜 키', () => assert.strictEqual(L.dayKey(new Date(2026, 10, 9)), '2026-11-09'));
t('지도 표시 후보: 이름 같은 것 우선, 같은 이름이면 화면 가운데에 가까운 것', () => {
  const c = [{ n: L.normName('금오아파트'), x: 100, y: 100 }, { n: L.normName('금오아파트'), x: 640, y: 400 }, { n: L.normName('금오 아파트 2차'), x: 650, y: 400 }, { n: L.normName('이마트24'), x: 640, y: 400 }];
  const r = L.rankCandidates(c, '금오아파트', 640, 400); assert.strictEqual(r.length, 2); assert.strictEqual(r[0].x, 640); assert.strictEqual(r[0].exact, 0);
});
t('지도 표시 후보: 이름이 다르면 비어 있음(엉뚱한 단지를 누르지 않음)', () => assert.strictEqual(L.rankCandidates([{ n: L.normName('해링턴플레이스'), x: 1, y: 1 }], '금오아파트', 0, 0).length, 0));
t('같은 단지 판단: 9단지·2차가 붙으면 다른 단지, 동 이름(비동·910동)은 무시', () => {
  assert.ok(L.sameComplex('집주인보라맨션 비동', '보라맨션')); assert.ok(L.sameComplex('보라맨션 에이동', '보라맨션')); assert.ok(L.sameComplex('영천마을주공 910동', '영천마을주공아파트'));
  assert.ok(!L.sameComplex('집주인영천마을주공9단지 910동', '영천마을주공아파트')); assert.ok(!L.sameComplex('푸른마을2차', '푸른마을')); assert.ok(!L.sameComplex('총 2동', '보라맨션'));
});
t('보내기 전 확인: 머리줄이 다른 단지면 false, 머리줄이 없으면 null', () => {
  assert.strictEqual(L.headersMatch('집주인영천마을주공9단지 910동\n매매2억 5,700\n확인매물 26.11.19.', '영천마을주공아파트'), false);
  assert.strictEqual(L.headersMatch('보라맨션 비동\n매매3억\n확인매물\n보라맨션 에이동\n매매5억', '보라맨션'), true);
  assert.strictEqual(L.headersMatch('매매 5억\n101동', '보라맨션'), null);
});
t('자동완성 후보: 이름이 같은 단지 중 주소 동·리가 맞는 것', () => {
  const c = [{ first: '주공아파트', full: '주공아파트 경기 의정부시 가능동' }, { first: '주공아파트', full: '주공아파트 경기 의정부시 신곡동' }, { first: '주공아파트2단지', full: '주공아파트2단지 경기 의정부시 신곡동' }];
  assert.strictEqual(L.pickSuggestion(c, { name: '주공아파트', addr: '경기도 의정부시 신곡동 754', dong: '신곡동' }), 1);
  assert.strictEqual(L.pickSuggestion([{ first: '다른단지', full: '' }], { name: '주공아파트' }), -1);
});
t('같은 단지를 번호 순서만 다르게 적어도 같게 봄(장암2단지주공↔장암주공2단지), 9단지 차이는 다르게', () => {
  assert.ok(L.sameComplex('장암주공2단지 101동', '장암2단지주공아파트')); assert.ok(L.sameComplex('장암주공2단지아파트', '장암2단지주공아파트'));
  assert.ok(!L.sameComplex('장암주공1단지 105동', '장암2단지주공아파트')); assert.ok(!L.sameComplex('영천마을주공9단지 910동', '영천마을주공아파트'));
});
console.log(n + '개 통과');
