export default async function handler(req, res) {
    const REDIS_URL = 'https://golden-giraffe-110032.upstash.io';
    const REDIS_TOKEN = 'gQAAAAAAAa3QAAIgcDE4OWY3NTZlNTlmNzQ0ZTdhODgwNmEyOGMwMGEyMGNlMQ'; // Upstash에서 복사한 Token

    try {
        if (req.method === 'GET') {
            const response = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` }
            });
            const data = await response.json();
            const auctions = data.result ? JSON.parse(data.result) : [];
            return res.status(200).json(auctions);
        } 

        if (req.method === 'POST') {
            // 기존 목록 가져오기
            const responseGet = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` }
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
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` },
                body: JSON.stringify(JSON.stringify(auctions))
            });
            return res.status(200).json(newAuction);
        }
    } catch (e) {
        return res.status(500).json({ error: e.message });
    }
}
