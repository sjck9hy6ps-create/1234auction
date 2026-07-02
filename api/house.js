export default async function handler(req, res) {
  const { endpoint, lawdCd, dealYmd } = req.query;
  const serviceKey = 'Y7YnS70898i6yZf7O8H%2B%2B9%2F7vI0859898989898989898989898989898'; // 기본 키 (작동 안할 시 본인 키로 교체)

  const urls = {
    apt: `http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${dealYmd}`,
    aptRent: `http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${dealYmd}`
  };

  try {
    const response = await fetch(urls[endpoint] || urls.apt);
    const text = await response.text();
    res.setHeader('Content-Type', 'application/xml');
    return res.status(200).send(text);
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
}
