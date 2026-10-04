/* ════════════════════════════════════
   api/auction.js
   경매물건(auctions) + 임장메모(siteNotes) + 낙찰사례(bidCases) 공용 CRUD 엔드포인트
   ⚠️ Vercel Hobby 플랜은 서버리스 함수(api/*.js 파일)를 12개까지만 허용하는데
      이미 12개(auction, get-building, get-boundary, get-coords, get-house,
      get-official-price, parse-auction, parse-registry, search-complex,
      save-coord, export-table, data-coverage)가 꽉 차 있어서, 새 파일을
      추가하는 대신 이 파일 하나가 쿼리스트링 ?kind= 값으로 저장소를 구분해서
      세 자원(auctions/siteNotes/bidCases)을 함께 처리하도록 합침.
      - /api/auction              (kind 생략 시 기본값)        → 'auctions'
      - /api/auction?kind=siteNotes                              → 'siteNotes'
      - /api/auction?kind=bidCases  (지역별 낙찰사례 통계용)      → 'bidCases'

   ⚠️ 2026-10(저장소 월 전송량 10GB 초과 사고 후 재설계): 예전엔 키 하나에 JSON 배열 전체를 넣어서
      ① 앱을 열 때마다 경매물건 3.2MB + 낙찰사례 1.5MB를 통째로 받고
      ② 물건 하나를 저장/삭제할 때도 전체 목록을 읽고 다시 썼음(저장 1번에 약 6.5MB 전송)
      → Upstash 무료 플랜 월 10GB를 쉽게 넘김. 이제는
      - 물건마다 해시 필드 하나(HSET h:<kind> <id> <json>) - 저장/삭제는 그 물건 하나만 오감
      - 목록 버전(v:<kind>, 바뀔 때마다 +1) - 앱은 ?withVer=1&since=<버전>으로 물어보고, 안 바뀌었으면
        목록 없이 {unchanged:true}만 받아 브라우저에 보관된 목록을 씀
      - 기존 배열 키는 처음 접근할 때 자동으로 해시로 옮기고, 원본은 '<kind>:legacy_backup'으로 남겨둠
      응답 형식은 예전과 같음(?withVer=1을 안 붙이면 배열 그대로) - dashboard.html·match-bid-cases.mjs 호환.
════════════════════════════════════ */
// myAssets(2026-10): 💼 내 자산 탭 - 보유 부동산·올해 소득(몇 건뿐이라 저장량 부담 없음)
const KINDS = { auctions: 'auctions', siteNotes: 'siteNotes', bidCases: 'bidCases', myAssets: 'myAssets' };

export default async function handler(req, res) {
    const REDIS_URL = process.env.UPSTASH_REDIS_URL;
    const REDIS_TOKEN = process.env.UPSTASH_REDIS_TOKEN;
    if (!REDIS_URL || !REDIS_TOKEN) {
        return res.status(500).json({ error: 'UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
    }
    const kind = KINDS[req.query.kind] || 'auctions';
    const hashKey = `h:${kind}`;
    const verKey = `v:${kind}`;
    const auth = { Authorization: `Bearer ${REDIS_TOKEN}` };

    // 저장소가 오류를 주면(한도 초과 등) 예외로 올려 503으로 응답 - 빈 목록처럼 보이지 않게
    async function cmd(arr) {
        const r = await fetch(REDIS_URL, { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify(arr) });
        const j = await r.json().catch(() => null);
        if (!j || j.error) throw Object.assign(new Error('저장소 오류: ' + ((j && j.error) || r.status)), { storage: true });
        return j.result;
    }
    async function pipeline(cmds) {
        const r = await fetch(`${REDIS_URL}/pipeline`, { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify(cmds) });
        const j = await r.json().catch(() => null);
        if (!Array.isArray(j)) throw Object.assign(new Error('저장소 오류: ' + ((j && j.error) || r.status)), { storage: true });
        const bad = j.find((x) => x && x.error);
        if (bad) throw Object.assign(new Error('저장소 오류: ' + bad.error), { storage: true });
        return j.map((x) => x.result);
    }
    // 예전 배열 키 → 해시로 1회 이전(이미 이전됐으면 아무것도 안 함)
    async function ensureMigrated() {
        const exists = await cmd(['EXISTS', hashKey]);
        if (exists) return;
        const legacy = await cmd(['GET', kind]);
        let list = [];
        try { list = legacy ? JSON.parse(legacy) : []; } catch (e) { list = []; }
        if (!Array.isArray(list)) list = [];
        const CHUNK = 200;
        for (let i = 0; i < list.length; i += CHUNK) {
            const args = ['HSET', hashKey];
            list.slice(i, i + CHUNK).forEach((it, k) => {
                if (it && it.id != null) args.push(String(it.id), JSON.stringify({ ...it, _ord: i + k }));
            });
            if (args.length > 2) await cmd(args);
        }
        await cmd(['SET', verKey, '1']);
        // 원본 배열은 지우지 않고 이름만 바꿔 보관(동시에 두 요청이 이전하면 두 번째 RENAME은 실패해도 무방)
        if (legacy) { try { await cmd(['RENAME', kind, `${kind}:legacy_backup`]); } catch (e) { /* 이미 옮겨짐 */ } }
    }
    async function readAll() {
        const flat = (await cmd(['HGETALL', hashKey])) || [];
        const list = [];
        for (let i = 0; i + 1 < flat.length; i += 2) {
            try { list.push(JSON.parse(flat[i + 1])); } catch (e) { /* 깨진 항목은 건너뜀 */ }
        }
        // 예전 배열 순서(_ord) → 그 뒤 새로 추가된 건 id(생성시각) 순
        list.sort((a, b) => {
            const oa = a._ord != null ? a._ord : Infinity, ob = b._ord != null ? b._ord : Infinity;
            if (oa !== ob) return oa - ob;
            return String(a.id).localeCompare(String(b.id), undefined, { numeric: true });
        });
        return list.map(({ _ord, ...rest }) => rest);
    }

    try {
        await ensureMigrated();

        if (req.method === 'GET' && req.query.diag === '1') {
            // 진단 전용(읽기만 함) - 값 자체/비밀값은 노출하지 않음
            const [hlen, ver, dbsize] = await pipeline([['HLEN', hashKey], ['GET', verKey], ['DBSIZE']]);
            return res.status(200).json({ kind, items: hlen, ver, dbsize });
        }
        if (req.method === 'GET') {
            const ver = String((await cmd(['GET', verKey])) || '0');
            if (req.query.withVer === '1') {
                res.setHeader('Cache-Control', 'no-store');
                if (req.query.since && String(req.query.since) === ver) return res.status(200).json({ unchanged: true, ver });
                return res.status(200).json({ ver, list: await readAll() });
            }
            return res.status(200).json(await readAll());
        }
        if (req.method === 'POST') {
            const newItem = req.body;
            if (!newItem || newItem.id == null) return res.status(400).json({ error: 'id가 있는 항목이어야 합니다.' });
            const prev = await cmd(['HGET', hashKey, String(newItem.id)]);
            let ord = null;
            try { ord = prev ? JSON.parse(prev)._ord : null; } catch (e) { ord = null; }
            const stored = ord != null ? { ...newItem, _ord: ord } : newItem;
            const [, newVer] = await pipeline([['HSET', hashKey, String(newItem.id), JSON.stringify(stored)], ['INCR', verKey]]);
            res.setHeader('X-List-Version', String(newVer));
            return res.status(200).json(newItem);
        }
        if (req.method === 'DELETE') {
            const id = req.query.id;
            const [, newVer] = await pipeline([['HDEL', hashKey, String(id)], ['INCR', verKey]]);
            res.setHeader('X-List-Version', String(newVer));
            return res.status(200).json({ ok: true });
        }
        return res.status(405).json({ error: 'Method not allowed' });
    } catch (e) {
        return res.status(e.storage ? 503 : 500).json({ error: e.message });
    }
}
