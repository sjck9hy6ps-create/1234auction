// 호가 보내기 - 네이버 부동산 단지 페이지에 버튼 하나를 띄움. 눌렀을 때만 지금 열려 있는 페이지의 매물 목록을 읽어 보냄(자동 순회·자동 이동 없음).
(function () {
  if (document.getElementById('hg-send-btn')) return;
  // 매물 한 건의 가격 줄('매매2억 5,700' · '매매2억 5,000~2억 6,000' · '매매3억'). 단지 요약 줄('매매3.5억~5.5억', 소수점)과 구분
  const ITEM = /^매매\s*\d[\d,]*(?:억|만)?(?:\s*[\d,]+)?(?:\s*~\s*[\d,억만\s]+)?$/;
  const btn = document.createElement('button');
  btn.id = 'hg-send-btn';
  btn.textContent = '📤 호가 보내기';
  btn.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#1e5eff;color:#fff;border:none;border-radius:20px;padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.3);';
  document.body.appendChild(btn);
  const toast = (t, ok) => { btn.textContent = t; btn.style.background = ok === false ? '#c62828' : (ok ? '#2e7d32' : (ok === null ? '#ef6c00' : '#1e5eff')); };
  const count = (el) => ((el.innerText || '').match(/(^|\n)매매\s*\d/g) || []).length; // '매매5억 9,800' 같은 가격 줄(머리글 '매매 전체면적'은 제외)
  // 매물 목록이 들어 있는 스크롤 영역 찾기: 내용이 화면보다 긴 요소 중 '매매 가격' 줄이 있는 것 가운데 가장 안쪽(가장 작은) 요소.
  // overflow 속성이 자바스크립트로 정해지는 경우도 있어서 속성은 보지 않고 실제로 스크롤이 되는지로 판단
  const findScroller = () => {
    let best = null, bestLen = Infinity;
    document.querySelectorAll('div,ul,section,main,aside').forEach((el) => {
      if (el.scrollHeight <= el.clientHeight + 80 || el.clientHeight < 150) return;
      if (count(el) < 1) return;
      const len = (el.innerText || '').length;
      if (len < bestLen) { best = el; bestLen = len; }
    });
    return best;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // 목록 끝까지 내려 읽기(버튼과 자동 진행(content-chain.js)이 같이 씀) → { text, n }
  const collectListings = async () => {
    let sc = findScroller();
    let target = sc || document.body;
    // 목록 끝까지 한 화면씩 내려 모두 불러옴(최대 50번, 3번 연속 새로 안 늘면 중단). 목록 영역을 못 찾으면 페이지 자체를 내림
    const scrollOnce = () => { if (sc) sc.scrollTop += Math.max(300, sc.clientHeight * 0.9); else window.scrollBy(0, Math.max(300, window.innerHeight * 0.9)); };
    // 스크롤하며 보이는 매물 덩어리를 계속 모음(목록이 화면 밖 항목을 지우는 방식이어도 빠지지 않게). 덩어리 = '○○ 101동' 머리 줄부터 다음 머리 줄 전까지
    const blocks = new Map();
    // 2026-11-19: 매물 하나 = '머리줄(단지+동) → 매매 줄 → … → 확인매물/등록일 줄'. 예전엔 머리줄을 '○○ 101동'(숫자+동)으로만 알아봐서 '비동'·'에이동' 단지는 페이지 끝까지 한 덩어리가 되어 같은 매물이 여러 번 겹쳐 담겼음(보라맨션 8건→18건)
    const harvest = () => {
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
    };
    const cnt = () => { harvest(); return blocks.size; };
    // 2026-11-19(사용자: 호가가 40건이 넘는데 21건만 읽힘, 스크롤이 안 됨) - 스크롤 영역을 속성으로 찾는 대신, 화면의 '마지막 매매 매물' 요소를 찾아 그 요소를 화면 끝으로 끌어내리고(scrollIntoView) 그 위로 스크롤되는 가장 가까운 부모도 맨 아래로 내림.
    // 새로 안 늘어도 바로 멈추지 않고(불러오는 시간 1.2초씩, 5번 연속 그대로면 중단), 화면 위쪽 '매매 N' 건수를 알면 그 수에 닿을 때까지 계속함
    const expectedOf = () => { const m = (document.body.innerText || '').match(/(\d{1,4})\s*개\s*매물이\s*있습니다/); return m ? +m[1] : 0; };   // '54\n개 매물이 있습니다'
    const lastItemEl = () => {
      let found = null;
      document.querySelectorAll('div,li,span,a,p,dd').forEach((e) => { if (e.children.length > 4) return; const t = (e.innerText || '').trim(); if (ITEM.test(t.split('\n')[0].trim()) && t.length < 80) found = e; });
      return found;
    };
    const scrollParent = (el) => { for (let p = el; p && p !== document.body && p !== document.documentElement; p = p.parentElement) { let cs = null; try { cs = getComputedStyle(p); } catch (e) {} if (cs && cs.overflowY !== 'visible' && p.scrollHeight > p.clientHeight + 20) return p; } return null; };
    const expected = expectedOf();
    let same = 0, last = cnt(), info = '';
    for (let i = 0; i < 80 && same < 5; i++) {
      const el = lastItemEl();
      if (el) {
        const sp = scrollParent(el); if (sp) { sp.scrollTop = sp.scrollHeight; info = sp.tagName.toLowerCase() + '.' + String(sp.className || '').split(/\s+/)[0].slice(0, 20); }
        try { el.scrollIntoView({ block: 'end' }); } catch (e) {}
        try { (sp || el).dispatchEvent(new WheelEvent('wheel', { deltaY: 600, bubbles: true })); } catch (e) {}
      } else { scrollOnce(); }
      await sleep(1200);
      if (!sc) { const s2 = findScroller(); if (s2) sc = s2; }
      const n = cnt();
      same = n === last ? same + 1 : 0; last = n;
      if (expected && n >= expected) break;
    }
    harvest();
    const text = blocks.size ? [...blocks.keys()].join('\n\n') : (document.body.innerText || '');
    const n = text.split(/\r?\n/).filter((l) => ITEM.test(l.trim())).length;
    return { text, n, expected, info };
  };
  window.hgCollect = collectListings;
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      toast('매물 읽는 중…');
      let { text, n, expected } = await collectListings();
      if (expected && n < expected * 0.9) { toast('↻ ' + n + '/' + expected + '건만 읽혀 한 번 더 내려요…'); const r2 = await collectListings(); if (r2.n > n) { text = r2.text; n = r2.n; } }
      if (!n) { toast('매매 매물을 못 찾았어요', false); return; }
      toast('보내는 중… (' + n + '건' + (expected ? ' / 화면 표시 ' + expected + '건' : '') + ')');
      chrome.runtime.sendMessage({ type: 'send', text, url: location.href }, (res) => {
        if (!res || !res.ok) toast('❌ 보내기 실패', false);
        else if (res.applied) {
          const a = (res.result && res.result.applied) || [];
          if (a.length) toast('✅ 앱에 반영됨: ' + a.slice(0, 2).map((x) => x.name + ' ' + x.pyung + '평 매물 ' + x.n + '건').join(' · '), true);
          else toast('⚠️ 받았지만 반영된 물건이 없어요 (' + ((res.result && res.result.text) || '대상 단지가 아니거나 같은 평형 없음') + ')', false);
        } else toast(res.noApp ? '⏳ 앱 탭이 안 열려 있어요 - 앱을 열면 자동 반영돼요' : '⏳ 앱이 아직 처리 중이에요 - 앱 화면에서 확인하세요', null);
        setTimeout(() => { btn.textContent = '📤 호가 보내기'; btn.style.background = '#1e5eff'; btn.disabled = false; }, 8000);
      });
      return;
    } catch (e) { toast('오류: ' + e.message, false); }
    setTimeout(() => { btn.textContent = '📤 호가 보내기'; btn.style.background = '#1e5eff'; btn.disabled = false; }, 4000);
  };
})();
