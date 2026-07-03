export default async function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    const serviceKey = 'ca4e98f4254eccbbabfbb3f9f972e17eba48507e804a9ac2bc97260423a090d6';

    // ✅ 올바른 엔드포인트
    const aptTradeUrl = `https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev`;
    const aptRentUrl = `https://apis.data.go.kr/1613000/RTMSDataSvcAptRent`;

    const baseUrl = endpoint === 'aptRent' ? aptRentUrl : aptTradeUrl;
    const fullUrl = `${baseUrl}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${dealYmd}`;

    res.setHeader('Content-Type', 'application/xml; charset=utf-8');
    res.setHeader('Access-Control-Allow-Origin', '*');

    try {
        const response = await fetch(fullUrl);
        const data = await response.text();
        res.status(200).send(data);
    } catch (error) {
        console.error('House API Error:', error.message);
        res.status(200).send(`<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>99</resultCode></header>
  <body><items></items><totalCount>0</totalCount></body>
</response>`);
    }
}
