/* ════════════════════════════════════
   api/auction.js
   경매물건(auctions) + 임장메모(siteNotes) 공용 CRUD 엔드포인트
   ⚠️ Vercel Hobby 플랜은 서버리스 함수(api/*.js 파일)를 12개까지만 허용하는데
      이미 12개(auction, get-building, get-boundary, get-coords, get-house,
      get-official-price, parse-auction, parse-registry, search-complex,
      save-coord, export-table, data-coverage)가 꽉 차 있어서, 새 파일을
      추가하는 대신 이 파일 하나가 쿼리스트링 ?kind= 값으로 저장소를 구분해서
      두 자원(auctions/siteNotes)을 함께 처리하도록 합침.
      - /api/auction              (kind 생략 시 기본값)        → Redis 키 'auctions'
      - /api/auction?kind=siteNotes                              → Redis 키 'siteNotes'
   Redis에 저장하는 방식(키 하나에 JSON 배열 전체)은 두 자원 모두 동일함.
════════════════════════════════════ */
export default async function handler(req, res) {
    const REDIS_URL = process.env.UPSTASH_REDIS_URL;
    const REDIS_TOKEN = process.env.UPSTASH_REDIS_TOKEN;
    if (!REDIS_URL || !REDIS_TOKEN) {
        return res.status(500).json({ error: 'UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
    }
    // kind=siteNotes 이면 임장메모 저장소, 그 외(기본값)는 경매물건 저장소를 사용
    const redisKey = req.query.kind === 'siteNotes' ? 'siteNotes' : 'auctions';
    try {
        if (req.method === 'GET') {
            const response = await fetch(`${REDIS_URL}/get/${redisKey}`, {
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` }
            });
            const data = await response.json();
            let list = data.result ? JSON.parse(data.result) : [];
            if (!Array.isArray(list)) list = [];
            return res.status(200).json(list);
        }
        if (req.method === 'POST') {
            // 기존 목록 가져오기
            const responseGet = await fetch(`${REDIS_URL}/get/${redisKey}`, {
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` }
            });
            const dataGet = await responseGet.json();
            let list = dataGet.result ? JSON.parse(dataGet.result) : [];
            if (!Array.isArray(list)) list = [];
            const newItem = req.body;
            const index = list.findIndex(a => a.id === newItem.id);
            if (index > -1) list[index] = newItem;
            else list.push(newItem);
            // 저장
            // ⚠️ Upstash REST API의 SET은 body를 "저장할 값 그 자체"로 취급하므로,
            //    배열을 JSON 문자열로 만든 값(JSON.stringify(list))을 그대로 body로 보내야 함.
            //    이걸 한 번 더 JSON.stringify하면 Redis에 "[...]" 형태의 문자열이 그대로
            //    저장되어(따옴표까지 포함), 읽어올 때 JSON.parse 한 번으로는 배열이 아니라
            //    문자열이 나와서 Array.isArray 체크에 걸려 매번 빈 배열로 리셋되는 버그가 있었음.
            const setRes = await fetch(`${REDIS_URL}/set/${redisKey}`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
                body: JSON.stringify(list)
            });
            if (!setRes.ok) {
                const errText = await setRes.text();
                console.error('Redis 저장 실패:', setRes.status, errText);
                return res.status(500).json({ error: 'Redis 저장 실패: ' + errText });
            }
            return res.status(200).json(newItem);
        }
        if (req.method === 'DELETE') {
            const id = req.query.id;
            const responseGet = await fetch(`${REDIS_URL}/get/${redisKey}`, {
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` }
            });
            const dataGet = await responseGet.json();
            let list = dataGet.result ? JSON.parse(dataGet.result) : [];
            if (!Array.isArray(list)) list = [];
            list = list.filter(a => a.id !== id);
            const setRes = await fetch(`${REDIS_URL}/set/${redisKey}`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
                body: JSON.stringify(list)
            });
            if (!setRes.ok) {
                const errText = await setRes.text();
                console.error('Redis 삭제(저장) 실패:', setRes.status, errText);
                return res.status(500).json({ error: 'Redis 저장 실패: ' + errText });
            }
            return res.status(200).json({ ok: true });
        }
        return res.status(405).json({ error: 'Method not allowed' });
    } catch (e) {
        return res.status(500).json({ error: e.message });
    }
}
