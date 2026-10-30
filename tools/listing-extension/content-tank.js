// 탱크옥션 상세 보내기(0.4.2: 상세 팝업의 '파일자료' 메뉴는 눌러도 같은 화면이 바뀌지 않고 참고자료 팝업이 새로 열리므로, 보내기를 누르면 그 팝업을 한 번 열어 그 안의 탭(사건내역~세대열람)을 읽어 상세 글과 합쳐 보냄 / 0.4.1: 참고자료 팝업·iframe 안 글도 읽고, 못 찾은 탭이 있으면 화면 버튼 이름을 같이 보냄, 끝나면 완료 안내창 + 모으려고 열었던 팝업창 자동 닫기 / 0.4.0: 사건내역·기일내역·문건/송달·현황조사서·부동산표시·감정평가서·매각물건명세서·건물등기·세대열람 탭까지 같이 읽음) - 탱크옥션 물건 상세 페이지에 버튼 하나를 띄움. 눌렀을 때만 지금 열려 있는 페이지의 글(임차인 현황·건물등기·권리분석 등)을 앱에 보냄.
// 로그인은 사용자가 직접 한 화면만 읽음(로그인 정보는 건드리지 않고, 자동으로 다른 페이지로 이동하거나 순회하지 않음).
(function () {
  const ID = 'tk-send-btn';
  const isTop = window === window.top;
  const isFile = /\/caFile\.php/.test(location.pathname);   // 참고자료 팝업(사진·지도·등기부·감정평가서·명세서 등)
  const tidOf = () => { const m = location.search.match(/[?&]tid=(\d+)/); return m ? m[1] : ''; };
  const isDetail = () => {
    if (!isTop) return false;
    if (isFile) return true;
    const t = (document.body && document.body.innerText) || '';
    return /경매\s*\d{4}\s*타경\s*\d+/.test(t) && (/임차인\s?현황/.test(t) || /건물등기/.test(t));
  };
  // 같은 사이트 iframe 안의 화면까지 함께 읽음(참고자료가 상세 화면 안 iframe으로 들어 있는 경우)
  const docs = () => { const out = [document]; const walk = (d) => { Array.from(d.querySelectorAll('iframe,frame')).forEach((f) => { try { const x = f.contentDocument; if (x && x.body) { out.push(x); walk(x); } } catch (e) {} }); }; walk(document); return out; };

  // 탭 목록(앱의 MYR_TABS와 같은 key). 눌렀을 때만, 같은 페이지 안의 탭 글자만 눌러 보이는 글을 읽음(다른 주소로 이동하는 링크는 누르지 않음)
  const TABS = [
    ['case', '사건내역', /^사건내역/], ['dates', '기일내역', /^기일내역/], ['docs', '문건/송달현황', /^문건\/?송달/],
    ['survey', '현황조사서', /^(현황)?조사서/], ['estate', '부동산표시', /^부동산표시/], ['appraisal', '감정평가서', /^감정평가서/],
    ['spec', '매각물건명세서', /^(매각)?(물건)?(명세서)|^매물명세서/], ['registry', '건물등기', /^건물등기/], ['house', '세대열람', /^세대열람/]
  ];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const bodyText = () => docs().map((d) => (d.body && d.body.innerText) || '').join('\n');  // 읽는 동안 보내기 버튼은 숨겨 두므로 버튼 글이 섞이지 않음
  const norm = (x) => x.replace(/\s+/g, ' ').trim();
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const findTab = (re) => {
    const cands = [].concat(...docs().map((d) => Array.from(d.querySelectorAll('a,button,li,span,div,td,th,label,[role=tab]')))).filter((el) => {
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
  const collectTabs = async (onProgress, fresh) => {
    const seen = fresh ? new Set() : new Set(bodyText().split('\n').map(norm).filter(Boolean));
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
  // 화면에서 눌러 볼 만한 짧은 글자(탭·버튼 이름)와 iframe 주소 - 탭을 못 찾았을 때 어디에 서류가 있는지 확인하는 용도(로그인·열쇠값은 빼고 보냄)
  const probe = () => {
    const seen = new Set(), names = [];
    docs().forEach((d) => Array.from(d.querySelectorAll('a,button,[role=tab],[onclick],li,label,summary')).forEach((el) => {
      if (el.id === ID || !visible(el)) return;
      const t = norm(el.innerText || el.value || el.title || ''); if (!t || t.length > 20 || seen.has(t)) return;
      seen.add(t); names.push(t);
    }));
    const frames = []; docs().forEach((d) => Array.from(d.querySelectorAll('iframe,frame')).forEach((f) => frames.push(String(f.src || '').replace(/(transferKey|key|token)=[^&]*/gi, '$1=…').slice(0, 160))));
    return '\n【화면요소】 ' + names.slice(0, 150).join(' | ') + '\n【프레임】 ' + frames.join(' | ') + '\n【화면】 ' + location.pathname + ' / ' + docs().length + '개 문서';
  };
  // 끝나면 화면 가운데에 완료 안내창을 띄우고, 몇 초 뒤 모으려고 열었던 팝업창(같은 사건의 상세·참고자료)을 모두 닫음
  const finish = (ok, title, lines) => {
    let box = document.getElementById('tk-done'); if (box) box.remove();
    box = document.createElement('div'); box.id = 'tk-done';
    box.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;font-family:sans-serif;';
    const card = document.createElement('div');
    card.style.cssText = 'background:#fff;color:#222;border-radius:14px;padding:22px 26px;max-width:420px;width:86%;box-shadow:0 8px 32px rgba(0,0,0,.4);text-align:center;line-height:1.6;';
    const h = document.createElement('div'); h.style.cssText = 'font-size:20px;font-weight:800;margin-bottom:8px;color:' + (ok ? '#2e7d32' : '#c62828'); h.textContent = title;
    const p = document.createElement('div'); p.style.cssText = 'font-size:14px;text-align:left;white-space:pre-line;'; p.textContent = lines.join('\n');
    const f = document.createElement('div'); f.style.cssText = 'margin-top:14px;font-size:13px;color:#555;';
    const keep = document.createElement('button'); keep.textContent = '창 닫지 않기'; keep.style.cssText = 'margin-left:8px;padding:4px 10px;border:1px solid #bbb;background:#f5f5f5;border-radius:8px;cursor:pointer;';
    const ok2 = document.createElement('button'); ok2.textContent = '확인(바로 닫기)'; ok2.style.cssText = 'margin-left:8px;padding:4px 10px;border:none;background:#7b1fa2;color:#fff;border-radius:8px;cursor:pointer;';
    card.append(h, p, f); box.appendChild(card); document.body.appendChild(box);
    const doClose = () => { try { chrome.runtime.sendMessage({ type: 'closeWindows', tid: tidOf() }); } catch (e) {} };
    if (!ok) { f.textContent = '실패해서 창은 닫지 않았어요. '; const x = document.createElement('button'); x.textContent = '닫기'; x.style.cssText = keep.style.cssText; x.onclick = () => box.remove(); f.appendChild(x); return; }
    let n = 5, timer = null;
    const tick = () => { f.firstChild && (f.firstChild.nodeValue = n + '초 뒤 열었던 팝업창을 모두 닫아요.'); if (n-- <= 0) { clearInterval(timer); doClose(); } };
    f.textContent = ''; f.appendChild(document.createTextNode('')); f.append(keep, ok2);
    keep.onclick = () => { clearInterval(timer); f.textContent = '창을 닫지 않았어요.'; setTimeout(() => box.remove(), 1500); };
    ok2.onclick = () => { clearInterval(timer); doClose(); };
    tick(); timer = setInterval(tick, 1000);
  };
  let btn = null;
  const label = isFile ? '📤 참고자료 보내기 (모든 탭)' : '📤 탱크옥션 상세 보내기 (모든 탭)';
  const toast = (t, ok) => { if (!btn) return; btn.textContent = t; btn.style.background = ok === false ? '#c62828' : (ok ? '#2e7d32' : (ok === null ? '#ef6c00' : '#7b1fa2')); };
  const msg = (m) => new Promise((r) => { try { chrome.runtime.sendMessage(m, (x) => r(chrome.runtime.lastError ? null : x)); } catch (e) { r(null); } });
  let autoRun = false;
  // 앱에 보내고(권리분석 반영 결과를 기다림) 완료 안내창을 띄움
  const deliver = (text, tabRes, kind, url) => {
    toast('보내는 중… (탭 ' + tabRes.found.length + '개 읽음' + (tabRes.missing.length ? ', 못 찾은 탭 ' + tabRes.missing.length + '개' : '') + (tabRes.empty.length ? ', 새 글 없음 ' + tabRes.empty.length + '개' : '') + ')');
    chrome.runtime.sendMessage({ type: 'send', kind, text: text.slice(0, 190000), url: String(url || location.href).replace(/(transferKey)=[^&]*/gi, '$1=…') }, (res) => {
      const sum = ['읽은 탭: ' + (tabRes.found.length ? tabRes.found.length + '개 (' + tabRes.found.join(', ') + ')' : '없음') + (tabRes.missing.length ? ' / 못 찾은 탭 ' + tabRes.missing.length + '개' : '') + (tabRes.empty.length ? ' / 새 글 없음 ' + tabRes.empty.length + '개' : '')];
      if (!res || !res.ok) { toast('❌ 보내기 실패', false); finish(false, '❌ 모으기 실패', sum.concat(['앱으로 보내지 못했어요. 잠시 뒤 다시 눌러 주세요.'])); }
      else if (res.applied) {
        const a = (res.result && res.result.applied) || [];
        if (a.length) { toast('✅ 앱에 반영됨: ' + a[0].name + ' 권리분석 (등기 ' + a[0].n + '건, ' + (a[0].tenants ? '임차인 ' + a[0].tenants + '명' : '임차인 없음') + ')', true); finish(true, '✅ 사건 정보 모으기 완료', sum.concat([a[0].name + ' 권리분석이 앱에 반영됐어요.', '앱에서 입찰후보 판정을 확인하세요.'])); }
        else if (kind === 'probe') { toast('✅ 참고자료를 보냈어요', true); finish(true, '✅ 참고자료 보내기 완료', sum.concat(['참고자료 글을 앱 수신함에 올렸어요(권리분석에는 아직 반영하지 않음).'])); }
        else { toast('⚠️ 받았지만 반영 못함: ' + ((res.result && res.result.text) || '입찰후보에 없는 사건이에요'), false); finish(false, '⚠️ 앱에 반영하지 못했어요', sum.concat([(res.result && res.result.text) || '입찰후보에 없는 사건이에요.'])); }
      } else { toast(res.noApp ? '⏳ 앱 탭이 안 열려 있어요 - 앱을 열면 자동 반영돼요' : '⏳ 앱이 아직 처리 중이에요 - 앱 화면에서 확인하세요', null); finish(true, '✅ 모으기 완료(앱 반영 대기)', sum.concat([res.noApp ? '앱 탭이 열려 있지 않아요. 앱을 열면 자동으로 반영돼요.' : '앱이 아직 처리 중이에요. 앱 화면에서 확인하세요.'])); }
      setTimeout(() => { if (btn) { btn.textContent = label; btn.style.background = '#7b1fa2'; btn.disabled = false; } }, 8000);
    });
  };
  // 상세 팝업: '파일자료' 메뉴(사건내역 등)를 누르면 참고자료 팝업이 새로 열림 → 팝업이 스스로 읽도록 표시해 두고 한 번만 누름. 팝업이 열려 읽기 시작하면 true
  const tryDelegate = async (headText) => {
    const el = findTab(TABS[0][2]); if (!el) return false;
    await msg({ type: 'arm', tid: tidOf(), text: headText, url: location.href });
    try { el.click(); } catch (e) { await msg({ type: 'disarm', tid: tidOf() }); return false; }
    for (let i = 0; i < 28; i++) { await sleep(250); const r = await msg({ type: 'armState', tid: tidOf() }); if (r && r.claimed) return true; }
    await msg({ type: 'disarm', tid: tidOf() }); return false;
  };
  // 참고자료 팝업이 열렸는데 상세 팝업이 미리 표시해 둔 것이 있으면 자동으로 탭을 읽어 보냄
  const autoCollect = async () => {
    const r = await msg({ type: 'claim', tid: tidOf() });
    if (!r || !r.armed) return;
    autoRun = true;
    for (let i = 0; i < 60 && !findTab(TABS[0][2]); i++) await sleep(500);
    const oldTitle = document.title; let tabRes = { found: [], missing: [], empty: [], text: '' };
    try { tabRes = await collectTabs((l, i, n) => { document.title = '탭 읽는 중 ' + l + ' (' + i + '/' + n + ')'; }, true); } catch (e) {}
    document.title = oldTitle;
    const text = r.text + tabRes.text + '\n【수집결과】 via=popup; found=' + tabRes.found.join(',') + '; missing=' + tabRes.missing.join(',') + '; empty=' + tabRes.empty.join(',') + probe();
    deliver(text, tabRes, /경매\s*\d{4}\s*타경/.test(text) ? 'tank' : 'probe', r.url);
  };
  if (isTop && isFile) autoCollect();
  const ensure = () => {
    const show = isDetail() && !autoRun;
    if (show && !btn) {
      if (document.getElementById(ID)) return;
      btn = document.createElement('button');
      btn.id = ID; btn.textContent = label;
      btn.style.cssText = 'position:fixed;right:16px;bottom:64px;z-index:2147483647;background:#7b1fa2;color:#fff;border:none;border-radius:20px;padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3);';
      document.body.appendChild(btn);
      btn.onclick = async () => {
        btn.disabled = true;
        const full = bodyText();
        const s = full.search(/경매\s*\d{4}\s*타경\s*\d+/);
        let text = s >= 0 ? full.slice(s) : '【참고자료 tid=' + tidOf() + '】\n' + full;
        const e = text.search(/\n파일자료\n/);   // 맨 아래 메뉴 이전까지만(필요한 부분 위주, 용량 줄이기)
        if (e > 0) text = text.slice(0, e);
        text = text.slice(0, 100000);
        let tabRes = { found: [], missing: [], empty: [] };
        const oldTitle = document.title; btn.style.display = 'none';
        if (!isFile) {
          toast('참고자료 창을 여는 중…', null); btn.style.display = '';
          if (await tryDelegate(text)) { toast('참고자료 창에서 읽는 중… (끝나면 알려 드려요)', null); setTimeout(() => { if (btn) { btn.textContent = label; btn.style.background = '#7b1fa2'; btn.disabled = false; } }, 90000); return; }
          btn.style.display = 'none';
        }
        try { tabRes = await collectTabs((l, i, n) => { document.title = '탭 읽는 중 ' + l + ' (' + i + '/' + n + ')'; }); text += tabRes.text + '\n【수집결과】 found=' + tabRes.found.join(',') + '; missing=' + tabRes.missing.join(',') + '; empty=' + tabRes.empty.join(',') + probe(); } catch (e) {}
        document.title = oldTitle; btn.style.display = '';
        deliver(text, tabRes, (isFile && !/경매\s*\d{4}\s*타경/.test(text)) ? 'probe' : 'tank');
      };
    } else if (!show && btn) { btn.remove(); btn = null; }
  };
  setInterval(ensure, 2000);
  ensure();
})();
