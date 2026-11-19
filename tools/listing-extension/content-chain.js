// 호가 자동 진행(0.8.0, 사용자 요청 2026-11-19): 앱이 만든 대기열(최대 30곳)을 한 번 눌러 시작하면, 이 탭에서 단지 페이지를 하나씩 열어 → 매물 목록을 끝까지 읽어 → 앱에 보내고 → 20~60초 쉬고 → 다음 단지로 넘어감.
// 안전장치: 하루 30곳 · 단지 사이 20~60초 무작위 · 로그인/캡차/접속 제한 화면이 뜨면 즉시 멈춤 · 3번 연속 못 읽으면 멈춤 · 시작한 탭에서만 동작 · 언제든 ⏹ 멈추기. 로그인·캡차는 다루지 않음(직접 해야 함).
(function () {
  if (window.__hgChain) return; window.__hgChain = true;
  const L = window.HGChain; if (!L) return;
  const LIMIT = 30, FAIL_LIMIT = 5, SEARCH = 'https://new.land.naver.com/search?sk=';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const bg = (m) => new Promise((res) => { try { chrome.runtime.sendMessage(m, (r) => res(chrome.runtime.lastError ? null : r)); } catch (e) { res(null); } });
  const getSt = async () => ((await chrome.storage.local.get('hchain')).hchain) || null;
  const setSt = async (st) => { await chrome.storage.local.set({ hchain: st }); return st; };

  // ---- 화면 패널(왼쪽 아래) ----
  const box = document.createElement('div'); box.id = 'hg-chain-box';
  box.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:2147483647;background:#111827;color:#fff;border-radius:14px;padding:10px 12px;font:13px/1.5 sans-serif;max-width:300px;box-shadow:0 2px 10px rgba(0,0,0,.35);';
  const line = document.createElement('div'); const row = document.createElement('div'); row.style.marginTop = '6px';
  box.appendChild(line); box.appendChild(row); document.body.appendChild(box);
  const mkBtn = (t, bgc, fn) => { const b = document.createElement('button'); b.textContent = t; b.style.cssText = 'margin-right:6px;border:none;border-radius:12px;padding:6px 10px;font-size:12px;font-weight:700;cursor:pointer;color:#fff;background:' + bgc; b.onclick = fn; return b; };
  const show = (txt, btns) => { line.textContent = txt; row.textContent = ''; (btns || []).forEach((b) => row.appendChild(b)); };

  const stop = async (reason, ok) => {
    const st = (await getSt()) || {}; st.on = false; st.stop = reason; st.stopAt = Date.now(); await setSt(st);
    show((ok ? '✅ ' : '⏹ ') + '호가 자동 진행 멈춤: ' + reason + (st.count ? ' (오늘 ' + st.count + '곳)' : ''), [mkBtn('닫기', '#475569', () => box.remove())]);
  };
  const queriesOf = (c) => { const a = []; if (c.addr) a.push(String(c.addr).trim()); a.push(String(c.name || '').trim()); const b = (String(c.name || '').trim() + ' ' + String(c.dong || '').trim()).trim(); if (b && a.indexOf(b) < 0) a.push(b); return a.filter(Boolean); };
  const searchUrl = (c, qi) => SEARCH + encodeURIComponent(queriesOf(c)[qi || 0] || c.name);
  const advance = async () => {
    let st = await getSt(); if (!st || !st.on) return;
    if (st.day !== L.dayKey()) { st.day = L.dayKey(); st.count = 0; st.fails = 0; }
    const why = L.shouldStop(st, LIMIT, FAIL_LIMIT); if (why) { await stop(why, !/연속/.test(why)); return; }
    const r = await bg({ type: 'hqGet' }); const q = r && r.q;
    if (!q) { await stop('앱에 대기열이 없어요(앱 → 📋 호가 모으기에서 만들어 주세요)'); return; }
    const handled = {}; Object.keys(q.handled || {}).forEach((k) => { handled[k] = 1; });
    const it = L.nextItem(q, handled);
    if (!it) { await stop('대기열을 모두 처리했어요 ✅', true); return; }
    st.cur = { key: it.key, name: it.name, dong: it.dong || '', addr: it.addr || '', step: it.url ? 'complex' : 'search', qi: 0, at: Date.now() };
    await setSt(st);
    show('➡ 다음 단지로 이동: ' + it.name);
    location.href = it.url || searchUrl(st.cur, 0);
  };
  // 실패 때 화면 요소 정보(짧은 글자 요소의 태그·클래스·글자)를 남겨서 어디를 눌러야 하는지 나중에 확인할 수 있게 함
  const diag = () => { try { const out = [], seen = {}; document.querySelectorAll('body *').forEach((e) => { if (out.length >= 28 || (e.closest && e.closest('#hg-chain-box')) || e.children.length > 2) return; const t = String(e.innerText || e.textContent || '').trim().split('\n')[0]; if (!t || t.length > 24) return; const r = e.getBoundingClientRect(); if (r.width < 5 || r.height < 5 || r.bottom < 0 || r.top > innerHeight) return; const k = t; if (seen[k]) return; seen[k] = 1; out.push(e.tagName.toLowerCase() + '.' + String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className || '').split(/\s+/)[0].slice(0, 28) + ':' + t); }); return out.join(' | ').slice(0, 1200); } catch (e) { return ''; } };
  const mark = async (st, status, note) => { await bg({ type: 'hqMark', key: st.cur.key, status, note }); };
  const countdown = async (ms, label) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const st = await getSt(); if (!st || !st.on) return false;
      show('⏳ ' + label + ' · ' + Math.ceil((end - Date.now()) / 1000) + '초 뒤 다음 단지 (오늘 ' + (st.count || 0) + '/' + LIMIT + ')', [mkBtn('⏹ 멈추기', '#dc2626', userStop)]);
      await sleep(1000);
    }
    return true;
  };
  const userStop = async () => { await stop('직접 멈췄어요'); };

  const fail = async (st, note) => {
    st.fails = (st.fails || 0) + 1; await setSt(st); await mark(st, 'fail', note);
    const ok = await countdown(L.jitter(8000, 20000), '못 읽었어요(' + note + ')');
    if (ok) await advance();
  };

  const run = async () => {
    const st = await getSt();
    show('호가 자동 진행 확인 중…');
    // 시작 버튼(진행 중이 아닐 때)
    if (!st || !st.on) {
      const r = await bg({ type: 'hqGet' }); const q = r && r.q;
      if (!q || !q.items || !q.items.length) { show('호가 자동 진행: 앱에 대기열이 없어요 (앱 → 📋 호가 모으기 → 대기열 만들기)' + (st && st.stop ? ' · 지난번: ' + st.stop : ''), [mkBtn('닫기', '#475569', () => box.remove())]); return; }
      const left = q.items.filter((i) => !(q.handled || {})[i.key || L.itemKey(i)]).length;
      show('📋 호가 자동 진행 · 대기열 ' + q.items.length + '곳 중 ' + left + '곳 남음' + (st && st.stop ? '\n지난번: ' + st.stop : ''), [
        mkBtn('▶ 자동 진행 시작', '#16a34a', async () => {
          const me = await bg({ type: 'whoami' });
          const day = L.dayKey(), prev = st && st.day === day ? st : {};
          await setSt({ on: true, owner: me && me.tabId, day, count: prev.count || 0, fails: 0, cur: null, stop: null });
          await advance();
        }), mkBtn('닫기', '#475569', () => box.remove())]);
      return;
    }
    // 진행 중: 시작한 탭에서만 동작
    const me = await bg({ type: 'whoami' }); if (!me || me.tabId !== st.owner) { box.remove(); return; }
    const blk = L.blockedReason(location.href, document.body ? document.body.innerText : ''); if (blk) { await stop(blk); return; }
    if (!st.cur) { await advance(); return; }
    if (Date.now() - st.cur.at > 15 * 60 * 1000) { await fail(st, '한 단지에 15분 넘게 걸렸어요'); return; }
    const onComplex = /\/complexes\/\d+/.test(location.pathname);
    if (!onComplex) {   // 검색 화면: 지도 위 단지 표시에는 이름이 없고 가격·면적뿐이라(이름은 지도 그림 글자), 검색창에 이름을 쳐서 나오는 자동완성 목록(이름+주소 글자)에서 목표 단지를 골라 누름
      const qs = queriesOf(st.cur), qtext = qs[st.cur.qi || 0] || st.cur.name;
      let clicked = false, note = '', cands = [];
      const findInput = () => document.querySelector('.search_area input[type="text"], .search_area input, input[placeholder*="검색"], input[type="search"]');
      let inp = null; for (let i = 0; i < 8 && !inp; i++) { inp = findInput(); if (!inp) await sleep(1000); }
      if (!inp) note = '검색창을 못 찾음';
      else {
        show('⌨ 「' + qtext + '」 검색창에 입력', [mkBtn('⏹ 멈추기', '#dc2626', userStop)]);
        try { inp.focus(); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(inp, qtext); inp.dispatchEvent(new Event('input', { bubbles: true })); inp.dispatchEvent(new Event('keyup', { bubbles: true })); } catch (e) { note = '입력 실패'; }
        const ir = inp.getBoundingClientRect();
        const readCands = () => { const out = []; document.querySelectorAll('li,a,button,div,span').forEach((e) => { if ((e.closest && e.closest('#hg-chain-box')) || e.children.length > 8 || e === inp) return; const t = String(e.innerText || '').trim(); if (!t || t.length > 140) return; const r = e.getBoundingClientRect(); if (r.width < 20 || r.height < 10 || r.top < ir.bottom - 4 || r.top > innerHeight || r.left < ir.left - 30 || r.left > ir.right + 30) return; out.push({ el: e, first: t.split('\n')[0].trim(), full: t.replace(/\n+/g, ' ') }); }); return out; };
        let pick = -1;
        for (let i = 0; i < 12 && pick < 0; i++) { await sleep(800); cands = readCands(); pick = L.pickSuggestion(cands, st.cur); show('🔎 자동완성에서 「' + st.cur.name + '」 찾는 중… (후보 ' + cands.length + '개)', [mkBtn('⏹ 멈추기', '#dc2626', userStop)]); }
        if (pick >= 0) {
          show('🖱 「' + st.cur.name + '」 자동완성 항목을 눌러요'); const el = cands[pick].el;
          ['mousedown', 'mouseup', 'click'].forEach((t) => { try { el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })); } catch (e) {} }); try { el.click(); } catch (e) {}
          for (let k = 0; k < 10 && !/\/complexes\/\d+/.test(location.pathname); k++) await sleep(1000);
          clicked = /\/complexes\/\d+/.test(location.pathname);
          if (!clicked) note = '항목을 눌렀지만 단지 화면으로 안 넘어감';
        } else note = '자동완성에 이름이 맞는 단지가 없음(후보 ' + cands.length + '개)';
      }
      if (clicked) { st.cur.step = 'complex'; st.cur.at = Date.now(); await setSt(st); await sleep(L.jitter(1500, 3000)); return run(); }   // 같은 화면 안에서 주소만 바뀌어 새로고침이 없으므로 이어서 진행
      if ((st.cur.qi || 0) + 1 < qs.length) { st.cur.qi = (st.cur.qi || 0) + 1; st.cur.at = Date.now(); await setSt(st); show('🔁 다른 검색어로 다시 찾아요: ' + qs[st.cur.qi]); await sleep(L.jitter(1500, 3500)); location.href = searchUrl(st.cur, st.cur.qi); return; }
      await fail(st, note + ' 자동완성 후보: ' + cands.slice(0, 10).map((c) => c.full.slice(0, 40)).join(' | ') + ' · 입력창:' + (inp ? 'O' : 'X')); return;
    }
    if (st.cur.sent) { const ok = await countdown(L.jitter(20000, 60000), '완료'); if (ok) await advance(); return; }   // 새로고침 등으로 다시 열렸을 때 같은 단지를 다시 보내지 않음
    show('📖 ' + st.cur.name + ' 매물 읽는 중…', [mkBtn('⏹ 멈추기', '#dc2626', userStop)]);
    await sleep(L.jitter(4000, 7000));   // 화면이 그려질 때까지
    for (let i = 0; i < 15 && !/(^|\n)매매\s*\d/.test(document.body.innerText || ''); i++) await sleep(1000);
    const cur = await getSt(); if (!cur || !cur.on) return;
    let col = await window.hgCollect().catch(() => null);
    if (col && col.expected && col.n < col.expected * 0.9) { show('↻ ' + col.n + '/' + col.expected + '건만 읽혀서 한 번 더 내려요'); const c2 = await window.hgCollect().catch(() => null); if (c2 && c2.n > col.n) col = c2; }   // 덜 읽혔으면 한 번 더(이미 불러온 목록 위에서 다시 끝까지)
    if (!col || !col.n) {
      const sp = (x) => String(x || '').replace(/[\s·.\-_,()]/g, '').toLowerCase(), T = sp(st.cur.name), bodyN = sp(String(document.body.innerText || '').slice(0, 4000));   // '아파트'를 떼지 않은 이름으로 비교('삼성아파트'→'삼성'은 너무 짧아 오인)
      if (T.length >= 3 && bodyN.indexOf(T) >= 0) {   // 같은 이름 단지 화면은 열렸는데 매매 매물이 0건 → 실패가 아니라 '매물 없음'(정상)
        cur.fails = 0; cur.count = (cur.count || 0) + 1; await setSt(cur); await mark(cur, 'none', '매매 매물 0건(단지 화면은 열림)');
        const ok0 = await countdown(L.jitter(20000, 60000), st.cur.name + ' 매물 없음'); if (ok0) await advance(); return;
      }
      await fail(cur, '매매 매물을 못 찾았어요(다른 단지일 수 있음) 화면: ' + document.body.innerText.slice(0, 120).replace(/\n+/g, ' / ')); return;
    }
    const hm = L.headersMatch(col.text, st.cur.name);
    if (hm === false) {   // 다른 단지 화면이면 보내지 않음(예: 영천마을주공아파트를 찾는데 영천마을주공9단지가 열림)
      const first = (String(col.text).split(/\n/)[0] || '').slice(0, 30);
      await fail(cur, '다른 단지 화면이 열렸어요(첫 매물: ' + first + ')'); return;
    }
    show('📤 ' + st.cur.name + ' ' + col.n + '건 앱에 보내는 중…');
    const res = await bg({ type: 'send', text: col.text, url: location.href });
    if (!res || !res.ok) { await fail(cur, '앱으로 보내기 실패'); return; }
    cur.fails = 0; cur.count = (cur.count || 0) + 1; cur.cur.sent = true; await setSt(cur);
    await mark(cur, 'ok', col.n + '건' + (hm === null ? ' (단지 이름 확인 불가)' : '') + (col.expected ? ' / 화면 표시 ' + col.expected + '건' + (col.n < col.expected ? ' ⚠️ 덜 읽힘' : '') : '') + (col.info ? ' · 스크롤:' + col.info : ' · 스크롤 영역 못 찾음'));
    const why = L.shouldStop(cur, LIMIT, FAIL_LIMIT); if (why) { await stop(why, true); return; }
    const ok = await countdown(L.jitter(20000, 60000), st.cur.name + ' ' + col.n + '건 완료');
    if (ok) await advance();
  };
  run().catch(async (e) => { try { await stop('오류: ' + (e && e.message ? e.message : e)); } catch (x) {} });
})();
