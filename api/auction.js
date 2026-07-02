export default async function handler(req, res) {
    const REDIS_URL = process.env.REDIS_URL;
    const REDIS_TOKEN = process.env.REDIS_TOKEN;

    // Redis 설정이 없는 경우를 대비한 안전장치
    if (!REDIS_URL || !REDIS_TOKEN) {
        console.error("Redis 환경변수가 설정되지 않았습니다.");
        return res.status(200).json([]); // 에러 대신 빈 배열 반환
    }

    try {
        if (req.method === 'GET') {
            // Upstash REST API 방식 호출
            const response = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` }
            });
            const data = await response.json();
            
            // Redis에 데이터가 없으면 빈 배열, 있으면 파싱
            const auctions = data.result ? JSON.parse(data.result) : [];
            return res.status(200).json(auctions);
        } 

        if (req.method === 'POST') {
            const newAuction = req.body;
            
            // 기존 데이터 가져오기
            const responseGet = await fetch(`${REDIS_URL}/get/auctions`, {
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` }
            });
            const dataGet = await responseGet.json();
            let auctions = dataGet.result ? JSON.parse(dataGet.result) : [];
            
            // 데이터 업데이트 또는 추가
            const index = auctions.findIndex(a => a.id === newAuction.id);
            if (index > -1) auctions[index] = newAuction;
            else auctions.push(newAuction);
            
            // Redis에 저장 (set 명령은 POST로 전달)
            await fetch(`${REDIS_URL}/set/auctions`, {
                method: 'POST',
                headers: { Authorization: `Bearer \${REDIS_TOKEN}` },
                body: JSON.stringify(auctions)
            });
            
            return res.status(200).json(newAuction);
        }

        // DELETE 등 기타 요청 처리
        return res.status(405).end();

    } catch (e) {
        console.error('Redis 통신 에러:', e.message);
        // 서버 에러(500)를 던지는 대신 빈 데이터를 보내서 프론트엔드가 멈추지 않게 함
        return res.status(200).json([]); 
    }
}
