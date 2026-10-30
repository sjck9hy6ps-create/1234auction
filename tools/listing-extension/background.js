// 호가 보내기 - 백그라운드: 매물 목록 원문을 경매 앱 수신함(kind=listingRaw)에 올리고, 열려 있는 앱 탭에 바로 알려 반영시킨 뒤, 앱이 반영한 결과를 기다려 돌려줌
const APP = 'https://1234auction.vercel.app';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // 모으기가 끝나면 그 사건을 보려고 열었던 탱크옥션 팝업창(상세·참고자료)을 모두 닫음. 일반 상세 페이지·앱 탭은 닫지 않음
  if (msg && msg.type === 'closeWindows') {
    (async () => {
      const tid = String(msg.tid || '');
      try {
        const tabs = await chrome.tabs.query({ url: ['https://www.tankauction.com/*', 'https://tankauction.com/*'] });
        const ids = tabs.filter((t) => /\/popup\//.test(t.url || '') && (!tid || new RegExp('[?&](tid|opener_1st_no)=' + tid + '(&|$)').test(t.url || ''))).map((t) => t.id);
        if (sender.tab && /\/popup\//.test(sender.tab.url || '') && ids.indexOf(sender.tab.id) < 0) ids.push(sender.tab.id);
        if (ids.length) await chrome.tabs.remove(ids);
      } catch (e) {}
      sendResponse({ ok: true });
    })();
    return true;
  }
  if (!msg || msg.type !== 'send') return;
  (async () => {
    try {
      const id = Date.now() + '_' + Math.random().toString(36).slice(2, 7);
      const body = { id, at: new Date().toISOString(), url: msg.url || '', text: String(msg.text || '').slice(0, 200000) };
      if (msg.kind === 'tank' || msg.kind === 'probe') body.kind = msg.kind;  // 탱크옥션 상세 글 - 앱이 권리분석으로 읽음
      const r = await fetch(APP + '/api/auction?kind=listingRaw', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!r.ok) { sendResponse({ ok: false, status: r.status }); return; }
      // 열려 있는 앱 탭에 즉시 알림(새로고침·대기 없이 바로 반영)
      let tabs = [];
      try { tabs = await chrome.tabs.query({ url: APP + '/*' }); } catch (e) {}
      for (const t of tabs) { try { await chrome.tabs.sendMessage(t.id, { type: 'inbox', id }); } catch (e) {} }
      // 앱이 반영하고 남긴 처리 기록을 기다림(최대 약 60초)
      for (let i = 0; i < 30; i++) {
        await sleep(2000);
        try {
          const list = await fetch(APP + '/api/auction?kind=listingRaw', { cache: 'no-store' }).then((x) => x.json());
          const mine = Array.isArray(list) ? list.find((x) => x.id === id) : null;
          if (mine && mine.done) { sendResponse({ ok: true, applied: true, result: mine.result || null }); return; }
        } catch (e) {}
      }
      sendResponse({ ok: true, applied: false, noApp: tabs.length === 0 });
    } catch (e) { sendResponse({ ok: false, error: String(e) }); }
  })();
  return true; // 비동기 응답
});
