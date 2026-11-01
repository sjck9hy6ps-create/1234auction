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
  if (msg && ['queueGet', 'queueDone', 'learnTids', 'openCase', 'autoStart', 'chainSet', 'prog', 'chainFail', 'chainStart', 'clickPending', 'clickFail', 'pendingRow', 'rowMissing'].indexOf(msg.type) >= 0) {
    (async () => {
      const QID = 'queue', loc = chrome.storage.local, ses = chrome.storage.session;
      const qLoad = async () => { const list = await fetch(APP + '/api/auction?kind=listingRaw', { cache: 'no-store' }).then((x) => x.json()); const it = Array.isArray(list) ? list.find((x) => x.id === QID) : null; let q = null; try { q = it && JSON.parse(it.text); } catch (e) {} return { it, q }; };
      const qSave = async (it, q) => { await fetch(APP + '/api/auction?kind=listingRaw', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: QID, at: (it && it.at) || new Date().toISOString(), kind: 'queue', url: '', text: JSON.stringify(q), done: true, appliedAt: new Date().toISOString() }) }); };
      const norm = (x) => String(x || '').replace(/타경/g, '-').replace(/\s+/g, '');
      const openTid = async (tid, caseNo) => { await ses.set({ ['auto_' + tid]: { at: Date.now(), caseNo: caseNo || '' } }); await chrome.windows.create({ url: 'https://www.tankauction.com/ca/inc/component/popup/caView.php?tid=' + encodeURIComponent(tid) + '&chkNo=1&TotNo=1&opener_1st_no=' + encodeURIComponent(tid), type: 'popup', width: 1300, height: 900 }); };
      // 다음 사건 열기: 번호를 아는 미완료 사건 1건(하루 30건 상한). wait=true면 8초 뒤
      const TKURL = ['https://www.tankauction.com/*', 'https://tankauction.com/*'];
      // 번호를 모르는 사건: 열려 있는 탱크옥션 목록 탭에서 그 사건 줄을 대신 눌러 사이트가 창을 열게 함
      const viaList = async (caseNo, name) => {
        const tabs = (await chrome.tabs.query({ url: TKURL })).filter((t) => !/\/popup\//.test(t.url || ''));
        for (const t of tabs) {
          await ses.set({ clickOpen: { caseNo, at: Date.now() } });
          const r = await new Promise((res) => { try { chrome.tabs.sendMessage(t.id, { type: 'clickRow', caseNo, name }, (x) => res(chrome.runtime.lastError ? null : x)); } catch (e) { res(null); } });
          if (r && r.ok) return true;
        }
        await ses.remove('clickOpen');
        // 이 목록에 없으면 목록 탭을 그 사건번호 검색 결과로 바꾸고, 다 열리면 content가 줄을 눌러 이어감
        const lt = tabs.find((t) => /caList\.php/.test(t.url || '')), m = String(caseNo).match(/^(\d{4})-(\d+)(?:\((\d+)\))?$/);
        if (lt && m) { await ses.set({ pendingRow: { caseNo, name: name || '', at: Date.now() } }); await chrome.tabs.update(lt.id, { url: 'https://www.tankauction.com/ca/caList.php?sn1=' + m[1] + '&sn2=' + m[2] + (m[3] ? '&pn=' + m[3] : '') }); return true; }
        return false;
      };
      // 다음 사건 열기: 미완료 사건을 차례로 - 번호를 알면 바로 열고, 모르면 목록 탭의 줄을 눌러 열기(하루 30건 상한). wait=true면 8초 뒤
      const chainNext = async (q, tm, wait) => {
        if (!q) return false; tm = Object.assign({}, q.tids || {}, tm);  // 서버 대기열에 기록된 번호(앱이 남긴 것)도 함께 사용
        const today = new Date().toISOString().slice(0, 10), cnt0 = ((await loc.get('chainCnt')).chainCnt) || { d: today, n: 0 }, c = cnt0.d === today ? cnt0 : { d: today, n: 0 };
        if (c.n >= 60) { await loc.set({ qStatus: { step: '⏸ 오늘 자동으로 연 사건이 60건에 도달해 멈췄어요(탱크옥션 부담을 줄이는 하루 상한) - 내일 다시 시작하세요', tid: '', caseNo: '', at: Date.now() } }); return false; }
        const dn = new Set((q.done || []).concat(q.failed || [])), todo = (q.items || []).filter((i) => !dn.has(norm(i.caseNo))); if (!todo.length) return false;
        if (wait) await new Promise((r) => setTimeout(r, 8000));
        for (const nxt of todo) {
          const cn = norm(nxt.caseNo);
          if (tm[cn]) { c.n++; await loc.set({ chainCnt: c, qStatus: { step: '다음 사건 여는 중', tid: tm[cn], caseNo: cn, at: Date.now() } }); await openTid(tm[cn], cn); return true; }
          if (await viaList(cn, nxt.name)) { c.n++; await loc.set({ chainCnt: c, qStatus: { step: '목록에서 다음 사건 줄을 누르는 중', tid: '', caseNo: cn, at: Date.now() } }); return true; }
        }
        await loc.set({ qStatus: { step: '⏸ 이어서 열 사건이 이 목록에 없어요 - 대기열 사건이 보이는 탱크옥션 목록(매각기일 등)을 열어 두고 다시 시작하세요', tid: '', caseNo: '', at: Date.now() } }); return false;
      };
      try {
        let tm = ((await loc.get('tidMap')).tidMap) || {}; if (((await loc.get('tidMapVer')).tidMapVer) !== 5) { tm = {}; await loc.set({ tidMap: {}, tidMapVer: 5, chainCnt: { d: '', n: 0 } }); }  // 0.5.1~0.5.2에서 잘못 기억된 번호 초기화
        if (msg.type === 'chainStart') { const { q } = await qLoad(); sendResponse({ ok: await chainNext(q, tm, false) }); return; }
        if (msg.type === 'chainFail' && msg.reason === 'popup') { await loc.set({ qStatus: { step: '⛔ 팝업 차단 - 크롬에서 tankauction.com 팝업을 허용한 뒤 다시 시작하세요', tid: msg.tid || '', caseNo: '', at: Date.now() }, chainStop: Date.now() }); try { const tabs = await chrome.tabs.query({ url: ['https://www.tankauction.com/*', 'https://tankauction.com/*'] }); const ids = tabs.filter((t) => /\/popup\//.test(t.url || '') && new RegExp('[?&](tid|opener_1st_no)=' + String(msg.tid) + '(&|$)').test(t.url || '')).map((t) => t.id); setTimeout(() => chrome.tabs.remove(ids).catch(() => {}), 12000); } catch (e) {} sendResponse({ ok: true }); return; }
        if (msg.type === 'chainFail') { const { it, q } = await qLoad(); const rev = Object.keys(tm).find((k) => tm[k] === String(msg.tid || '')); if (q && rev) { q.failed = Array.from(new Set((q.failed || []).concat([rev]))); await qSave(it, q); } sendResponse({ ok: true }); try { const tabs = await chrome.tabs.query({ url: ['https://www.tankauction.com/*', 'https://tankauction.com/*'] }); const ids = tabs.filter((t) => /\/popup\//.test(t.url || '') && new RegExp('[?&](tid|opener_1st_no)=' + String(msg.tid) + '(&|$)').test(t.url || '')).map((t) => t.id); if (ids.length) await chrome.tabs.remove(ids); } catch (e) {} await chainNext(q, tm, true); return; }
        if (msg.type === 'queueGet') { const { q } = await qLoad(); const cv = (await loc.get('chainOn')).chainOn; const stt = ((await loc.get('qStatus')).qStatus) || null; sendResponse({ q, tids: tm, chainOn: cv === undefined ? true : cv, status: stt }); return; }
        if (msg.type === 'prog') { const rev = Object.keys(tm).find((k) => tm[k] === String(msg.tid || '')); await loc.set({ qStatus: { step: String(msg.step || ''), tid: msg.tid || '', caseNo: rev || '', at: Date.now() } }); sendResponse({ ok: true }); return; }
        if (msg.type === 'chainSet') { await loc.set({ chainOn: !!msg.on }); sendResponse({ ok: true }); return; }
        if (msg.type === 'learnTids') { const mp = Object.assign({}, msg.map || {}); if (msg.hay) { const { q: ql } = await qLoad(); Object.keys(mp).forEach((k) => { const qi = ql && (ql.items || []).find((i) => norm(i.caseNo) === k), nm = qi && String(qi.name || '').replace(/\s+/g, '').slice(0, 4); if (nm && nm.length >= 3 && String(msg.hay).indexOf(nm) < 0) delete mp[k]; }); } { const bad = ((await loc.get('badTids')).badTids) || {}; Object.keys(mp).forEach((k) => { if (bad[String(mp[k])] === k) delete mp[k]; }); } Object.assign(tm, mp); await loc.set({ tidMap: tm }); sendResponse({ ok: true }); return; }
        if (msg.type === 'openCase') { await ses.set({ ['auto_' + msg.tid]: { at: Date.now(), caseNo: msg.caseNo || '' } }); await chrome.windows.create({ url: 'https://www.tankauction.com/ca/inc/component/popup/caView.php?tid=' + encodeURIComponent(msg.tid) + '&chkNo=1&TotNo=1&opener_1st_no=' + encodeURIComponent(msg.tid), type: 'popup', width: 1300, height: 900 }); sendResponse({ ok: true }); return; }
        if (msg.type === 'pendingRow') { const pr = (await ses.get('pendingRow')).pendingRow; if (pr && Date.now() - pr.at < 90000) { await ses.remove('pendingRow'); await ses.set({ clickOpen: { caseNo: pr.caseNo, at: Date.now() } }); await loc.set({ qStatus: { step: '검색 결과에서 줄을 누르는 중', tid: '', caseNo: pr.caseNo, at: Date.now() } }); sendResponse({ caseNo: pr.caseNo, name: pr.name }); } else sendResponse({}); return; }
        if (msg.type === 'rowMissing') { const { it, q } = await qLoad(); await ses.remove('clickOpen'); if (q) { q.failed = Array.from(new Set((q.failed || []).concat([norm(msg.caseNo)]))); await qSave(it, q); } sendResponse({ ok: true }); if (q) await chainNext(q, tm, true); return; }
        if (msg.type === 'clickPending') { const co = (await ses.get('clickOpen')).clickOpen; sendResponse({ pending: !!(co && Date.now() - co.at < 120000) }); return; }
        if (msg.type === 'clickFail') {
          await ses.remove('clickOpen');
          await loc.set({ qStatus: { step: '⛔ 목록의 줄을 눌렀지만 사건 창이 안 열렸어요 - 크롬 팝업 허용(tankauction.com) 확인', tid: '', caseNo: String(msg.caseNo || ''), at: Date.now() }, chainStop: Date.now() });
          try { await fetch(APP + '/api/auction?kind=listingRaw', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: Date.now() + '_clk', at: new Date().toISOString(), kind: 'probe', url: '', text: '【줄클릭실패】 ' + msg.caseNo + '\n' + String(msg.html || '') }) }); } catch (e) {}
          sendResponse({ ok: true }); return;
        }
        if (msg.type === 'autoStart') {
          const k = 'auto_' + msg.tid, v = (await ses.get(k))[k], co = (await ses.get('clickOpen')).clickOpen, nc = norm(msg.caseNo || ''), fresh = (t) => t && Date.now() - t < 120000;
          // 같은 사건번호가 다른 법원에도 있으면 번호가 같아도 엉뚱한 사건일 수 있음 → 대기열의 건물 이름이 화면에 없으면 다른 사건으로 봄
          if (nc && (fresh(v && (v.at || v)) || (co && fresh(co.at)))) {
            const { it: it0, q: q0 } = await qLoad(), qi = q0 && (q0.items || []).find((i) => norm(i.caseNo) === nc), nm = qi && String(qi.name || '').replace(/\s+/g, '').slice(0, 4);
            if (nm && nm.length >= 3 && String(msg.hay || '').indexOf(nm) < 0) {
              await ses.remove(k); await ses.remove('clickOpen'); delete tm[nc]; { const bad = ((await loc.get('badTids')).badTids) || {}; bad[String(msg.tid)] = nc; await loc.set({ badTids: bad }); } await loc.set({ tidMap: tm, qStatus: { step: '같은 사건번호의 다른 법원 사건이라 건너뜀 (' + nc + ')', tid: msg.tid, caseNo: nc, at: Date.now() } });
              if (q0) { if (q0.tids) delete q0.tids[nc]; await qSave(it0, q0); }
              sendResponse({ auto: false, mismatch: true });
              try { const tabs = await chrome.tabs.query({ url: TKURL }); const ids = tabs.filter((t) => /\/popup\//.test(t.url || '') && new RegExp('[?&](tid|opener_1st_no)=' + String(msg.tid) + '(&|$)').test(t.url || '')).map((t) => t.id); if (ids.length) await chrome.tabs.remove(ids); } catch (e) {}
              if (q0) await chainNext(q0, tm, true); return;
            }
          }
          if (v && fresh(v.at || v)) {
            await ses.remove(k); const exp = (v && v.caseNo) || '';
            if (exp && nc && exp !== nc) {  // 기억한 번호가 다른 사건이었음: 바로잡고 이 창은 닫은 뒤 다음으로
              delete tm[exp]; tm[nc] = String(msg.tid); await loc.set({ tidMap: tm, qStatus: { step: '번호가 다른 사건이라 건너뜀 (' + exp + ')', tid: msg.tid, caseNo: exp, at: Date.now() } });
              sendResponse({ auto: false, mismatch: true });
              try { const tabs = await chrome.tabs.query({ url: TKURL }); const ids = tabs.filter((t) => /\/popup\//.test(t.url || '') && new RegExp('[?&](tid|opener_1st_no)=' + String(msg.tid) + '(&|$)').test(t.url || '')).map((t) => t.id); if (ids.length) await chrome.tabs.remove(ids); } catch (e) {}
              const { q } = await qLoad(); await chainNext(q, tm, true); return;
            }
            if (nc) { tm[nc] = String(msg.tid); await loc.set({ tidMap: tm }); }
            sendResponse({ auto: true }); return;
          }
          if (co && fresh(co.at) && nc && co.caseNo === nc) { await ses.remove('clickOpen'); tm[nc] = String(msg.tid); await loc.set({ tidMap: tm }); sendResponse({ auto: true }); return; }
          sendResponse({ auto: false }); return;
        }
        if (msg.type === 'queueDone') {
          if (msg.caseNo && msg.tid) { tm[String(msg.caseNo).replace(/타경/g, '-').replace(/\s+/g, '')] = msg.tid; await loc.set({ tidMap: tm }); }
          const { it, q } = await qLoad(); if (q) { q.done = Array.from(new Set((q.done || []).concat([String(msg.caseNo || '').replace(/타경/g, '-').replace(/\s+/g, '')]))); q.tids = Object.assign(q.tids || {}, tm); await qSave(it, q); }
          sendResponse({ ok: true });
          // 끝나면 다음 사건 자동 열기(체크박스 켜짐일 때)
          const cv2 = (await loc.get('chainOn')).chainOn; if ((cv2 === undefined ? true : cv2) && q) await chainNext(q, tm, true);
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
      for (let i = 0; i < 20; i++) {
        await sleep(1500);
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
