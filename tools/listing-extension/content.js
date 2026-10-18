// 호가 보내기 - 네이버 부동산 단지 페이지에 버튼 하나를 띄움. 눌렀을 때만 지금 열려 있는 페이지의 매물 목록을 읽어 보냄(자동 순회·자동 이동 없음).
(function () {
  if (document.getElementById('hg-send-btn')) return;
  const btn = document.createElement('button');
  btn.id = 'hg-send-btn';
  btn.textContent = '📤 호가 보내기';
  btn.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#1e5eff;color:#fff;border:none;border-radius:20px;padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.3);';
  document.body.appendChild(btn);
  const toast = (t, ok) => { btn.textContent = t; btn.style.background = ok === false ? '#c62828' : (ok ? '#2e7d32' : '#1e5eff'); };
  const count = (el) => ((el.innerText || '').match(/(^|\n)매매\s/g) || []).length;
  // 매물 목록이 들어 있는 스크롤 영역 찾기: 스크롤 가능하고 '매매' 줄이 가장 많은 요소
  const findScroller = () => {
    let best = null, bestN = 0;
    document.querySelectorAll('div,ul,section').forEach((el) => {
      if (el.scrollHeight <= el.clientHeight + 100) return;
      const oy = getComputedStyle(el).overflowY;
      if (oy !== 'auto' && oy !== 'scroll') return;
      const n = count(el);
      if (n > bestN) { best = el; bestN = n; }
    });
    return best;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      toast('매물 읽는 중…');
      const sc = findScroller();
      let target = sc || document.body;
      if (sc) {
        // 목록 끝까지 한 화면씩 내려 모두 불러옴(최대 40번, 새로 안 늘면 중단)
        let same = 0, last = count(sc);
        for (let i = 0; i < 40 && same < 3; i++) {
          sc.scrollTop += Math.max(300, sc.clientHeight * 0.9);
          await sleep(700);
          const n = count(sc);
          same = n === last ? same + 1 : 0; last = n;
        }
      }
      const text = target.innerText || '';
      const n = (text.match(/(^|\n)매매\s/g) || []).length;
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
