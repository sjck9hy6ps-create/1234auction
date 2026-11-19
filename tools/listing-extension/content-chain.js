// 호가 자동 진행(0.8.0, 사용자 요청 2026-11-19): 앱이 만든 대기열(최대 30곳)을 한 번 눌러 시작하면, 이 탭에서 단지 페이지를 하나씩 열어 → 매물 목록을 끝까지 읽어 → 앱에 보내고 → 20~60초 쉬고 → 다음 단지로 넘어감.
// 안전장치: 하루 30곳 · 단지 사이 20~60초 무작위 · 로그인/캡차/접속 제한 화면이 뜨면 즉시 멈춤 · 3번 연속 못 읽으면 멈춤 · 시작한 탭에서만 동작 · 언제든 ⏹ 멈추기. 로그인·캡차는 다루지 않음(직접 해야 함).
(function () {
  if (window.__hgChain) return; window.__hgChain = true;
  const L = window.HGChain; if (!L) return;
  const LIMIT = 30, FAIL_LIMIT = 3, SEARCH = 'https://new.land.naver.com/search?sk=';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const bg = (m) => new Promise((res) => { try { chrome.runtime.sendMessage(m, (r) => res(chrome.runtime.lastError ? null : r)); } catch (e) { res(null); } });
  const getSt = async () => ((await chrome.storage.local.get('hchain')).hchain) || null;
  const setSt = async (st) => { await chrome.storage.local.set({ hchain: st }); return st; };

  // ---- 화면 패널(왼쪽 아래) ----
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:2147483647;background:#111827;color:#fff;border-radius:14px;padding:10px 12px;font:13px/1.5 sans-serif;max-width:300px;box-shadow:0 2px 10px rgba(0,0,0,.35);';
  const line = document.createElement('div'); const row = document.createElement('div'); row.style.marginTop = '6px';
  box.appendChild(line); box.appendChild(row); document.body.appendChild(box);
  const mkBtn = (t, bgc, fn) => { const b = document.createElement('button'); b.textContent = t; b.style.cssText = 'margin-right:6px;border:none;border-radius:12px;padding:6px 10px;font-size:12px;font-weight:700;cursor:pointer;color:#fff;background:' + bgc; b.onclick = fn; return b; };
  const show = (txt, btns) => { line.textContent = txt; row.textContent = ''; (btns || []).forEach((b) => row.appendChild(b)); };

  const stop = async (reason, ok) => {
    const st = (await getSt()) || {}; st.on = false; st.stop = reason; st.stopAt = Date.now(); await setSt(st);
    show((ok ? '✅ ' : '⏹ ') + '호가 자동 진행 멈춤: ' + reason + (st.count ? ' (오늘 ' + st.count + '곳)' : ''), [mkBtn('닫기', '#475569', () => box.remove())]);
  };
  const advance = async () => {
    let st = await getSt(); if (!st || !st.on) return;
    if (st.day !== L.dayKey()) { st.day = L.dayKey(); st.count = 0; st.fails = 0; }
    const why = L.shouldStop(st, LIMIT, FAIL_LIMIT); if (why) { await stop(why, !/연속/.test(why)); return; }
    const r = await bg({ type: 'hqGet' }); const q = r && r.q;
    if (!q) { await stop('앱에 대기열이 없어요(앱 → 📋 호가 모으기에서 만들어 주세요)'); return; }
    const handled = {}; Object.keys(q.handled || {}).forEach((k) => { handled[k] = 1; });
    const it = L.nextItem(q, handled);
    if (!it) { await stop('대기열을 모두 처리했어요 ✅', true); return; }
    st.cur = { key: it.key, name: it.name, dong: it.dong || '', step: it.url ? 'complex' : 'search', at: Date.now() };
    await setSt(st);
    show('➡ 다음 단지로 이동: ' + it.name);
    location.href = it.url || (SEARCH + encodeURIComponent(it.q || (it.name + ' ' + (it.dong || ''))));
  };
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
    const initial = () => { show('호가 자동 진행 준비 중…'); };
    initial();
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
    if (!onComplex) {   // 검색 결과 화면: 이름이 맞는 단지 링크만 눌러 들어감(못 찾으면 건너뜀)
      let href = null;
      for (let i = 0; i < 15 && !href; i++) {
        await sleep(1000);
        const links = [...document.querySelectorAll('a[href*="/complexes/"]')].map((a) => ({ href: a.href, text: (a.innerText || a.textContent || '').trim(), ctx: ((a.closest('li,div') || a).innerText || '').slice(0, 200) }));
        href = L.pickComplexLink(links, st.cur);
      }
      if (!href) { await fail(st, '검색 결과에서 단지를 못 찾았어요'); return; }
      st.cur.step = 'complex'; st.cur.at = Date.now(); await setSt(st);
      await sleep(L.jitter(1500, 4000)); location.href = href; return;
    }
    if (st.cur.sent) { const ok = await countdown(L.jitter(20000, 60000), '완료'); if (ok) await advance(); return; }   // 새로고침 등으로 다시 열렸을 때 같은 단지를 다시 보내지 않음
    show('📖 ' + st.cur.name + ' 매물 읽는 중…', [mkBtn('⏹ 멈추기', '#dc2626', userStop)]);
    await sleep(L.jitter(4000, 7000));   // 화면이 그려질 때까지
    for (let i = 0; i < 15 && !/(^|\n)매매\s*\d/.test(document.body.innerText || ''); i++) await sleep(1000);
    const cur = await getSt(); if (!cur || !cur.on) return;
    const col = await window.hgCollect().catch(() => null);
    if (!col || !col.n) { await fail(cur, '매매 매물을 못 찾았어요'); return; }
    show('📤 ' + st.cur.name + ' ' + col.n + '건 앱에 보내는 중…');
    const res = await bg({ type: 'send', text: col.text, url: location.href });
    if (!res || !res.ok) { await fail(cur, '앱으로 보내기 실패'); return; }
    cur.fails = 0; cur.count = (cur.count || 0) + 1; cur.cur.sent = true; await setSt(cur);
    await mark(cur, 'ok', col.n + '건');
    const why = L.shouldStop(cur, LIMIT, FAIL_LIMIT); if (why) { await stop(why, true); return; }
    const ok = await countdown(L.jitter(20000, 60000), st.cur.name + ' ' + col.n + '건 완료');
    if (ok) await advance();
  };
  run().catch(async (e) => { try { await stop('오류: ' + (e && e.message ? e.message : e)); } catch (x) {} });
})();
