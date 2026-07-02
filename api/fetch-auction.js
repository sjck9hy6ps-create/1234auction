// utils/fetch-auction.js
export async function fetchAuctionData(url) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000); // 8초 타임아웃

    try {
        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'Accept': 'application/xml',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Cache-Control': 'no-cache'
            },
            signal: controller.signal,
            // Vercel 환경에서 DNS 캐시를 무시하도록 유도
            next: { revalidate: 0 } 
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            throw new Error(`HTTP error! status: \${response.status}`);
        }

        return await response.text();
    } catch (error) {
        clearTimeout(timeoutId);
        if (error.name === 'AbortError') {
            throw new Error('국토부 API 응답 시간 초과');
        }
        throw error;
    }
}
