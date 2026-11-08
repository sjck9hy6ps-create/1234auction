/* 탱크옥션 상세 → 권리분석 읽기 회귀 시험 (2026-11-01)
   - public/index.html의 읽기 함수(rightsParseFull 등)를 그대로 꺼내 실제 수집 원문(tests/fixtures-private/*.txt)에 돌림
   - 읽은 결과를 ① 원문에서 따로 다시 읽은 값(독립 추출)과 대조 ② 이전에 확인한 결과(tests/snapshots/rights-snapshot.json)와 대조
   - 원문에는 실명이 있어 git에 올리지 않음(.gitignore). 새 원문을 넣으려면 파일을 fixtures-private에 추가하고 --update 로 기준 결과를 다시 저장
   사용: node tests/rights-regression.cjs [--update] */
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = path.join(__dirname, '..'), FIX = path.join(__dirname, 'fixtures-private'), SNAP = path.join(__dirname, 'snapshots', 'rights-snapshot.json');
const html = fs.readFileSync(path.join(ROOT, 'public', 'index.html'), 'utf8');
function grab(i) { let d = 0, k = html.indexOf('{', i); for (;; k++) { const c = html[k]; if (c === '{') d++; else if (c === '}') { d--; if (d === 0) break; } } return html.slice(i, k + 1); }
const funcs = [...html.matchAll(/^(?:async )?function ((?:myr|rights|parseTank|normalizeCase)\w*)\(/gm)].map((m) => grab(m.index));
const consts = [...html.matchAll(/^var (?:MYR|RIGHTS)\w* = [^;]*;/gm)].map((m) => m[0]);
const ctx = {}; vm.createContext(ctx); vm.runInContext(consts.join('\n') + '\n' + funcs.join('\n') + '\nthis.rightsParseFull = rightsParseFull; this.myrMaskTabs = myrMaskTabs; this.rightsIntegrity = rightsIntegrity;', ctx);

const num = (s) => (/\d/.test(s || '') ? parseInt(String(s).replace(/\D/g, ''), 10) : 0);
const dt = (s) => { const m = String(s || '').match(/(\d{4})[-.](\d{1,2})[-.](\d{1,2})/); return m ? `${m[1]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}` : ''; };
function indepTenants(t) {
  const i = t.indexOf('임차인 현황'); if (i < 0) return [];
  const e1 = t.indexOf('\n\t계', i), e2 = t.indexOf('\n기타사항', i), e = Math.min(...[e1, e2].filter((x) => x > 0), t.length), sec = t.slice(i, e);
  const st = [...sec.matchAll(/(?:^|\n)(\d{1,2})\t([^\t\n]{1,60})\t/g)];
  return st.map((m, k) => {
    const ch = sec.slice(m.index, k + 1 < st.length ? st[k + 1].index : sec.length), g = (re) => (ch.match(re) || [])[1];
    return { name: m[2].trim(), moveIn: dt(g(/전입\s*:\s*(\d{4}-\d\d-\d\d|미상)/)), fixed: dt(g(/확정\s*:\s*(\d{4}-\d\d-\d\d|미상|없음)/)), dist: dt(g(/배당\s*:\s*(\d{4}-\d\d-\d\d|없음|미상)/)), deposit: num(g(/보\s*:\s*([\d,]+)원/)), rent: num(g(/월\s*:\s*([\d,]+)원/)), depUnknown: /보\s*:\s*미상/.test(ch) };
  });
}
function indepRegistry(t) {
  const i = t.indexOf('건물등기'); if (i < 0) return []; let sec = t.slice(i);
  for (const stop of ['\n참고/주의', '\n주의사항', '\n권리분석요약']) { const e = sec.indexOf(stop); if (e > 0) sec = sec.slice(0, e); }
  const ms = [...sec.matchAll(/(?:^|\n)(갑|을)\((\d+)\)\t(\d{4}-\d\d-\d\d)\n\t([^\t\n]*)\t([^\t\n]*)\t([^\t\n]*)/g)];
  return ms.map((m, k) => {
    const ch = sec.slice(m.index, k + 1 < ms.length ? ms[k + 1].index : sec.length).trimEnd(); let amt = /^[\d,]+$/.test(m[6].trim()) ? num(m[6]) : 0;
    if (!amt && ch.includes('청구금액')) { const c = ch.match(/청구금액\s*\n?\s*([\d,]+)/); if (c) amt = num(c[1]); }
    return { seq: `${m[1]}(${m[2]})`, date: m[3], type: m[4].trim(), amount: amt, base: ch.includes('말소기준등기'), extinguished: /소멸\s*$/.test(ch) };
  });
}
function summary(R) {
  return { tenants: R.tenants.map((x) => [x.moveIn, x.fixed, x.distDate, x.deposit, x.rent, x.tankStanding]), unknown: (R.unknownOccupants || []).map((u) => [u.moveIn, u.tankStanding, !!u.senior, !!u.ownerNote, !!u.family]),
    registry: R.registry.map((x) => [x.seq, x.date, x.type, x.amount, x.base, x.extinguished, x.assumed]), minBidWon: R.minBidWon, appraisalWon: R.appraisalWon, tankSaleDate: R.tankSaleDate || '', tankSoldWon: R.tankSoldWon || 0,
    baseDate: R.baseDate, distDeadline: R.distDeadline, claimTotalWon: R.claimTotalWon || 0, tankTenantN: R.tankTenantN == null ? null : R.tankTenantN, warnings: R.warnings.length };
}
const files = fs.existsSync(FIX) ? fs.readdirSync(FIX).filter((f) => f.endsWith('.txt')).sort() : [];
if (!files.length) { console.log('원문 파일이 없어 시험을 건너뜀 (tests/fixtures-private/*.txt)'); process.exit(0); }
const update = process.argv.includes('--update'), snapOld = fs.existsSync(SNAP) ? JSON.parse(fs.readFileSync(SNAP, 'utf8')) : {}, snapNew = {}; let fail = 0, rows = 0, ten = 0;
files.forEach((f) => {
  const key = f.replace('.txt', ''), t = fs.readFileSync(path.join(FIX, f), 'utf8'), iss = []; let R;
  try { R = ctx.rightsParseFull(ctx.myrMaskTabs(t)); } catch (e) { console.log('❌', key, '읽기 오류', e.message); fail++; return; }
  // ① 독립 추출과 대조
  const it = indepTenants(t); ten += it.length;
  const un = R.unknownOccupants || [];
  if (R.tankTenantN != null && R.tankTenantN !== R.tenants.length && R.tankTenantN !== R.tenants.length + un.length) iss.push(`임차인 수 원문표기 ${R.tankTenantN} ≠ 읽음 ${R.tenants.length}+${un.length}`);
  if (it.length !== R.tenants.length + un.length) iss.push(`임차인 행 ${it.length} ≠ 읽음 ${R.tenants.length + un.length}`);
  it.forEach((x, k) => {
    if (x.depUnknown) { const u = un.filter((y) => y.moveIn === x.moveIn)[0]; if (!u) iss.push(`보증금 미상 점유자 누락(전입 ${x.moveIn})`); return; }
    const s = R.tenants.filter((y) => y.moveIn === x.moveIn && y.deposit === x.deposit)[0]; if (!s) { iss.push(`임차인 값 불일치(전입 ${x.moveIn}, 보증금 ${x.deposit})`); return; }
    if ((s.rent || 0) !== x.rent) iss.push(`월세 원문 ${x.rent} ≠ 읽음 ${s.rent}`); if ((s.fixed || '') !== (x.fixed || '')) iss.push(`확정일 원문 ${x.fixed} ≠ 읽음 ${s.fixed}`); if ((s.distDate || '') !== (x.dist || '')) iss.push(`배당일 원문 ${x.dist} ≠ 읽음 ${s.distDate}`);
  });
  const ir = indepRegistry(t); rows += ir.length;
  if (ir.length !== R.registry.length) iss.push(`등기 행 원문 ${ir.length} ≠ 읽음 ${R.registry.length}`);
  ir.forEach((x) => { const s = R.registry.filter((y) => y.seq === x.seq)[0]; if (!s) { iss.push(`등기 ${x.seq} 누락`); return; }
    ['date', 'type', 'amount', 'base', 'extinguished'].forEach((p) => { if (x[p] !== s[p]) iss.push(`등기 ${x.seq} ${p} 원문 ${x[p]} ≠ 읽음 ${s[p]}`); }); });
  const hm = t.match(/최저가(?:격)?\s*\((\d+(?:\.\d+)?)%\)\s*([\d,]+)/); if (hm && num(hm[2]) !== R.minBidWon) iss.push(`최저가 원문 ${hm[2]} ≠ 읽음 ${R.minBidWon}`); if (!hm) iss.push('헤더 최저가를 못 찾음');
  const am = t.match(/감정가(?:격)?\s+([\d,]{7,})/); if (am && num(am[1]) !== R.appraisalWon) iss.push(`감정가 원문 ${am[1]} ≠ 읽음 ${R.appraisalWon}`);
  const sm = t.match(/매각일자\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})/); if (sm && dt(sm.slice(1, 4).join('-')) !== R.tankSaleDate) iss.push(`매각일 원문 ${sm[0]} ≠ 읽음 ${R.tankSaleDate}`);
  if (/매각가\s*\(\d+(?:\.\d+)?%\)\s*[\d,]+/.test(t.slice(0, 2500)) !== !!R.tankSoldWon) iss.push('낙찰(매각가) 표시 인식이 원문과 달라요');
  const bm = t.match(/말소기준일\(소액\)\s*:\s*(\d{4}-\d\d-\d\d)/); if (bm && bm[1] !== R.baseDate) iss.push(`말소기준일 원문 ${bm[1]} ≠ 읽음 ${R.baseDate}`);
  const dm = t.match(/배당요구종기일\s*:\s*(\d{4}-\d\d-\d\d)/); if (dm && R.distDeadline && dm[1] !== R.distDeadline) iss.push(`배당종기 원문 ${dm[1]} ≠ 읽음 ${R.distDeadline}`);
  const cm = t.match(/채권합계금액\s*:\s*([\d,]+)원/); if (cm && num(cm[1]) !== (R.claimTotalWon || 0)) iss.push(`채권합계 원문 ${cm[1]} ≠ 읽음 ${R.claimTotalWon}`);
  // ③ 저장 직전 검증(rightsIntegrity)이 정상 자료를 막지 않는지
  const ig = ctx.rightsIntegrity(ctx.myrMaskTabs(t), R); ig.bad.forEach((x) => iss.push('저장 검증이 정상 자료를 막음: ' + x));
  // ② 기준 결과와 대조
  const sNow = summary(R); snapNew[key] = sNow;
  if (!update && snapOld[key] && JSON.stringify(snapOld[key]) !== JSON.stringify(sNow)) iss.push('이전에 확인한 읽기 결과와 달라졌어요(의도한 변경이면 --update)');
  if (!update && !snapOld[key]) iss.push('기준 결과가 없어요(--update 로 저장)');
  if (iss.length) { fail++; console.log('❌', key); iss.slice(0, 8).forEach((x) => console.log('    ' + x)); }
});
// ④ 일부러 망가뜨린 자료는 저장 검증이 막아야 함 (등기 행 삭제·최저가 0·임차인 행 삭제)
{
  const f0 = files.filter((f) => /^2025-570/.test(f))[0] || files[0], t0 = fs.readFileSync(path.join(FIX, f0), 'utf8'), R0 = ctx.rightsParseFull(ctx.myrMaskTabs(t0)); let ok = true;
  const mut = [['등기 행 누락', (R) => { R.registry.pop(); }], ['최저가 0', (R) => { R.minBidWon = 0; }], ['임차인 행 누락', (R) => { R.tenants.pop(); R.tankTenantN = 5; }], ['채권합계 불일치', (R) => { R.claimTotalWon += 1; }]];
  mut.forEach(([nm, fn]) => { const R = JSON.parse(JSON.stringify(R0)); fn(R); if (!ctx.rightsIntegrity(ctx.myrMaskTabs(t0), R).bad.length) { console.log('❌ 저장 검증이 못 잡음:', nm); ok = false; fail++; } });
  if (ok) console.log('저장 검증: 일부러 망가뜨린 자료 ' + mut.length + '종을 모두 막음');
}
if (update) { fs.mkdirSync(path.dirname(SNAP), { recursive: true }); fs.writeFileSync(SNAP, JSON.stringify(snapNew, null, 1)); console.log('기준 결과 저장:', Object.keys(snapNew).length, '건'); }
console.log(`${fail ? '실패' : '통과'}: ${files.length}건 (임차인 ${ten}명, 등기 ${rows}행 원문 대조)${fail ? ' - 문제 ' + fail + '건' : ''}`);
process.exit(fail && !update ? 1 : 0);

