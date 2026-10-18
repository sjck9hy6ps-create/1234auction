// 호가 보내기 - 네이버 부동산 단지 페이지에 버튼 하나를 띄움. 눌렀을 때만 지금 열려 있는 페이지의 매물 목록을 읽어 보냄(자동 순회·자동 이동 없음).
(function () {
  if (document.getElementById('hg-send-btn')) return;
  const btn = document.createElement('button');
  btn.id = 'hg-send-btn';
  btn.textContent = '📤 호가 보내기';
  btn.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#1e5eff;color:#fff;border:none;border-radius:20px;padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.3);';
  document.body.appendChild(btn);
  const toast = (t, ok) => { btn.textContent = t; btn.style.background = ok === false ? '#c62828' : (ok ? '#2e7d32' : '#1e5eff'); };
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
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      toast('매물 읽는 중…');
      let sc = findScroller();
      let target = sc || document.body;
      // 목록 끝까지 한 화면씩 내려 모두 불러옴(최대 50번, 3번 연속 새로 안 늘면 중단). 목록 영역을 못 찾으면 페이지 자체를 내림
      const scrollOnce = () => { if (sc) sc.scrollTop += Math.max(300, sc.clientHeight * 0.9); else window.scrollBy(0, Math.max(300, window.innerHeight * 0.9)); };
      // 스크롤하며 보이는 매물 덩어리를 계속 모음(목록이 화면 밖 항목을 지우는 방식이어도 빠지지 않게). 덩어리 = '○○ 101동' 머리 줄부터 다음 머리 줄 전까지
      const blocks = new Map();
      const harvest = () => {
        const lines = (document.body.innerText || '').split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
        let cur = null;
        const flush = () => { if (cur && cur.some((l) => /^매매\s*\d/.test(l))) blocks.set(cur.join('\n'), 1); cur = null; };
        for (const ln of lines) {
          if (/\d+동\s*$/.test(ln) && !/^(매매|전세|월세)/.test(ln) && ln.length < 40) { flush(); cur = [ln]; }
          else if (cur) cur.push(ln);
        }
        flush();
      };
      const cnt = () => { harvest(); return blocks.size; };
      let same = 0, last = cnt();
      for (let i = 0; i < 50 && same < 3; i++) {
        scrollOnce();
        await sleep(700);
        // 한 번 더 찾아봄: 처음엔 안 보이던 목록 영역이 내려가며 생길 수 있음
        if (!sc) { const s2 = findScroller(); if (s2) { sc = s2; } }
        const n = cnt();
        same = n === last ? same + 1 : 0; last = n;
      }
      harvest();
      const text = blocks.size ? [...blocks.keys()].join('\n\n') : (document.body.innerText || '');
      const n = (text.match(/(^|\n)매매\s*\d/g) || []).length;
      if (!n) { toast('매매 매물을 못 찾았어요', false); return; }
      chrome.runtime.sendMessage({ type: 'send', text, url: location.href }, (res) => {
        if (res && res.ok) toast('✅ 보냈어요 (매매 ' + n + '건)', true);
        else toast('❌ 보내기 실패', false);
        setTimeout(() => { btn.textContent = '📤 호가 보내기'; btn.style.background = '#1e5eff'; btn.disabled = false; }, 4000);
      });
      return;
    } catch (e) { toast('오류: ' + e.message, false); }
    setTimeout(() => { btn.textContent = '📤 호가 보내기'; btn.style.background = '#1e5eff'; btn.disabled = false; }, 4000);
  };
})();
