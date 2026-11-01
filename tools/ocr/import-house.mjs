/* 세대열람(전입세대확인서) 그림 PDF 글자 인식 → 앱 반영 + 줄인 원본 그림 첨부 (2026-11-01)
   확장프로그램이 그림뿐인 세대열람 PDF를 ~/Downloads/tank-ocr/<tid>_house_p1.png 로 저장하면, 맥의 Vision(tools/ocr/ocr-vision.swift)으로 글자를 읽고
   앱의 읽기 함수(myrHouseRead)로 분석해서 이미 반영된 권리분석(rights.docs.houseRead)에 넣음.
   - 그림 속 '지번 주소 + 동·호'로 물건을 찾음(같은 주소가 여럿이거나 못 찾으면 건너뛰고 알려 줌)
   - 글자 인식은 틀릴 수 있어 houseRead.ocr=true 로 표시(점검표에서 원본 그림 확인 안내). 이미 인식한 그림(같은 파일 시각)은 다시 글자 인식하지 않음
   - 원본 그림은 위쪽 60%만 잘라 가로 1,100px JPEG(장당 약 50KB)로 줄여 앱 저장소(kind=houseImg)에 올림. 앱은 점검표의 '원본 그림 보기'를 눌렀을 때만 한 장씩 받아 옴(목록·시작 속도 영향 없음). 맥의 sips 사용
   사용: node tools/ocr/import-house.mjs [--dry-run] [--dir <그림 폴더>] [--site <앱 주소>] */
import fs from 'fs'; import os from 'os'; import path from 'path'; import vm from 'vm'; import { execFileSync } from 'child_process'; import { fileURLToPath } from 'url';
const here = path.dirname(fileURLToPath(import.meta.url)), ROOT = path.join(here, '..', '..');
const args = process.argv.slice(2), dry = args.includes('--dry-run');
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const DIR = opt('--dir', path.join(os.homedir(), 'Downloads', 'tank-ocr')), SITE = opt('--site', 'https://1234auction.vercel.app');
// 앱의 읽기 함수 꺼내기
const html = fs.readFileSync(path.join(ROOT, 'public', 'index.html'), 'utf8');
const grab = (i) => { let d = 0, k = html.indexOf('{', i); for (;; k++) { const c = html[k]; if (c === '{') d++; else if (c === '}') { d--; if (d === 0) break; } } return html.slice(i, k + 1); };
const funcs = [...html.matchAll(/^(?:async )?function ((?:myr|rights)\w*)\(/gm)].map((m) => grab(m.index)), consts = [...html.matchAll(/^var (?:MYR|RIGHTS)\w* = [^;]*;/gm)].map((m) => m[0]);
const ctx = {}; vm.createContext(ctx); vm.runInContext(consts.join('\n') + '\n' + funcs.join('\n') + '\nthis.myrHouseRead = myrHouseRead; this.rightsDate = rightsDate;', ctx);
// 그림 줄이기(맥 sips): 위 60%만 잘라 가로 1100px, JPEG 품질 55
function shrink(png) {
  const tmp = path.join(os.tmpdir(), 'hi_' + path.basename(png, '.png') + '.jpg'), crop = path.join(os.tmpdir(), 'hc_' + path.basename(png));
  const h = parseInt(execFileSync('sips', ['-g', 'pixelHeight', png], { encoding: 'utf8' }).match(/pixelHeight:\s*(\d+)/)[1], 10), w = parseInt(execFileSync('sips', ['-g', 'pixelWidth', png], { encoding: 'utf8' }).match(/pixelWidth:\s*(\d+)/)[1], 10);
  execFileSync('sips', ['--cropToHeightWidth', String(Math.round(h * 0.6)), String(w), '--cropOffset', '0', '0', png, '--out', crop], { stdio: 'ignore' });
  execFileSync('sips', ['-Z', '1100', '-s', 'format', 'jpeg', '-s', 'formatOptions', '55', crop, '--out', tmp], { stdio: 'ignore' });
  const b = fs.readFileSync(tmp); fs.unlinkSync(tmp); fs.unlinkSync(crop);
  return { dataUrl: 'data:image/jpeg;base64,' + b.toString('base64'), bytes: b.length };
}
// 글자 인식 도구 준비
const BIN = path.join(os.tmpdir(), 'ocr-vision');
if (!fs.existsSync(BIN)) { console.log('글자 인식 도구를 만드는 중...'); execFileSync('swiftc', ['-O', path.join(here, 'ocr-vision.swift'), '-o', BIN], { stdio: 'inherit' }); }
if (!fs.existsSync(DIR)) { console.log('그림 폴더가 없어요:', DIR); process.exit(1); }
const files = fs.readdirSync(DIR).filter((f) => /_house_p\d+\.png$/.test(f)).sort();
console.log(`세대열람 그림 ${files.length}장 (${DIR})`);
const auc = await fetch(SITE + '/api/auction?kind=auctions').then((r) => r.json());
const ents = auc.filter((a) => a.rights && a.rights.via === 'extension' && a.rights.tankAddr);
const toSave = [], skipped = [], imgJobs = [];
for (const f of files) {
  const mtime = Math.floor(fs.statSync(path.join(DIR, f)).mtimeMs);
  const text = execFileSync(BIN, [path.join(DIR, f)], { encoding: 'utf8', maxBuffer: 1 << 24 });
  const jb = (text.match(/지번\s*주소\s*\t?([^\n]+)/) || [])[1] || '', dm = jb.match(/([가-힣0-9]+(?:동|리|가))\s+(\d+(?:-\d+)?)/), ho = jb.match(/(\d+)호/), dn = jb.replace(/^.*?\d+(?:-\d+)?\s*/, '').match(/(\d+)동/);
  if (!dm) { skipped.push([f, '그림에서 지번 주소를 못 읽음']); continue; }
  const bj = dm[2].replace(/-0$/, '');  // 856-0 = 856
  let cand = ents.filter((a) => a.rights.tankAddr.includes(dm[1] + ' ' + bj + ' ') || a.rights.tankAddr.includes(dm[1] + ' ' + bj));
  if (ho) cand = cand.filter((a) => a.rights.tankAddr.includes(ho[1] + '호')) || cand;
  if (dn && cand.length > 1) { const c2 = cand.filter((a) => a.rights.tankAddr.includes(dn[1] + '동')); if (c2.length) cand = c2; }
  let looseNote = '';
  if (!cand.length && ho && dn) {  // 글자 인식이 동 이름을 한 글자 잘못 읽는 경우(삼숭동→삼송동): 번지·동·호가 모두 같은 물건이 하나뿐이고, 그림의 전입일이 앱의 임차인 전입일과 겹칠 때만 같은 물건으로 봄
    const bre = new RegExp('(^|\\s)' + bj.replace(/-/g, '\\-') + '(\\s|$)'), dates0 = new Set((text.match(/\d{4}-\d{2}-\d{2}/g) || []));
    const loose = ents.filter((a) => bre.test(a.rights.tankAddr) && a.rights.tankAddr.includes(dn[1] + '동') && a.rights.tankAddr.includes(ho[1] + '호') && (a.rights.tenants || []).concat(a.rights.unknownOccupants || []).some((t) => t.moveIn && dates0.has(t.moveIn)));
    if (loose.length === 1) { cand = loose; looseNote = '그림의 동 이름(' + dm[1] + ')이 앱(' + (loose[0].rights.tankAddr.match(/([가-힣0-9]+(?:동|리|가))\s+\d/) || [])[1] + ')과 달라요 - 번지·동·호·전입일이 같아 같은 물건으로 봄'; }
  }
  if (cand.length !== 1) { skipped.push([f, cand.length ? '같은 주소 물건이 ' + cand.length + '건이라 구분 못 함' : '앱에 이 주소의 탱크옥션 수집 물건이 없음 (' + jb.trim().slice(0, 40) + ')']); continue; }
  const a = cand[0], R = a.rights; R.docs = R.docs || {};
  if (R.docs.houseRead && R.docs.houseRead.ocr && R.docs.houseRead.ocrMtime === mtime) {
    if (R.docs.houseRead.imgAt) { skipped.push([f, '이미 반영됨(' + a.caseNo + ')']); continue; }
    imgJobs.push({ a, f, mtime }); R.docs.houseRead.imgAt = Date.now(); toSave.push(a); console.log(`${dry ? '[미리보기] ' : ''}${a.caseNo} ${a.name || ''}: 그림만 첨부 (${f})`); continue;  // 글자 인식은 이미 했고 그림만 올림
  }
  const hr = ctx.myrHouseRead(text); if (hr.state !== 'ok') { skipped.push([f, '글자는 읽었지만 세대열람 내용으로 보이지 않음']); continue; }
  if (looseNote) hr.addrNote = looseNote;
  hr.ocr = true; hr.ocrAt = Date.now(); hr.ocrMtime = mtime; hr.ocrFile = f; hr.imgAt = Date.now();
  imgJobs.push({ a, f, mtime });
  const dates = (text.match(/\d{4}[.\-]\d{1,2}[.\-]\d{1,2}/g) || []).slice(0, 30).map(ctx.rightsDate);
  R.docs.houseRead = hr; R.docs.house = { dates, nChars: text.length, none: !!hr.empty, ocr: true };
  toSave.push(a);
  console.log(`${dry ? '[미리보기] ' : ''}${a.caseNo} ${a.name || ''} ← ${f}${looseNote ? ' (' + looseNote + ')' : ''}: 발급 ${hr.issued || '?'} · 전입일 ${hr.moveIns.length}개 · 세대주 ${hr.holders}명 · ${hr.empty ? '전입 세대 없음' : '거주자 ' + hr.residents + '명'}${hr.absent ? ' · 말소/거주불명 표시 있음' : ''}`);
}
skipped.forEach(([f, why]) => console.log('건너뜀', f, '-', why));
if (!dry && imgJobs.length) {  // 줄인 그림 올리기(사건 id = 키). 저장 실패하면 앱 값도 올리지 않음
  let sum = 0;
  for (const j of imgJobs) {
    const im = shrink(path.join(DIR, j.f)); sum += im.bytes;
    const r = await fetch(SITE + '/api/auction?kind=houseImg', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: j.a.id, caseNo: j.a.caseNo, img: im.dataUrl, file: j.f, mtime: j.mtime, at: Date.now() }) });
    if (!r.ok) { console.error('그림 저장 실패', j.a.caseNo, r.status, (await r.text()).slice(0, 120)); process.exit(1); }
  }
  console.log(`🖼️ 그림 ${imgJobs.length}장 첨부 (합계 ${Math.round(sum / 1024)}KB)`);
}
if (!dry && toSave.length) {
  for (let i = 0; i < toSave.length; i += 15) { const r = await fetch(SITE + '/api/auction', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(toSave.slice(i, i + 15)) }); if (!r.ok) { console.error('저장 실패', r.status); process.exit(1); } }
  console.log(`✅ ${toSave.length}건 앱에 반영했어요. 앱을 새로고침하세요.`);
} else if (dry) console.log(`(미리보기) ${toSave.length}건을 반영할 수 있어요.`);
