/* 서류로 쓴 이야기를 앱에 저장 (2026-11-01)
   사용: node tools/story/save-story.mjs <이야기.json> <서류1.txt> [서류2.txt ...] [--site <앱 주소>] [--force]
   저장 전에 ground-check로 이야기 속 값이 서류에 있는지 대조하고, 못 찾은 값이 있으면 저장하지 않음(--force로만 저장). 대조 결과(일치 수·못 찾은 값)가 이야기와 함께 앱에 저장되어 화면에 표시됨 */
import fs from 'fs'; import { groundCheck } from './ground-check.mjs';
const args = process.argv.slice(2), force = args.includes('--force'), si = args.indexOf('--site'), SITE = si >= 0 ? args[si + 1] : 'https://1234auction.vercel.app';
const files = args.filter((a, i) => !a.startsWith('--') && (si < 0 || (i !== si + 1)));
const story = JSON.parse(fs.readFileSync(files[0], 'utf8')), srcs = files.slice(1).map((f) => fs.readFileSync(f, 'utf8'));
const text = story.sections.map((s) => s.title + '\n' + (s.paragraphs || []).join('\n') + (s.items || []).map((i) => '\n' + (i.tag || '') + ' ' + (i.head || '') + ' ' + (i.body || '')).join('')).join('\n'), r = groundCheck(text, srcs);
console.log(`서류 대조: ${r.total}개 중 일치 ${r.ok}개, 못 찾은 값 ${r.unverified.length}개`); r.unverified.forEach((t) => console.log('  ✗ ' + t.type + ': ' + t.raw));
if (r.unverified.length && !force) { console.log('서류에 없는 값이 있어 저장하지 않았어요(확인 후 고치거나 --force).'); process.exit(1); }
const n = (x) => String(x || '').replace(/타경/g, '-').replace(/\s/g, '');
const auc = await fetch(SITE + '/api/auction?kind=auctions').then((x) => x.json());
const a = auc.find((x) => !x.isBacktest && n(x.caseNo) === n(story.case) && x.rights && x.rights.via === 'extension');
if (!a) { console.log('앱에서 이 사건(탱크옥션 수집)을 못 찾았어요:', story.case); process.exit(1); }
a.rights.aiStory = { at: Date.now(), by: 'Claude (서류를 읽고 작성 - 서류 값 대조 후 저장)', title: story.title, sections: story.sections, check: { total: r.total, ok: r.ok, unverified: r.unverified.map((t) => t.type + ':' + t.raw), calc: r.calc.length } };
const res = await fetch(SITE + '/api/auction', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(a) });
console.log(res.ok ? '✅ 앱에 저장했어요 - ' + a.caseNo + ' ' + (a.name || '') : '저장 실패 ' + res.status);
