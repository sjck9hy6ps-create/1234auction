export default async function handler(req, res) {
    // Upstash에서 복사한 정보를 아래에 직접 넣으세요
    const REDIS_URL = 'https://golden-giraffe-110032.upstash.io';
    const REDIS_TOKEN = 'gQAAAAAAAa3QAAIgcDE4OWY3NTZlNTlmNzQ0ZTdhODgwNmEyOGMwMGEyMGNlMQ'; 

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
            const responseGet = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` }
            });
            const dataGet = await responseGet.json();
            let auctions = dataGet.result ? JSON.parse(dataGet.result) : [];
            
            const newAuction = req.body;
            const index = auctions.findIndex(a => a.id === newAuction.id);
            if (index > -1) auctions[index] = newAuction;
            else auctions.push(newAuction);
            
            await fetch(`${REDIS_URL}/set/auctions`, {
                method: 'POST',
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` },
                body: JSON.stringify(auctions)
            });
            return res.status(200).json(newAuction);
        }
    } catch (e) {
        return res.status(200).json([]); // 에러 시 빈 배열 반환하여 지도 살림
    }
}
