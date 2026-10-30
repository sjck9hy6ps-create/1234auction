// 탱크옥션 상세 보내기(0.4.0: 사건내역·기일내역·문건/송달·현황조사서·부동산표시·감정평가서·매각물건명세서·건물등기·세대열람 탭까지 같이 읽음) - 탱크옥션 물건 상세 페이지에 버튼 하나를 띄움. 눌렀을 때만 지금 열려 있는 페이지의 글(임차인 현황·건물등기·권리분석 등)을 앱에 보냄.
// 로그인은 사용자가 직접 한 화면만 읽음(로그인 정보는 건드리지 않고, 자동으로 다른 페이지로 이동하거나 순회하지 않음).
(function () {
  const ID = 'tk-send-btn';
  const isDetail = () => {
    const t = (document.body && document.body.innerText) || '';
    return /경매\s*\d{4}\s*타경\s*\d+/.test(t) && (/임차인\s?현황/.test(t) || /건물등기/.test(t));
  };

  // 탭 목록(앱의 MYR_TABS와 같은 key). 눌렀을 때만, 같은 페이지 안의 탭 글자만 눌러 보이는 글을 읽음(다른 주소로 이동하는 링크는 누르지 않음)
  const TABS = [
    ['case', '사건내역', /^사건내역/], ['dates', '기일내역', /^기일내역/], ['docs', '문건/송달현황', /^문건\/?송달/],
    ['survey', '현황조사서', /^(현황)?조사서/], ['estate', '부동산표시', /^부동산표시/], ['appraisal', '감정평가서', /^감정평가서/],
    ['spec', '매각물건명세서', /^(매각)?(물건)?(명세서)|^매물명세서/], ['registry', '건물등기', /^건물등기/], ['house', '세대열람', /^세대열람/]
  ];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const bodyText = () => (document.body && document.body.innerText) || '';  // 읽는 동안 보내기 버튼은 숨겨 두므로 버튼 글이 섞이지 않음
  const norm = (x) => x.replace(/\s+/g, ' ').trim();
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const findTab = (re) => {
    const cands = Array.from(document.querySelectorAll('a,button,li,span,div,td,th,label,[role=tab]')).filter((el) => {
      if (el.id === ID || !visible(el)) return false;
      const t = (el.innerText || '').replace(/\s+/g, '').replace(/\d+$/, '');
      if (!t || t.length > 14 || !re.test(t)) return false;
      const nav = (x) => { const h = x.getAttribute('href') || ''; return !!h && !h.startsWith('#') && !/^javascript:/i.test(h); };
      if (Array.from(el.querySelectorAll('a[href]')).some(nav)) return false;
      const a = el.closest('a[href]');
      if (a) { const h = a.getAttribute('href') || ''; if (h && !h.startsWith('#') && !/^javascript:/i.test(h)) return false; }  // 다른 주소로 가는 링크는 누르지 않음
      return true;
    });
    // 가장 안쪽(글자만 가진) 요소를 우선
    cands.sort((x, y) => (x.querySelectorAll('*').length - y.querySelectorAll('*').length));
    return cands[0] || null;
  };
  const waitChange = async (before, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { await sleep(250); if (bodyText() !== before) { await sleep(500); return true; } } return false; };
  const collectTabs = async (onProgress) => {
    const seen = new Set(bodyText().split('\n').map(norm).filter(Boolean));
    let out = '', found = [], missing = [], empty = [];
    for (let i = 0; i < TABS.length; i++) {
      const [key, label, re] = TABS[i]; onProgress(label, i + 1, TABS.length);
      const el = findTab(re);
      if (!el) { missing.push(key); continue; }
      const before = bodyText();
      try { el.click(); } catch (e) { missing.push(key); continue; }
      await waitChange(before, 3000);
      const lines = bodyText().split('\n').map((x) => x.replace(/\s+$/, '')).filter((x) => { const n = norm(x); if (!n || seen.has(n)) return false; seen.add(n); return true; });
      if (!lines.length) { empty.push(key); continue; }
      found.push(key);
      out += '\n【탭:' + key + '|' + label + '】\n' + lines.join('\n').slice(0, 30000);
    }
    return { text: out, found, missing, empty };
  };
  let btn = null;
  const label = '📤 탱크옥션 상세 보내기 (모든 탭)';
  const toast = (t, ok) => { if (!btn) return; btn.textContent = t; btn.style.background = ok === false ? '#c62828' : (ok ? '#2e7d32' : (ok === null ? '#ef6c00' : '#7b1fa2')); };
  const ensure = () => {
    const show = isDetail();
    if (show && !btn) {
      if (document.getElementById(ID)) return;
      btn = document.createElement('button');
      btn.id = ID; btn.textContent = label;
      btn.style.cssText = 'position:fixed;right:16px;bottom:64px;z-index:2147483647;background:#7b1fa2;color:#fff;border:none;border-radius:20px;padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3);';
      document.body.appendChild(btn);
      btn.onclick = async () => {
        btn.disabled = true;
        const full = document.body.innerText || '';
        const s = full.search(/경매\s*\d{4}\s*타경\s*\d+/);
        let text = s >= 0 ? full.slice(s) : full;
        const e = text.search(/\n파일자료\n/);   // 맨 아래 메뉴 이전까지만(필요한 부분 위주, 용량 줄이기)
        if (e > 0) text = text.slice(0, e);
        text = text.slice(0, 100000);
        let tabRes = { found: [], missing: [], empty: [] };
        const oldTitle = document.title; btn.style.display = 'none';
        try { tabRes = await collectTabs((l, i, n) => { document.title = '탭 읽는 중 ' + l + ' (' + i + '/' + n + ')'; }); text += tabRes.text + '\n【수집결과】 found=' + tabRes.found.join(',') + '; missing=' + tabRes.missing.join(',') + '; empty=' + tabRes.empty.join(','); } catch (e) {}
        document.title = oldTitle; btn.style.display = '';
        text = text.slice(0, 190000);
        toast('보내는 중… (탭 ' + tabRes.found.length + '개 읽음' + (tabRes.missing.length ? ', 못 찾은 탭 ' + tabRes.missing.length + '개' : '') + (tabRes.empty.length ? ', 새 글 없음 ' + tabRes.empty.length + '개' : '') + ')');
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
