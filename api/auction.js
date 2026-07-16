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
            const auctions = data.result ? JSON.parse(data.result) : [];
            return res.status(200).json(auctions);
        }
        if (req.method === 'POST') {
            // 기존 목록 가져오기
            const responseGet = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` }
            });
            const dataGet = await responseGet.json();
            let auctions = dataGet.result ? JSON.parse(dataGet.result) : [];

            const newAuction = req.body;
            const index = auctions.findIndex(a => a.id === newAuction.id);
            if (index > -1) auctions[index] = newAuction;
            else auctions.push(newAuction);

            // 저장
            await fetch(`${REDIS_URL}/set/auctions`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
                body: JSON.stringify(JSON.stringify(auctions))
            });
            return res.status(200).json(newAuction);
        }
        if (req.method === 'DELETE') {
            const id = req.query.id;
            const responseGet = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` }
            });
            const dataGet = await responseGet.json();
            let auctions = dataGet.result ? JSON.parse(dataGet.result) : [];
            auctions = auctions.filter(a => a.id !== id);

            await fetch(`${REDIS_URL}/set/auctions`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
                body: JSON.stringify(JSON.stringify(auctions))
            });
            return res.status(200).json({ ok: true });
        }
        return res.status(405).json({ error: 'Method not allowed' });
    } catch (e) {
        return res.status(500).json({ error: e.message });
    }
}
