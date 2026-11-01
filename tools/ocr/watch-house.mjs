/* 세대열람 그림 자동 반영 감시 프로그램 (2026-11-01)
   확장프로그램이 ~/Downloads/tank-ocr 에 세대열람 그림(<tid>_house_p1.png)을 저장하면, 잠시 뒤 자동으로 tools/ocr/import-house.mjs 를 실행해
   글자 인식 → 앱 반영 → 줄인 원본 그림 첨부까지 끝냄(새 사건마다 직접 실행하던 단계를 없앰). 끝나면 맥 알림이 뜸.
   사용: node tools/ocr/watch-house.mjs [--dir <그림 폴더>] [--site <앱 주소>]   (터미널을 열어 두는 동안 감시)
   맥이 켜질 때마다 자동으로 켜 두려면: bash tools/ocr/install-watch.sh   (끄기: bash tools/ocr/install-watch.sh --uninstall) */
import fs from 'fs'; import os from 'os'; import path from 'path'; import { spawn, execFile } from 'child_process'; import { fileURLToPath } from 'url';
const here = path.dirname(fileURLToPath(import.meta.url)), args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const DIR = opt('--dir', path.join(os.homedir(), 'Downloads', 'tank-ocr')), SITE = opt('--site', 'https://1234auction.vercel.app');
const IMPORT = path.join(here, 'import-house.mjs'), SETTLE_MS = 15000;  // 파일이 다 저장될 때까지 15초 기다림
const log = (m) => console.log(new Date().toLocaleTimeString('ko-KR') + ' ' + m);
const notify = (title, body) => { try { execFile('osascript', ['-e', `display notification ${JSON.stringify(body)} with title ${JSON.stringify(title)}`]); } catch (e) {} };
let running = false, again = false, timer = null;
function sizeStable(f) { try { const a = fs.statSync(f).size; return new Promise((r) => setTimeout(() => { try { r(fs.statSync(f).size === a && a > 0); } catch (e) { r(false); } }, 1500)); } catch (e) { return Promise.resolve(false); } }
async function runImport(why) {
  if (running) { again = true; return; }
  running = true; log('세대열람 그림 처리 시작 (' + why + ')');
  const out = [];
  await new Promise((resolve) => {
    const p = spawn(process.execPath, [IMPORT, '--dir', DIR, '--site', SITE], { cwd: path.join(here, '..', '..') });
    p.stdout.on('data', (d) => out.push(String(d))); p.stderr.on('data', (d) => out.push(String(d)));
    p.on('close', resolve); p.on('error', (e) => { out.push(String(e)); resolve(); });
  });
  const txt = out.join(''), done = txt.match(/✅\s*(\d+)건/), pics = txt.match(/그림\s*(\d+)장 첨부/), failed = /저장 실패|오류|Error/.test(txt) && !done;
  const unmatched = (txt.match(/건너뜀[^\n]*(?:수집 물건이 없음|구분 못 함|못 읽음)/g) || []).length;
  txt.split('\n').filter((l) => /^(\d{4}-\d+|✅|🖼️|건너뜀)/.test(l) && !/이미 반영됨/.test(l)).forEach((l) => log('  ' + l));
  if (done) { log('✅ 반영 ' + done[1] + '건' + (pics ? ' · 그림 ' + pics[1] + '장' : '')); notify('세대열람 반영 완료', done[1] + '건 반영됐어요. 앱을 새로고침하세요.' + (unmatched ? ' (앱에 없는 그림 ' + unmatched + '장)' : '')); }
  else if (failed) { log('⚠️ 처리 중 문제가 있었어요:\n' + txt.slice(-400)); notify('세대열람 반영 실패', '자세한 내용은 로그를 확인하세요.'); }
  else log('새로 반영할 그림 없음');
  running = false; if (again) { again = false; schedule('이어서'); }
}
function schedule(why) { clearTimeout(timer); timer = setTimeout(() => runImport(why), SETTLE_MS); }
if (!fs.existsSync(DIR)) { fs.mkdirSync(DIR, { recursive: true }); log('그림 폴더를 만들었어요: ' + DIR); }
log('세대열람 그림 감시 시작: ' + DIR + ' → ' + SITE);
runImport('시작할 때 밀린 그림 확인');
fs.watch(DIR, (ev, name) => {
  if (!name || !/_house_p\d+\.png$/.test(name)) return;
  const f = path.join(DIR, name);
  sizeStable(f).then((ok) => { if (ok) { log('새 그림: ' + name); schedule('새 그림'); } });
});
process.on('SIGINT', () => { log('감시를 끝냈어요'); process.exit(0); });
