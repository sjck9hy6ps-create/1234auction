// 빌라 호가 보내기(0.7) - 네이버 부동산 '지도 목록'(연립/다세대 등, 단지 페이지가 아님)에서 버튼을 눌렀을 때만, 지금 지도 화면 안의 매매 호가 목록을 읽어 보냄.
// 지도 중심 좌표는 주소창의 ms=위도,경도,확대 에서 읽음. 자동 이동·자동 순회 없음, 로그인 정보는 다루지 않음.
(function () {
  if (!/^\/(houses|offices|complexes|articles)?/.test(location.pathname)) return;
  if (/^\/complexes\/\d+/.test(location.pathname)) return;   // 단지 페이지는 content.js가 처리
  if (document.getElementById('hg-villa-btn')) return;
  const btn = document.createElement('button');
  btn.id = 'hg-villa-btn'; btn.textContent = '🏘 빌라 호가 보내기';
  btn.style.cssText = 'position:fixed;right:16px;bottom:64px;z-index:2147483647;background:#6a1b9a;color:#fff;border:none;border-radius:20px;padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.3);';
  document.body.appendChild(btn);
  try { const e0 = new URL(location.href).searchParams.get('ms') || ''; if (e0 && !/^\d{2}\./.test(e0)) chrome.runtime.sendMessage({ type: 'bindEnc', enc: e0 }); } catch (e) {}   // 앱이 방금 연 탭이면 처음(암호화된) 주소를 앱이 알려 준 좌표와 짝지음
  const toast = (t, ok) => { btn.textContent = t; btn.style.background = ok === false ? '#c62828' : (ok ? '#2e7d32' : '#6a1b9a'); };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const isPrice = (l) => /^매매\s*[\d억]/.test(l);
  const findScroller = () => {
    let best = null, bestLen = Infinity;
    document.querySelectorAll('div,ul,section,main,aside').forEach((el) => {
      if (el.scrollHeight <= el.clientHeight + 80 || el.clientHeight < 150) return;
      if (!/(^|\n)매매\s*[\d억]/.test(el.innerText || '')) return;
      const len = (el.innerText || '').length; if (len < bestLen) { best = el; bestLen = len; }
    });
    return best;
  };
  // 가격 줄을 기준으로 앞 2줄(이름)·뒤 5줄(종류·면적·층·설명)을 한 묶음으로 저장. 해석은 서버쪽 python이 함
  const items = new Map();
  const harvest = (root) => {
    const lines = ((root || document.body).innerText || '').split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
    lines.forEach((l, i) => { if (isPrice(l)) { const blk = lines.slice(Math.max(0, i - 2), i + 6).join('\n'); items.set(lines.slice(i, i + 4).join('|'), blk); } });
  };
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      // 좌표 찾기: ① 주소에 숫자 좌표가 있으면 그대로 ② 네이버가 암호 같은 글자로 바꿨으면(ms=2AIWpC,3zk8iO), 바뀌기 전에 기억해 둔 좌표(content-villa-early.js).
      //   단, 기억해 둔 것은 '처음 열었을 때' 화면이라 지도를 움직였으면(주소가 또 바뀜) 쓸 수 없음 → 앱 링크로 다시 열도록 안내
      const href = decodeURIComponent(location.href); let m = null, mm, enc = '';
      if ((mm = href.match(/[?&#]ms=(\d{2}\.\d+)[,:](\d{3}\.\d+)(?:[,:](\d+))?/))) m = [+mm[1], +mm[2], +(mm[3] || 0)];
      else {
        enc = new URL(location.href).searchParams.get('ms') || '';
        // 네이버의 암호 좌표 풀이(2026-11-14 실측 2쌍으로 확인): 62진법(0-9a-zA-Z) 숫자 ÷ 1e7 − 200 = 위도·경도 (예 2AIWpC,3zk8iO → 37.49247,127.03687)
        const B62 = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ', d62 = (t) => { let v = 0; for (const ch of t) { const k = B62.indexOf(ch); if (k < 0) return NaN; v = v * 62 + k; } return v / 1e7 - 200; };
        const pr = enc.split(',');
        if (pr.length >= 2 && /^[0-9a-zA-Z]{5,7}$/.test(pr[0]) && /^[0-9a-zA-Z]{5,7}$/.test(pr[1])) { const la = d62(pr[0]), lo = d62(pr[1]); if (la > 33 && la < 39 && lo > 124 && lo < 132) m = [la, lo, +(pr[2] || 0)]; }
        let st = null; if (!m) try { st = JSON.parse(sessionStorage.getItem('hg_ms0') || 'null'); } catch (e) {}
        if (!m && st && st.lat) {
          if (!st.enc) { st.enc = enc; try { sessionStorage.setItem('hg_ms0', JSON.stringify(st)); } catch (e) {} }
          if (st.enc === enc) m = [st.lat, st.lon, st.z];
          else { toast('지도를 움직였어요 - 앱의 네이버 링크로 다시 열어 처음 화면에서 눌러 주세요', false); return; }
        }
      }
      if (!m) {   // 앱이 링크를 열 때 알려 준 좌표(처음 주소와 같을 때만)
        const r = await new Promise((res) => { try { chrome.runtime.sendMessage({ type: 'getOpen', enc }, (x) => res(chrome.runtime.lastError ? null : x)); } catch (e) { res(null); } });
        if (r && r.ok) m = [r.lat, r.lon, r.z || 0];
        else if (enc) { const lo = await new Promise((res) => { try { chrome.storage.local.get('lastOpen', (x) => res(x && x.lastOpen)); } catch (e) { res(null); } }); if (lo && lo.enc && lo.enc !== enc) { toast('지도를 움직였어요 - 앱의 네이버 링크로 다시 열어 처음 화면에서 눌러 주세요', false); return; } }
      }
      if (!m) { toast('좌표를 못 찾았어요 - 앱의 네이버부동산 링크로 열어 주세요(주소: ' + location.pathname + location.search.slice(0, 40) + ')', false); return; }
      toast('호가 읽는 중…');
      let sc = findScroller(); harvest(sc);
      let same = 0, last = items.size;
      for (let i = 0; i < 60 && same < 3; i++) {
        if (sc) sc.scrollTop += Math.max(300, sc.clientHeight * 0.9); else window.scrollBy(0, Math.max(300, window.innerHeight * 0.9));
        await sleep(700);
        if (!sc) sc = findScroller();
        harvest(sc); same = items.size === last ? same + 1 : 0; last = items.size;
      }
      if (!items.size) { toast('매매 호가를 못 찾았어요(목록이 보이는지 확인)', false); return; }
      toast('보내는 중… (' + items.size + '건)');
      chrome.runtime.sendMessage({ type: 'sendVillaAsks', lat: m[0], lon: m[1], zoom: m[2] || null, enc: enc, url: location.href, items: [...items.values()] }, (res) => {
        if (!res || !res.ok) toast('❌ 보내기 실패' + (res && res.error ? ': ' + res.error : ''), false);
        else toast('✅ 저장됨: 호가 ' + res.n + '건', true);
        setTimeout(() => { btn.textContent = '🏘 빌라 호가 보내기'; btn.style.background = '#6a1b9a'; btn.disabled = false; }, 8000);
      });
      return;
    } catch (e) { toast('오류: ' + e.message, false); }
    setTimeout(() => { btn.textContent = '🏘 빌라 호가 보내기'; btn.style.background = '#6a1b9a'; btn.disabled = false; }, 4000);
  };
})();
