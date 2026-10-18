// 호가 보내기 - 백그라운드: 페이지에서 받은 매물 목록 원문을 경매 앱 수신함(kind=listingRaw)에 올림. 앱이 열릴 때 단지 이름·평형으로 알아서 반영함.
const APP = 'https://1234auction.vercel.app';
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== 'send') return;
  (async () => {
    try {
      const body = { id: Date.now() + '_' + Math.random().toString(36).slice(2, 7), at: new Date().toISOString(), url: msg.url || '', text: String(msg.text || '').slice(0, 200000) };
      const r = await fetch(APP + '/api/auction?kind=listingRaw', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      sendResponse({ ok: r.ok, status: r.status });
    } catch (e) { sendResponse({ ok: false, error: String(e) }); }
  })();
  return true; // 비동기 응답
});
