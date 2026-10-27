// 탱크옥션 상세 보내기 - 탱크옥션 물건 상세 페이지에 버튼 하나를 띄움. 눌렀을 때만 지금 열려 있는 페이지의 글(임차인 현황·건물등기·권리분석 등)을 앱에 보냄.
// 로그인은 사용자가 직접 한 화면만 읽음(로그인 정보는 건드리지 않고, 자동으로 다른 페이지로 이동하거나 순회하지 않음).
(function () {
  const ID = 'tk-send-btn';
  const isDetail = () => {
    const t = (document.body && document.body.innerText) || '';
    return /경매\s*\d{4}\s*타경\s*\d+/.test(t) && (/임차인\s?현황/.test(t) || /건물등기/.test(t));
  };
  let btn = null;
  const label = '📤 탱크옥션 상세 보내기';
  const toast = (t, ok) => { if (!btn) return; btn.textContent = t; btn.style.background = ok === false ? '#c62828' : (ok ? '#2e7d32' : (ok === null ? '#ef6c00' : '#7b1fa2')); };
  const ensure = () => {
    const show = isDetail();
    if (show && !btn) {
      if (document.getElementById(ID)) return;
      btn = document.createElement('button');
      btn.id = ID; btn.textContent = label;
      btn.style.cssText = 'position:fixed;right:16px;bottom:64px;z-index:2147483647;background:#7b1fa2;color:#fff;border:none;border-radius:20px;padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3);';
      document.body.appendChild(btn);
      btn.onclick = () => {
        btn.disabled = true;
        const full = document.body.innerText || '';
        const s = full.search(/경매\s*\d{4}\s*타경\s*\d+/);
        let text = s >= 0 ? full.slice(s) : full;
        const e = text.search(/\n파일자료\n/);   // 맨 아래 메뉴 이전까지만(필요한 부분 위주, 용량 줄이기)
        if (e > 0) text = text.slice(0, e);
        text = text.slice(0, 120000);
        toast('보내는 중…');
        chrome.runtime.sendMessage({ type: 'send', kind: 'tank', text, url: location.href }, (res) => {
          if (!res || !res.ok) toast('❌ 보내기 실패', false);
          else if (res.applied) {
            const a = (res.result && res.result.applied) || [];
            if (a.length) toast('✅ 앱에 반영됨: ' + a[0].name + ' 권리분석 (등기 ' + a[0].n + '건, ' + (a[0].tenants ? '임차인 ' + a[0].tenants + '명' : '임차인 없음') + ')', true);
            else toast('⚠️ 받았지만 반영 못함: ' + ((res.result && res.result.text) || '입찰후보에 없는 사건이에요'), false);
          } else toast(res.noApp ? '⏳ 앱 탭이 안 열려 있어요 - 앱을 열면 자동 반영돼요' : '⏳ 앱이 아직 처리 중이에요 - 앱 화면에서 확인하세요', null);
          setTimeout(() => { if (btn) { btn.textContent = label; btn.style.background = '#7b1fa2'; btn.disabled = false; } }, 8000);
        });
      };
    } else if (!show && btn) { btn.remove(); btn = null; }
  };
  setInterval(ensure, 2000);
  ensure();
})();
