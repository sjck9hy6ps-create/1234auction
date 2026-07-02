// api/house.js
import { fetchAuctionData } from '../utils/fetch-auction';

export default async function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    const serviceKey = 'ca4e98f4254eccbbabfbb3f9f972e17eba48507e804a9ac2bc97260423a090d6';

    let safeYmd = dealYmd;
    if (parseInt(dealYmd) > 202412) safeYmd = '202412';

    const baseUrl = 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc';
    const apiPath = endpoint === 'aptRent' 
        ? `/getRTMSDataSvcAptRent`
        : `/getRTMSDataSvcAptTradeDev`;
    
    const fullUrl = `${baseUrl}${apiPath}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${safeYmd}`;

    try {
        const data = await fetchAuctionData(fullUrl);
        
        res.setHeader('Content-Type', 'application/xml; charset=utf-8');
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.status(200).send(data);
    } catch (error) {
        console.error('House API Error:', error.message);
        res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><body><items></items></body></response>');
    }
}
