// utils/fetch-auction.js
export async function fetchAuctionData(url) {
    try {
        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'Accept': 'application/xml',
                'User-Agent': 'Mozilla/5.0'
            },
            // 캐시 문제 방지
            cache: 'no-store'
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: \${response.status}`);
        }

        return await response.text();
    } catch (error) {
        console.error('Fetch Auction Error:', error);
        throw error;
    }
}
