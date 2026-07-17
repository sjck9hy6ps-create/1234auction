export default async function handler(req, res) {
    const REDIS_URL = process.env.UPSTASH_REDIS_URL;
    const REDIS_TOKEN = process.env.UPSTASH_REDIS_TOKEN;
    if (!REDIS_URL || !REDIS_TOKEN) {
        return res.status(500).json({ error: 'UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
    }
    try {
        if (req.method === 'GET') {
            const response = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` }
            });
            const data = await response.json();
            let auctions = data.result ? JSON.parse(data.result) : [];
            if (!Array.isArray(auctions)) auctions = [];
            return res.status(200).json(auctions);
        }
        if (req.method === 'POST') {
            // 기존 목록 가져오기
            const responseGet = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` }
            });
            const dataGet = await responseGet.json();
            let auctions = dataGet.result ? JSON.parse(dataGet.result) : [];
            if (!Array.isArray(auctions)) auctions = [];
            const newAuction = req.body;
            const index = auctions.findIndex(a => a.id === newAuction.id);
            if (index > -1) auctions[index] = newAuction;
            else auctions.push(newAuction);
            // 저장
            // ⚠️ Upstash REST API의 SET은 body를 "저장할 값 그 자체"로 취급하므로,
            //    배열을 JSON 문자열로 만든 값(JSON.stringify(auctions))을 그대로 body로 보내야 함.
            //    이걸 한 번 더 JSON.stringify하면 Redis에 "[...]" 형태의 문자열이 그대로
            //    저장되어(따옴표까지 포함), 읽어올 때 JSON.parse 한 번으로는 배열이 아니라
            //    문자열이 나와서 Array.isArray 체크에 걸려 매번 빈 배열로 리셋되는 버그가 있었음.
            const setRes = await fetch(`${REDIS_URL}/set/auctions`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
                body: JSON.stringify(auctions)
            });
            if (!setRes.ok) {
                const errText = await setRes.text();
                console.error('Redis 저장 실패:', setRes.status, errText);
                return res.status(500).json({ error: 'Redis 저장 실패: ' + errText });
            }
            return res.status(200).json(newAuction);
        }
        if (req.method === 'DELETE') {
            const id = req.query.id;
            const responseGet = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` }
            });
            const dataGet = await responseGet.json();
            let auctions = dataGet.result ? JSON.parse(dataGet.result) : [];
            if (!Array.isArray(auctions)) auctions = [];
            auctions = auctions.filter(a => a.id !== id);
            const setRes = await fetch(`${REDIS_URL}/set/auctions`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
                body: JSON.stringify(auctions)
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
