export default async function handler(req, res) {
  // CORS 허용 (보안 설정)
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') return res.status(200).end();

  const { url } = req.query;
  if (!url) return res.status(400).json({ error: 'URL이 없습니다' });

  try {
    // 탱크옥션 페이지 가져오기
    const response = await fetch(url, {
      headers: { 
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36' 
      }
    });
    const html = await response.text();

    // 필요한 데이터만 추출 (제목, 가격, 주소)
    const title = html.match(/<title>(.*?)<\/title>/i)?.[1] || '제목 없음';
    const address = html.match(/소재지[^가-힣]*([가-힣].{5,50}?[0-9-]{1,10})/)?.[1] || '주소를 찾을 수 없음';
    const price = html.match(/감정가[^0-9]*([0-9,]+)/)?.[1] || '0';

    return res.status(200).json({ title, address, price });
  } catch (e) {
    return res.status(500).json({ error: '데이터를 가져오는데 실패했습니다.' });
  }
}
