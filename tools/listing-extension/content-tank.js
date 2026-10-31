// 탱크옥션 상세 보내기(0.5.2: 수집 중 화면 위쪽에 진행 막대(사건·단계), 메인 화면 대기열 버튼에도 '수집 중' 실시간 표시, ▶ 자동 수집 시작 버튼, 2분 넘게 막힌 사건은 건너뛰고 다음으로 / 0.5.1: 대기열 사건이 끝나면 다음 사건을 자동으로 열기(체크박스, 8초 뒤·하루 30건 상한), 번호(tid) 학습을 링크 외 속성(onclick·data-*)까지 확대, '🔎 번호 점검' 버튼 / 0.5.0: 앱이 만든 '모으기 대기열'을 탱크옥션 화면 왼쪽 아래에 보여 주고, 한 번 누르면 그 사건 팝업을 열어 자동 수집·닫기. 사건번호↔탱크옥션 번호(tid)는 사용자가 연 화면에서 자동으로 기억 / 0.4.4: 글자 정보가 없는 그림 PDF(세대열람)는 확대해서 쪽 그림을 내려받기 폴더(tank-ocr)에 저장 - 글자 인식용 / 0.4.3: PDF로 열리는 서류(감정평가서·매물명세서·건물등기·세대열람)는 글 조각이 줄바꿈으로 흩어져 읽히므로, 쪽을 끝까지 넘겨 그린 뒤 글 조각의 위치로 줄을 다시 맞춤 / 0.4.2: 상세 팝업의 '파일자료' 메뉴는 눌러도 같은 화면이 바뀌지 않고 참고자료 팝업이 새로 열리므로, 보내기를 누르면 그 팝업을 한 번 열어 그 안의 탭(사건내역~세대열람)을 읽어 상세 글과 합쳐 보냄 / 0.4.1: 참고자료 팝업·iframe 안 글도 읽고, 못 찾은 탭이 있으면 화면 버튼 이름을 같이 보냄, 끝나면 완료 안내창 + 모으려고 열었던 팝업창 자동 닫기 / 0.4.0: 사건내역·기일내역·문건/송달·현황조사서·부동산표시·감정평가서·매각물건명세서·건물등기·세대열람 탭까지 같이 읽음) - 탱크옥션 물건 상세 페이지에 버튼 하나를 띄움. 눌렀을 때만 지금 열려 있는 페이지의 글(임차인 현황·건물등기·권리분석 등)을 앱에 보냄.
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
  // PDF 보기 화면(pdf.js)의 글 조각을 위치(세로·가로)로 묶어 한 줄씩 복원 - 표의 칸은 탭으로 구분
  const pdfLines = () => {
    const out = [];
    docs().forEach((d) => Array.from(d.querySelectorAll('.page')).forEach((pg, pi) => {
      const sp = Array.from(pg.querySelectorAll('.textLayer span')).filter((e) => !e.querySelector('span') && (e.textContent || '').trim());
      if (!sp.length) return;
      const items = sp.map((e) => { const r = e.getBoundingClientRect(); return { t: e.textContent.replace(/\s+$/, ''), x: r.left, y: r.top + r.height / 2, h: r.height || 10, w: r.width }; }).sort((a, b) => a.y - b.y || a.x - b.x);
      const rows = []; items.forEach((it) => { const last = rows[rows.length - 1]; if (last && Math.abs(it.y - last.y) < Math.max(3, last.h * 0.6)) { last.items.push(it); last.y = (last.y * (last.items.length - 1) + it.y) / last.items.length; } else rows.push({ y: it.y, h: it.h, items: [it] }); });
      out.push('[쪽 ' + (pg.getAttribute('data-page-number') || (pi + 1)) + ']');
      rows.forEach((r) => { r.items.sort((a, b) => a.x - b.x); let line = '', px = null; r.items.forEach((it) => { if (px !== null) line += (it.x - px > r.h * 1.8) ? '\t' : (it.x - px > 1 ? ' ' : ''); line += it.t; px = it.x + it.w; }); out.push(line); });
    }));
    return out.join('\n');
  };
  // 글자 정보가 없는 그림 PDF(세대열람 등): 확대해서 다시 그린 뒤 쪽마다 그림을 파일로 저장(내려받기 폴더/tank-ocr). 저장한 개수를 돌려줌
  const pdfImages = async (key, maxPages) => {
    const zoomIn = () => docs().forEach((d) => { const b = Array.from(d.querySelectorAll('button,[role=button]')).find((x) => /확대|zoom\s*in/i.test((x.title || '') + (x.getAttribute('aria-label') || '') + (x.textContent || ''))); if (b) try { b.click(); } catch (e) {} });
    zoomIn(); await sleep(400); zoomIn(); await sleep(1500);
    const imgs = [];
    const pages = [].concat(...docs().map((d) => Array.from(d.querySelectorAll('.page'))));
    for (let i = 0; i < pages.length && imgs.length < maxPages; i++) {
      try { pages[i].scrollIntoView({ block: 'start' }); } catch (e) {}
      await sleep(900);
      const c = pages[i].querySelector('canvas'); if (!c || !c.width) continue;
      try { imgs.push(c.toDataURL('image/png')); } catch (e) {}
    }
    if (!imgs.length) return 0;
    const r = await msg({ type: 'saveImages', tid: tidOf(), key, images: imgs });
    return r && r.ok ? r.saved : 0;
  };
  const hasPdf = () => docs().some((d) => d.querySelector('.pdfViewer,#viewer .page,.textLayer'));
  // 쪽을 차례로 보이게 해서 글이 그려지게 하고, 글 조각 수가 더 늘지 않을 때까지 기다림(없으면 빈 글)
  const pdfRead = async (prevSig, maxMs) => {
    const t0 = Date.now(); let last = -1, stable = 0, txt = '';
    while (Date.now() - t0 < maxMs) {
      docs().forEach((d) => Array.from(d.querySelectorAll('.page')).slice(0, 40).forEach((pg) => { try { pg.scrollIntoView({ block: 'start' }); } catch (e) {} }));
      await sleep(450);
      const n = docs().reduce((a, d) => a + d.querySelectorAll('.textLayer span').length, 0);
      txt = pdfLines();
      if (n > 0 && n === last && txt.slice(0, 300) !== prevSig) { if (++stable >= 2) break; } else stable = 0;
      last = n;
    }
    docs().forEach((d) => Array.from(d.querySelectorAll('.page')).slice(0, 1).forEach((pg) => { try { pg.scrollIntoView({ block: 'start' }); } catch (e) {} }));
    return txt && txt.slice(0, 300) !== prevSig ? txt : '';
  };
  const waitChange = async (before, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { await sleep(250); if (bodyText() !== before) { await sleep(500); return true; } } return false; };
  const collectTabs = async (onProgress, fresh) => {
    const seen = fresh ? new Set() : new Set(bodyText().split('\n').map(norm).filter(Boolean));
    let out = '', found = [], missing = [], empty = [], images = [], pdfSigPrev = hasPdf() ? pdfLines().slice(0, 300) : '';
    for (let i = 0; i < TABS.length; i++) {
      const [key, label, re] = TABS[i]; onProgress(label, i + 1, TABS.length);
      const el = findTab(re);
      if (!el) { missing.push(key); continue; }
      const before = bodyText();
      try { el.click(); } catch (e) { missing.push(key); continue; }
      await waitChange(before, 3000);
      if (hasPdf()) {  // PDF로 열리는 서류: 위치로 맞춘 줄을 씀
        const pt = await pdfRead(pdfSigPrev, 9000);
        if (pt) { pdfSigPrev = pt.slice(0, 300); pt.split('\n').forEach((x) => seen.add(norm(x))); found.push(key); out += '\n【탭:' + key + '|' + label + '】\n' + pt.slice(0, 40000); continue; }
        if (key === 'house') { const n = await pdfImages(key, 8); if (n) { images.push(key + ':' + n); out += '\n【탭:' + key + '|' + label + '】\n【그림 PDF - 글자 정보 없음. 쪽 그림 ' + n + '장을 내려받기 폴더(tank-ocr)에 저장】'; found.push(key); continue; } }
      }
      const lines = bodyText().split('\n').map((x) => x.replace(/\s+$/, '')).filter((x) => { const n = norm(x); if (!n || seen.has(n)) return false; seen.add(n); return true; });
      if (!lines.length) { empty.push(key); continue; }
      found.push(key);
      out += '\n【탭:' + key + '|' + label + '】\n' + lines.join('\n').slice(0, 30000);
    }
    return { text: out, found, missing, empty, images };
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
    let n = 4, timer = null; setProg('✅ 완료 - 곧 창을 닫고 다음 사건으로 넘어가요');
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
  let autoRun = false, autoMode = false;
  // 진행 막대(수집 중인 팝업 맨 위) + 메인 화면 대기열 버튼에 단계 전달
  const setProg = (step) => {
    try {
      if (!isTop || !document.body) return;
      let b = document.getElementById('tk-prog');
      if (!b) { const st = document.createElement('style'); st.textContent = '@keyframes tkpulse{0%{opacity:1}50%{opacity:.45}100%{opacity:1}}'; document.head && document.head.appendChild(st); b = document.createElement('div'); b.id = 'tk-prog'; b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#0369a1;color:#fff;font:700 14px sans-serif;padding:8px 14px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.35);animation:tkpulse 1.4s infinite;'; document.body.appendChild(b); }
      b.textContent = '🧲 경매정보 수집 중' + (tidOf() ? ' · 번호 ' + tidOf() : '') + ' · ' + step; if (/완료|실패/.test(step)) b.style.animation = 'none';
      msg({ type: 'prog', step, tid: tidOf() });
    } catch (e) {}
  };
  // 앱에 보내고(권리분석 반영 결과를 기다림) 완료 안내창을 띄움
  const deliver = (text, tabRes, kind, url) => {
    setProg('앱으로 보내는 중');
    toast('보내는 중… (탭 ' + tabRes.found.length + '개 읽음' + (tabRes.missing.length ? ', 못 찾은 탭 ' + tabRes.missing.length + '개' : '') + (tabRes.empty.length ? ', 새 글 없음 ' + tabRes.empty.length + '개' : '') + ')');
    chrome.runtime.sendMessage({ type: 'send', kind, text: text.slice(0, 190000), url: String(url || location.href).replace(/(transferKey)=[^&]*/gi, '$1=…') }, (res) => {
      const sum = ['읽은 탭: ' + (tabRes.found.length ? tabRes.found.length + '개 (' + tabRes.found.join(', ') + ')' : '없음') + (tabRes.missing.length ? ' / 못 찾은 탭 ' + tabRes.missing.length + '개' : '') + (tabRes.empty.length ? ' / 새 글 없음 ' + tabRes.empty.length + '개' : '')];
      if (!res || !res.ok) { toast('❌ 보내기 실패', false); finish(false, '❌ 모으기 실패', sum.concat(['앱으로 보내지 못했어요. 잠시 뒤 다시 눌러 주세요.'])); }
      else if (res.applied) {
        const a = (res.result && res.result.applied) || [];
        if (a.length) { msg({ type: 'queueDone', caseNo: a[0].caseNo || '', tid: tidOf() }); toast('✅ 앱에 반영됨: ' + a[0].name + ' 권리분석 (등기 ' + a[0].n + '건, ' + (a[0].tenants ? '임차인 ' + a[0].tenants + '명' : '임차인 없음') + ')', true); finish(true, '✅ 사건 정보 모으기 완료', sum.concat([a[0].name + ' 권리분석이 앱에 반영됐어요.', '앱에서 입찰후보 판정을 확인하세요.'])); }
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
    setProg('참고자료 탭 읽는 중'); try { tabRes = await collectTabs((l, i, n) => { document.title = '탭 읽는 중 ' + l + ' (' + i + '/' + n + ')'; setProg('참고자료 탭 읽는 중 ' + l + ' (' + i + '/' + n + ')'); }, true); } catch (e) {}
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
      if (!isFile) msg({ type: 'autoStart', tid: tidOf() }).then((r) => { if (r && r.auto) { autoMode = true; setProg('상세 글 읽는 중'); setTimeout(() => { try { btn.click(); } catch (e) {} }, 2500); setTimeout(() => { if (!document.getElementById('tk-done')) { setProg('실패 - 2분 넘게 끝나지 않아 건너뛰어요'); msg({ type: 'chainFail', tid: tidOf() }); } }, 150000); } });  // 대기열에서 열린 팝업이면 자동으로 모으기 시작
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
          toast('참고자료 창을 여는 중…', null); setProg('참고자료 창 여는 중'); btn.style.display = '';
          if (await tryDelegate(text)) { toast('참고자료 창에서 읽는 중… (끝나면 알려 드려요)', null); setTimeout(() => { if (btn) { btn.textContent = label; btn.style.background = '#7b1fa2'; btn.disabled = false; } }, 90000); return; }
          btn.style.display = 'none';
        }
        try { tabRes = await collectTabs((l, i, n) => { document.title = '탭 읽는 중 ' + l + ' (' + i + '/' + n + ')'; setProg('탭 읽는 중 ' + l + ' (' + i + '/' + n + ')'); }); text += tabRes.text + '\n【수집결과】 found=' + tabRes.found.join(',') + '; missing=' + tabRes.missing.join(',') + '; empty=' + tabRes.empty.join(',') + probe(); } catch (e) {}
        document.title = oldTitle; btn.style.display = '';
        deliver(text, tabRes, (isFile && !/경매\s*\d{4}\s*타경/.test(text)) ? 'probe' : 'tank');
      };
    } else if (!show && btn) { btn.remove(); btn = null; }
  };
  // ---- 모으기 대기열 패널(일반 탱크옥션 화면 왼쪽 아래) ----
  const normCase = (x) => String(x || '').replace(/타경/g, '-').replace(/\s+/g, '');
  const learnTids = () => {
    const map = {};
    const txt = (document.body && document.body.innerText) || '';
    const cm = txt.match(/경매\s*(\d{4})\s*타경\s*(\d+)\s*(\(\d+\))?/);
    if (cm && tidOf()) map[normCase(cm[1] + '타경' + cm[2] + (cm[3] || ''))] = tidOf();  // 상세 화면: 이 사건의 tid
    const tidOfEl = (a) => { const dt = a.getAttribute('data-tid'); if (dt && /^\d{6,8}$/.test(dt)) return dt; const at = (a.getAttribute('href') || '') + ' ' + (a.getAttribute('onclick') || '') + ' ' + Array.from(a.attributes || []).filter((x) => /^data-/.test(x.name)).map((x) => x.value).join(' '); const m = at.match(/[?&]tid=(\d+)/) || at.match(/tid['":=\s]+(\d{6,8})/) || at.match(/\((?:[^)]*?[,\s'"])?(2\d{6})(?:[,'"\s)][^)]*)?\)/); return m ? m[1] : ''; };
    Array.from(document.querySelectorAll('a[href],[onclick],[data-tid],[data-id]')).slice(0, 800).forEach((a) => {  // 목록 화면: 한 줄에 사건번호가 하나뿐인 링크만
      const tv = tidOfEl(a); if (!tv) return; const m = [0, tv];
      let el = a;
      for (let k = 0; k < 7 && el; k++) { if (k > 0) el = el.parentElement; if (!el) break; const ms = ((el.innerText || '').slice(0, 600).match(/\d{4}\s*타경\s*\d+(?:\(\d+\))?/g) || []).map(normCase); const u = ms.filter((v, i) => ms.indexOf(v) === i); if (u.length === 1) { map[u[0]] = m[1]; break; } if (u.length > 1) break; }
    });
    if (Object.keys(map).length) msg({ type: 'learnTids', map });
  };
  let qBox = null, qOpen = false;
  const renderQueue = async () => {
    if (!isTop || /\/popup\//.test(location.pathname)) return;
    const r = await msg({ type: 'queueGet' }), q = r && r.q;
    if (!q || !(q.items || []).length) { if (qBox) { qBox.remove(); qBox = null; } return; }
    const done = new Set((q.done || []).map(normCase)), tids = Object.assign({}, q.tids || {}, r.tids || {});
    const left = q.items.filter((i) => !done.has(normCase(i.caseNo)));
    if (!qBox) { qBox = document.createElement('div'); qBox.id = 'tk-queue'; qBox.style.cssText = 'position:fixed;left:16px;bottom:64px;z-index:2147483646;font-family:sans-serif;font-size:13px;'; document.body.appendChild(qBox); }
    qBox.textContent = '';
    const stt = r && r.status && Date.now() - (r.status.at || 0) < 90000 ? r.status : null;
    const head = document.createElement('button'); head.textContent = stt ? '⏳ 수집 중 · ' + (stt.caseNo || ('번호 ' + stt.tid)) + ' · ' + stt.step + ' (' + left.length + '건 남음)' : '🧲 모으기 대기열 ' + left.length + '건 남음 ' + (qOpen ? '▾' : '▸'); head.style.cssText = (stt ? 'animation:tkpulse 1.4s infinite;' : '') + 'background:' + (stt ? '#b45309' : '#0369a1') + ';color:#fff;border:none;border-radius:20px;padding:9px 14px;font-weight:700;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3);'; head.onclick = () => { qOpen = !qOpen; renderQueue(); }; qBox.appendChild(head);
    if (!qOpen) return;
    const opts = document.createElement('div'); opts.style.cssText = 'margin-top:6px;background:#fff;border:1px solid #cbd5e1;border-radius:10px;padding:6px 10px;color:#111;max-width:380px;';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = !!(r && r.chainOn); cb.onchange = () => msg({ type: 'chainSet', on: cb.checked });
    const lb = document.createElement('label'); lb.style.cssText = 'cursor:pointer;'; lb.appendChild(cb); lb.appendChild(document.createTextNode(' 끝나면 다음 사건 자동 열기(8초 뒤, 번호를 아는 사건만, 하루 30건)')); opts.appendChild(lb);
    const dg = document.createElement('button'); dg.textContent = '🔎 이 화면에서 번호 점검'; dg.style.cssText = 'display:block;margin-top:5px;padding:3px 9px;border:1px solid #94a3b8;border-radius:8px;background:#f1f5f9;cursor:pointer;';
    dg.onclick = async () => { const aEl = Array.from(document.querySelectorAll('a[href],[onclick],[data-tid],[data-id]')); const withTid = aEl.filter((x) => /tid|\b2\d{6}\b/.test((x.getAttribute('href') || '') + (x.getAttribute('onclick') || '') + (x.getAttribute('data-tid') || ''))); const ex = withTid.slice(0, 6).map((x) => '<' + x.tagName.toLowerCase() + ' href=' + (x.getAttribute('href') || '').slice(0, 90) + ' onclick=' + (x.getAttribute('onclick') || '').slice(0, 90) + '> ' + norm((x.parentElement && x.parentElement.innerText || x.innerText || '')).slice(0, 80)); learnTids(); const rr = await msg({ type: 'queueGet' }); dg.textContent = '점검: 번호 후보 요소 ' + withTid.length + '개 · 기억한 사건 ' + Object.keys((rr && rr.tids) || {}).length + '건 (자세한 내용은 앱으로 보냈어요)'; msg({ type: 'send', kind: 'probe', text: '【번호점검】 url=' + location.pathname + ' 후보=' + withTid.length + '\n' + ex.join('\n'), url: location.pathname }); };
    const known = left.filter((i) => tids[normCase(i.caseNo)]).length, go = document.createElement('button'); go.textContent = '▶ 대기열 자동 수집 시작 (번호 아는 ' + known + '건' + (left.length - known ? ', 모르는 ' + (left.length - known) + '건은 건너뜀' : '') + ')'; go.style.cssText = 'display:block;margin-top:5px;padding:5px 10px;border:none;border-radius:8px;background:#16a34a;color:#fff;font-weight:700;cursor:pointer;'; go.disabled = !known || !!stt; go.onclick = () => { go.disabled = true; go.textContent = '여는 중…'; msg({ type: 'chainStart' }); setTimeout(() => renderQueue(), 3000); };
    opts.insertBefore(go, opts.firstChild); opts.appendChild(dg); qBox.appendChild(opts);
    const list = document.createElement('div'); list.style.cssText = 'margin-top:6px;background:#fff;border:1px solid #cbd5e1;border-radius:10px;padding:8px 10px;max-width:380px;max-height:60vh;overflow:auto;box-shadow:0 4px 14px rgba(0,0,0,.25);color:#111;';
    if (!left.length) list.textContent = '✅ 대기열을 모두 모았어요.';
    left.slice(0, 12).forEach((it) => {
      const row = document.createElement('div'); row.style.cssText = 'padding:5px 0;border-bottom:1px solid #eef2f7;';
      const t = document.createElement('div'); t.textContent = it.caseNo + ' · ' + (it.name || '') + (it.sale ? ' · 매각 ' + it.sale : ''); t.style.cssText = 'font-weight:600;word-break:keep-all;'; row.appendChild(t);
      const tid = tids[normCase(it.caseNo)], b = document.createElement('button'); b.style.cssText = 'margin-top:3px;margin-right:6px;padding:3px 9px;border:none;border-radius:8px;cursor:pointer;color:#fff;background:' + (tid ? '#16a34a' : '#64748b') + ';';
      if (tid) { b.textContent = '▶ 열어서 자동 수집'; b.onclick = () => { b.disabled = true; b.textContent = '여는 중…'; msg({ type: 'openCase', tid }); setTimeout(() => renderQueue(), 4000); }; }
      else { b.textContent = '📋 사건번호 복사'; b.onclick = async () => { try { await navigator.clipboard.writeText(it.caseNo.replace('-', '타경')); b.textContent = '복사됨 - 탱크옥션 검색에 붙여넣기'; } catch (e) { b.textContent = it.caseNo; } }; const hint = document.createElement('span'); hint.textContent = '(처음 보는 사건: 한 번 열면 다음부턴 자동)'; hint.style.cssText = 'font-size:11px;color:#64748b;'; row.appendChild(b); row.appendChild(hint); list.appendChild(row); return; }
      row.appendChild(b); list.appendChild(row);
    });
    qBox.appendChild(list);
  };
  setInterval(ensure, 2000);
  ensure();
  if (isTop) { learnTids(); renderQueue(); setInterval(learnTids, 5000); setInterval(renderQueue, 4000); }
})();
