// 호가 보내기 - 네이버 부동산 단지 페이지에 📤 호가 보내기 버튼을 띄움. 사용자가 직접 연 단지 화면에서 매물 목록이 보이면 목록을 끝까지 자동으로 펼쳐(스크롤) 두고(2026-11-19 사용자 요청),
// 버튼을 누르면 읽어서 앱으로 보냄. 다른 페이지로 이동하거나 단지를 대신 열지 않음(자동 이동·자동 순회 없음). 사용자가 직접 스크롤·클릭하면 자동 펼치기는 멈춤.
(function () {
  if (document.getElementById('hg-send-btn')) return;
  // 매물 한 건의 가격 줄('매매2억 5,700' · '매매2억 5,000~2억 6,000' · '매매3억'). 단지 요약 줄('매매3.5억~5.5억', 소수점)과 구분
  const ITEM = /^매매\s*\d[\d,]*(?:억|만)?(?:\s*[\d,]+)?(?:\s*~\s*[\d,억만\s]+)?$/;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---- 버튼 ----
  const mkBtn = (id, label, bottom, bg) => {
    const b = document.createElement('button');
    b.id = id; b.textContent = label;
    b.style.cssText = 'position:fixed;right:16px;bottom:' + bottom + 'px;z-index:2147483647;background:' + bg + ';color:#fff;border:none;border-radius:20px;padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.3);';
    document.body.appendChild(b); return b;
  };
  const btn = mkBtn('hg-send-btn', '📤 호가 보내기', 16, '#1e5eff');
  const toast = (t, ok) => { btn.textContent = t; btn.style.background = ok === false ? '#c62828' : (ok ? '#2e7d32' : (ok === null ? '#ef6c00' : '#1e5eff')); };

  // ---- 매물 읽기 ----
  // 스크롤하며 보이는 매물 덩어리를 계속 모음(목록이 화면 밖 항목을 지우는 방식이어도 빠지지 않게). 매물 하나 = '머리줄(단지+동) → 매매 줄 → … → 확인매물/등록일 줄'
  // (2026-11-19: 예전엔 머리줄을 '○○ 101동'으로만 알아봐서 '비동'·'에이동' 단지는 같은 매물이 여러 번 겹쳐 담겼음 - 보라맨션 8건→18건)
  let blocks = new Map(), blocksFor = location.pathname;
  const resetIfMoved = () => { if (blocksFor !== location.pathname) { blocks = new Map(); blocksFor = location.pathname; } };   // 같은 화면 안에서 다른 단지로 바뀌면 처음부터
  const harvest = () => {
    resetIfMoved();
    const lines = (document.body.innerText || '').split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
    for (let i = 1; i < lines.length; i++) {
      if (!ITEM.test(lines[i])) continue;
      const hdr = lines[i - 1]; if (!hdr || /^(매매|전세|월세)/.test(hdr) || hdr.length > 60) continue;
      const blk = [hdr, lines[i]];
      for (let j = i + 1; j < lines.length && j < i + 12; j++) {
        if (ITEM.test(lines[j]) || lines[j] === '지역 선택') break;
        blk.push(lines[j]);
        if (/^(확인매물|등록일)/.test(lines[j])) break;
      }
      blocks.set(blk.join('\n'), 1);
    }
    return blocks.size;
  };
  const expectedOf = () => { const m = (document.body.innerText || '').match(/(\d{1,4})\s*개\s*매물이\s*있습니다/); return m ? +m[1] : 0; };   // '54\n개 매물이 있습니다'

  // ---- 목록 펼치기(스크롤) ----
  // 네이버는 처음에 20건만 보여 주고 목록을 아래로 내리면 더 불러옴. 어느 요소가 스크롤 영역인지 속성으로 알 수 없어서 여러 방법을 함께 씀:
  // ① 화면의 '마지막 매물' 요소를 찾아 그 요소를 감싸는 모든 부모를 맨 아래로 내림 ② 마지막 매물을 화면 끝으로(scrollIntoView) ③ 휠·스크롤 신호 ④ 페이지 자체 ⑤ '더보기' 버튼
  // ⑥ 맨 아래에서 조금 올렸다 다시 내림(위치가 바뀌어야 더 불러오는 목록 대응)
  const lastItemEl = () => {
    let found = null;
    document.querySelectorAll('div,li,span,a,p,dd').forEach((e) => { if (e.children.length > 4) return; const t = String(e.innerText || '').trim(); if (t.length < 80 && ITEM.test(t.split('\n')[0].trim())) found = e; });
    return found;
  };
  const moreButtons = () => [...document.querySelectorAll('button,a,div,span')].filter((e) => e.children.length <= 2 && /(매물\s*)?더\s*보기|더\s*많은\s*매물|매물\s*더/.test(String(e.innerText || '').trim()) && String(e.innerText || '').trim().length < 14);
  const expandList = async (onProgress, shouldStop) => {
    resetIfMoved();
    const expected = expectedOf();
    let same = 0, last = harvest(), info = '', rounds = 0;
    for (let i = 0; i < 120 && same < 6; i++) {
      if (shouldStop && shouldStop()) break;
      rounds++;
      const el = lastItemEl(), used = [];
      if (el) {
        for (let p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
          if (p.scrollHeight > p.clientHeight + 5) {
            const bottom = p.scrollHeight - p.clientHeight;
            try { if (i % 2 === 1) { p.scrollTop = Math.max(0, bottom - 80); await sleep(120); } p.scrollTop = bottom + 1000; p.dispatchEvent(new Event('scroll', { bubbles: true })); } catch (e) {}
            used.push(p.tagName.toLowerCase() + '.' + String(p.className || '').split(/\s+/)[0].slice(0, 18));
          }
        }
        try { el.scrollIntoView({ block: 'end' }); } catch (e) {}
        try { el.dispatchEvent(new WheelEvent('wheel', { deltaY: 800, bubbles: true })); } catch (e) {}
      }
      try { window.scrollTo(0, document.documentElement.scrollHeight); } catch (e) {}
      const mb = moreButtons()[0]; if (mb) { try { mb.click(); used.push('더보기 버튼'); } catch (e) {} }
      if (used.length) info = used.slice(0, 3).join(' > ');
      await sleep(1300);
      const n = harvest();
      same = n === last ? same + 1 : 0; last = n;
      if (onProgress) onProgress(n, expected, i);
      if (expected && n >= expected) break;
    }
    return { n: last, expected, info: info || '스크롤 영역 못 찾음', rounds };
  };

  // 읽은 매물 글(덩어리) → { text, n }
  const readListings = () => {
    harvest();
    const text = blocks.size ? [...blocks.keys()].join('\n\n') : (document.body.innerText || '');
    const n = text.split(/\r?\n/).filter((l) => ITEM.test(l.trim())).length;
    return { text, n };
  };
  // 목록을 끝까지 펼친 뒤 읽기(보내기 버튼과 시험이 같이 씀) → { text, n, expected, info }
  const collectListings = async (onProgress) => {
    const ex = await expandList(onProgress);
    const r = readListings();
    return { text: r.text, n: r.n, expected: ex.expected, info: ex.info };
  };
  window.hgCollect = collectListings;   // 시험(tests/listing-collect.test.cjs)용
  window.hgExpand = expandList;

  // ---- 자동 펼치기: 단지 화면에 매물 목록이 나타나면 끝까지 내려 모두 불러옴 ----
  let autoPath = null, autoRunning = false, userTouched = false;
  ['wheel', 'keydown', 'mousedown', 'touchstart'].forEach((ev) => { try { window.addEventListener(ev, (e) => { if (autoRunning && e.isTrusted) userTouched = true; }, { capture: true, passive: true }); } catch (e) {} });   // 사용자가 직접 움직이면 자동 펼치기는 멈춤(내 스크롤 신호 isTrusted=false는 무시)
  const idleLabel = () => { btn.textContent = '📤 호가 보내기'; btn.style.background = '#1e5eff'; };
  const autoExpand = async () => {
    autoRunning = true; userTouched = false;
    try {
      toast('⬇ 목록 펼치는 중…', null);
      const r = await expandList((n, expected) => { if (!btn.disabled) toast('⬇ 목록 펼치는 중 ' + n + (expected ? '/' + expected : '') + '건', null); }, () => userTouched);
      if (userTouched) { toast('📤 호가 보내기 (직접 내리는 중 - 끝나면 눌러 주세요)'); btn.style.background = '#1e5eff'; }
      else if (r.expected && r.n < r.expected) { toast('📤 호가 보내기 (' + r.n + '/' + r.expected + '건 펼침 · 스크롤:' + r.info + ')'); btn.style.background = '#ef6c00'; }
      else { toast('📤 호가 보내기 (' + r.n + (r.expected ? '/' + r.expected : '') + '건 펼침 ✅)', true); }
      btn.title = '스크롤 영역: ' + r.info + ' · 반복 ' + r.rounds + '번';
    } catch (e) { idleLabel(); }
    autoRunning = false;
  };
  const autoTick = () => {
    if (autoRunning || btn.disabled) return;
    if (!/\/complexes\/\d+/.test(location.pathname)) return;   // 단지 화면에서만
    const key = location.pathname;
    if (autoPath === key) return;                                    // 같은 단지는 한 번만
    resetIfMoved(); if (harvest() < 1) return;                      // 매물 목록이 나타난 뒤
    autoPath = key;
    setTimeout(() => { if (location.pathname === key) autoExpand(); }, 1500);   // 처음 20건이 다 그려질 때까지 잠깐
  };
  try { setInterval(autoTick, 1500); } catch (e) {}

  // ---- 📤 호가 보내기 ----
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      for (let w = 0; w < 120 && autoRunning; w++) await sleep(500);   // 자동 펼치기가 도는 중이면 끝나기를 기다림
      toast('매물 읽는 중…');
      // 이미 자동으로 펼쳤으면(읽은 건수가 화면 표시 건수에 닿았으면) 다시 내리지 않고 바로 읽음
      resetIfMoved(); let exp = expectedOf(), got = harvest(), n, text, expected = exp;
      if (!exp || got < exp) { const c = await collectListings((nn, ee) => toast('매물 펼치는 중 ' + nn + (ee ? '/' + ee : '') + '건')); text = c.text; n = c.n; expected = c.expected; if (expected && n < expected * 0.9) { toast('↻ ' + n + '/' + expected + '건만 읽혀 한 번 더 내려요…'); const c2 = await collectListings(); if (c2.n > n) { text = c2.text; n = c2.n; } } }
      else { const r = readListings(); text = r.text; n = r.n; }
      if (!n) { toast('매매 매물을 못 찾았어요', false); return; }
      toast('보내는 중… (' + n + '건' + (expected ? ' / 화면 표시 ' + expected + '건' : '') + ')');
      chrome.runtime.sendMessage({ type: 'send', text, url: location.href }, (res) => {
        if (!res || !res.ok) toast('❌ 보내기 실패', false);
        else if (res.applied) {
          const a = (res.result && res.result.applied) || [];
          if (a.length) toast('✅ 앱에 반영됨: ' + a.slice(0, 2).map((x) => x.name + ' ' + x.pyung + '평 매물 ' + x.n + '건').join(' · '), true);
          else toast('⚠️ 받았지만 반영된 물건이 없어요 (' + ((res.result && res.result.text) || '대상 단지가 아니거나 같은 평형 없음') + ')', false);
        } else toast(res.noApp ? '⏳ 앱 탭이 안 열려 있어요 - 앱을 열면 자동 반영돼요' : '⏳ 앱이 아직 처리 중이에요 - 앱 화면에서 확인하세요', null);
        setTimeout(() => { idleLabel(); btn.disabled = false; }, 8000);
      });
      return;
    } catch (e) { toast('오류: ' + e.message, false); }
    setTimeout(() => { idleLabel(); btn.disabled = false; }, 4000);
  };
})();
