// 건축물대장 백그라운드 수집(2026-10, 사용자: "입찰후보 탭을 열지 않아도 건축물대장 정보를 수집해줘. 한 번 정확히 불러오면 변하지 않는
// 정보이니 자주 불러올 필요가 없어").
// 등록한 입찰물건(아파트·빌라) 중 연식·세대수(단지 전체)·승강기 수가 비어 있는 것만 골라 /api/get-building으로 한 번씩 불러와 저장함.
//  - 이미 다 채워진 물건은 다시 부르지 않음. 못 찾은 물건은 30일 뒤에만 다시 시도(bldgTriedAt).
//  - 건축HUB 하루 한도 초과 응답이 오면 그 자리에서 멈춤(다음 실행 때 이어서).
//  - 법정동코드(bCode)가 없는 물건은 카카오 좌표→법정동 변환으로 구해 함께 저장.
//  - 저장 직전에 최신 목록을 다시 읽어 건축물대장 칸만 덮어씀(그 사이 앱에서 고친 다른 값은 그대로).
// 앱의 fetchHouseholdsFor와 같은 규칙: 세대수는 총괄표제부 → 같은 지번 모든 동 합계 → 동이 하나뿐일 때만 그 동 값.
const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const KAKAO = process.env.KAKAO_REST_API_KEY || '';
const MAX = parseInt(process.env.MAX_ITEMS || '1500', 10);
const RETRY_DAYS = 30;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const today = new Date().toISOString().slice(0, 10);

function needs(a) {
  if (!a || a.isBacktest) return false;
  if (a.propType !== 'apt' && a.propType !== 'villa') return false;
  if (!a.bunji && !a.addr) return false;
  const done = a.buildYear && (a.propType === 'villa' || (a.households && a.householdsVer === 2)) && a.elevatorCnt != null;
  if (done) return false;
  if (a.bldgTriedAt) {
    const days = (Date.now() - new Date(a.bldgTriedAt + 'T00:00:00').getTime()) / 86400000;
    if (days < RETRY_DAYS) return false;
  }
  return true;
}

function bunJi(bunji) {
  const parts = String(bunji || '').replace(/^산\s*/, '').split('-');
  const m = parseInt(parts[0], 10);
  if (!m) return null;
  const s = parts[1] !== undefined ? parseInt(parts[1], 10) : 0;
  return { bun: String(m).padStart(4, '0'), ji: String(s || 0).padStart(4, '0') };
}

async function bCodeOf(a) {
  if (a.bCode && String(a.bCode).length >= 10) return String(a.bCode);
  if (!KAKAO || !a.lat || !a.lon) return null;
  const r = await fetch(`https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?x=${a.lon}&y=${a.lat}`, { headers: { Authorization: `KakaoAK ${KAKAO}` } });
  if (!r.ok) return null;
  const j = await r.json();
  const b = (j.documents || []).find((d) => d.region_type === 'B');
  return b ? b.code : null;
}

async function main() {
  const list = await fetch(`${SITE}/api/auction`).then((r) => r.json());
  // 입찰이 가까운 물건부터, 이미 지난 입찰은 맨 뒤(2026-10-10: 하루 한도 10,000건을 실제로 볼 물건에 먼저 쓰게)
  const dd = (a) => { const d = String(a.bidDate || '').slice(0, 10); return /^\d{4}-\d\d-\d\d$/.test(d) ? (d >= today ? d : '9' + d) : '9999'; };
  const todo = list.filter(needs).sort((x, y) => dd(x).localeCompare(dd(y))).slice(0, MAX);
  console.log(`입찰물건 ${list.length}건 중 건축물대장 수집 대상 ${list.filter(needs).length}건 (이번 실행 최대 ${MAX}건)`);
  const updates = {};
  let quota = false, ok = 0, miss = 0;
  for (const a of todo) {
    const upd = { bldgTriedAt: today };
    try {
      const code = await bCodeOf(a);
      // CSV 물건은 지번이 본번만("22") 있는 경우가 있어 주소의 "동 22-7"을 먼저 씀
      const am = String(a.addr || '').match(new RegExp((a.dong || '[가-힣0-9]+[동리가]') + '\\s+(산?\\d+(?:-\\d+)?)'));
      const bj = bunJi(am ? am[1] : a.bunji);
      if (!code || !bj) { miss++; updates[a.id] = upd; continue; }
      if (!a.bCode) upd.bCode = code;
      const url = `${SITE}/api/get-building?sigunguCd=${code.slice(0, 5)}&bjdongCd=${code.slice(5, 10)}&bun=${bj.bun}&ji=${bj.ji}&bldNm=${encodeURIComponent(a.name || '')}`;
      const info = await fetch(url).then((r) => r.json());
      const raw = JSON.stringify((info && info.debug) || {});
      if (/LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS|일일 서비스 요청제한/.test(raw)) { quota = true; console.log('건축HUB 하루 한도 초과 - 여기서 멈춤(다음 실행 때 이어서)'); break; }
      const t = info && info.title;
      if (t) {
        const ym = String(t.useAprDay || (t.site && t.site.useAprDay) || '').match(/(\d{4})/);
        if (ym && !a.buildYear) { const y = parseInt(ym[1], 10); if (y > 1950 && y <= new Date().getFullYear()) { upd.buildYear = y; upd.buildYearSource = '건축물대장'; } }
        if (a.elevatorCnt == null && (t.rideElvtCnt != null || t.emgenElvtCnt != null)) upd.elevatorCnt = (t.rideElvtCnt || 0) + (t.emgenElvtCnt || 0);
        if (t.hhVer === 2 && !(a.households && a.householdsVer === 2)) {
          const hh = (t.site && t.site.hhldCnt > 0) ? t.site.hhldCnt : (t.hhldSum > 0 ? t.hhldSum : (t.hhldBldCnt <= 1 ? t.hhldCnt : null));
          if (hh > 0) { upd.households = parseInt(hh, 10); upd.householdsVer = 2; }
        }
        ok++;
      } else miss++;
    } catch (e) { miss++; console.log('실패', a.id, e.message); }
    updates[a.id] = upd;
    await sleep(400);
  }
  const ids = Object.keys(updates);
  if (!ids.length) { console.log('저장할 것 없음'); return; }
  // 최신 목록에 건축물대장 칸만 합쳐서 저장(그 사이 앱에서 바뀐 다른 값 보존)
  const fresh = await fetch(`${SITE}/api/auction`).then((r) => r.json());
  const byId = new Map(fresh.map((x) => [String(x.id), x]));
  const out = [];
  ids.forEach((id) => { const cur = byId.get(String(id)); if (cur) out.push({ ...cur, ...updates[id] }); });
  for (let i = 0; i < out.length; i += 100) {
    const r = await fetch(`${SITE}/api/auction`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(out.slice(i, i + 100)) });
    console.log('저장', i, '~', Math.min(i + 100, out.length), r.status);
  }
  const got = (k) => out.filter((x) => updates[x.id] && updates[x.id][k] != null).length;
  const summary = `건축물대장 수집: 조회 ${ok + miss}건(성공 ${ok}, 못 찾음 ${miss})${quota ? ' · 하루 한도 초과로 중단' : ''} · 새로 채움 연식 ${got('buildYear')} / 세대수 ${got('households')} / 승강기 ${got('elevatorCnt')}`;
  console.log(summary);
  if (process.env.GITHUB_STEP_SUMMARY) { const fs = await import('fs'); fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `## ${summary}\n`); }
}

main().catch((e) => { console.error(e); process.exit(1); });
