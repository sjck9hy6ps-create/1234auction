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
  // 상세 팝업 ↔ 참고자료 팝업 사이 인계: 상세 팝업이 표시(arm)하면 새로 열린 참고자료 팝업이 가져가서(claim) 읽음. 60초 지나면 무효
  if (msg && ['arm', 'claim', 'armState', 'disarm'].indexOf(msg.type) >= 0) {
    (async () => {
      const k = 'arm_' + String(msg.tid || ''), st = chrome.storage.session;
      try {
        if (msg.type === 'arm') { await st.set({ [k]: { text: String(msg.text || '').slice(0, 100000), url: msg.url || '', at: Date.now(), claimed: false } }); sendResponse({ ok: true }); return; }
        const cur = (await st.get(k))[k];
        const fresh = cur && Date.now() - cur.at < 60000;
        if (msg.type === 'disarm') { await st.remove(k); sendResponse({ ok: true }); }
        else if (msg.type === 'armState') sendResponse({ claimed: !!(fresh && cur.claimed) });
        else if (msg.type === 'claim') {
          if (fresh && !cur.claimed) { cur.claimed = true; await st.set({ [k]: cur }); sendResponse({ armed: true, text: cur.text, url: cur.url }); }
          else sendResponse({ armed: false });
        }
      } catch (e) { sendResponse({ armed: false, error: String(e) }); }
    })();
    return true;
  }
  // ---- 모으기 대기열(앱이 listingRaw의 id 'queue' 항목으로 저장) ----
  if (msg && ['queueGet', 'queueDone', 'learnTids', 'openCase', 'autoStart', 'chainSet'].indexOf(msg.type) >= 0) {
    (async () => {
      const QID = 'queue', loc = chrome.storage.local, ses = chrome.storage.session;
      const qLoad = async () => { const list = await fetch(APP + '/api/auction?kind=listingRaw', { cache: 'no-store' }).then((x) => x.json()); const it = Array.isArray(list) ? list.find((x) => x.id === QID) : null; let q = null; try { q = it && JSON.parse(it.text); } catch (e) {} return { it, q }; };
      const qSave = async (it, q) => { await fetch(APP + '/api/auction?kind=listingRaw', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: QID, at: (it && it.at) || new Date().toISOString(), kind: 'queue', url: '', text: JSON.stringify(q), done: true, appliedAt: new Date().toISOString() }) }); };
      try {
        const tm = ((await loc.get('tidMap')).tidMap) || {};
        if (msg.type === 'queueGet') { const { q } = await qLoad(); const cv = (await loc.get('chainOn')).chainOn; sendResponse({ q, tids: tm, chainOn: cv === undefined ? true : cv }); return; }
        if (msg.type === 'chainSet') { await loc.set({ chainOn: !!msg.on }); sendResponse({ ok: true }); return; }
        if (msg.type === 'learnTids') { Object.assign(tm, msg.map || {}); await loc.set({ tidMap: tm }); sendResponse({ ok: true }); return; }
        if (msg.type === 'openCase') { await ses.set({ ['auto_' + msg.tid]: Date.now() }); await chrome.windows.create({ url: 'https://www.tankauction.com/ca/inc/component/popup/caView.php?tid=' + encodeURIComponent(msg.tid) + '&chkNo=1&TotNo=1&opener_1st_no=' + encodeURIComponent(msg.tid), type: 'popup', width: 1300, height: 900 }); sendResponse({ ok: true }); return; }
        if (msg.type === 'autoStart') { const k = 'auto_' + msg.tid, v = (await ses.get(k))[k]; if (v && Date.now() - v < 120000) { await ses.remove(k); sendResponse({ auto: true }); } else sendResponse({ auto: false }); return; }
        if (msg.type === 'queueDone') {
          if (msg.caseNo && msg.tid) { tm[String(msg.caseNo).replace(/타경/g, '-').replace(/\s+/g, '')] = msg.tid; await loc.set({ tidMap: tm }); }
          const { it, q } = await qLoad(); if (q) { q.done = Array.from(new Set((q.done || []).concat([String(msg.caseNo || '').replace(/타경/g, '-').replace(/\s+/g, '')]))); q.tids = Object.assign(q.tids || {}, tm); await qSave(it, q); }
          sendResponse({ ok: true });
          // 끝나면 다음 사건 자동 열기(사용자가 켠 경우: 기본 켜짐). 8초 기다린 뒤 번호를 아는 다음 사건 하나만 열고, 하루 30건까지
          const cv = (await loc.get('chainOn')).chainOn, on = cv === undefined ? true : cv, today = new Date().toISOString().slice(0, 10), cnt = ((await loc.get('chainCnt')).chainCnt) || { d: today, n: 0 };
          if (on && q) { const c = cnt.d === today ? cnt : { d: today, n: 0 }; if (c.n < 30) { const dn = new Set(q.done || []), nxt = (q.items || []).find((i) => !dn.has(String(i.caseNo).replace(/타경/g, '-').replace(/\s+/g, '')) && tm[String(i.caseNo).replace(/타경/g, '-').replace(/\s+/g, '')]); if (nxt) { await new Promise((r) => setTimeout(r, 8000)); const tid = tm[String(nxt.caseNo).replace(/타경/g, '-').replace(/\s+/g, '')]; c.n++; await loc.set({ chainCnt: c }); await ses.set({ ['auto_' + tid]: Date.now() }); await chrome.windows.create({ url: 'https://www.tankauction.com/ca/inc/component/popup/caView.php?tid=' + encodeURIComponent(tid) + '&chkNo=1&TotNo=1&opener_1st_no=' + encodeURIComponent(tid), type: 'popup', width: 1300, height: 900 }); } } }
          return;
        }
      } catch (e) { sendResponse({ ok: false, error: String(e) }); }
    })();
    return true;
  }
  // 글자 없는 그림 PDF의 쪽 그림을 내려받기 폴더/tank-ocr 에 저장(글자 인식용)
  if (msg && msg.type === 'saveImages') {
    (async () => {
      let saved = 0;
      try {
        for (let i = 0; i < (msg.images || []).length; i++) {
          await chrome.downloads.download({ url: msg.images[i], filename: 'tank-ocr/' + String(msg.tid || 'x') + '_' + String(msg.key || 'p') + '_p' + (i + 1) + '.png', saveAs: false, conflictAction: 'overwrite' });
          saved++;
        }
      } catch (e) {}
      sendResponse({ ok: saved > 0, saved });
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
