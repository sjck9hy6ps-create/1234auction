export default async function handler(req, res) {
    const REDIS_URL = process.env.REDIS_URL;
    const REDIS_TOKEN = process.env.REDIS_TOKEN;

    // Upstash Redis 호출 함수
    async function redisFetch(command, ...args) {
        const response = await fetch(`${REDIS_URL}/${command}/${args.join('/')}`, {
            headers: { Authorization: `Bearer \${REDIS_TOKEN}` }
        });
        return response.json();
    }

    try {
        if (req.method === 'GET') {
            // 모든 경매 데이터 가져오기 (Redis의 'auctions' 키에 저장된 값)
            const data = await redisFetch('get', 'auctions');
            const auctions = data.result ? JSON.parse(data.result) : [];
            return res.status(200).json(auctions);
        } 

        if (req.method === 'POST') {
            const newAuction = req.body;
            // 기존 데이터 가져오기
            const currentData = await redisFetch('get', 'auctions');
            let auctions = currentData.result ? JSON.parse(currentData.result) : [];
            
            // 동일한 ID가 있으면 업데이트, 없으면 추가
            const index = auctions.findIndex(a => a.id === newAuction.id);
            if (index > -1) auctions[index] = newAuction;
            else auctions.push(newAuction);
            
            // Redis에 다시 저장 (문자열로 변환)
            await fetch(`${REDIS_URL}/set/auctions`, {
                method: 'POST',
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` },
                body: JSON.stringify(auctions)
            });
            
            return res.status(200).json(newAuction);
        }

        if (req.method === 'DELETE') {
            const { id } = req.query;
            const currentData = await redisFetch('get', 'auctions');
            let auctions = currentData.result ? JSON.parse(currentData.result) : [];
            
            auctions = auctions.filter(a => a.id !== id);
            
            await fetch(`${REDIS_URL}/set/auctions`, {
                method: 'POST',
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` },
                body: JSON.stringify(auctions)
            });
            
            return res.status(200).json({ success: true });
        }
    } catch (e) {
        console.error('Redis Error:', e);
        return res.status(500).json({ error: e.message });
    }
}
