// 호가 자동 진행(0.8.0) - 화면과 상관없는 순수 계산(단지 고르기·다음 순서·멈춤 조건·간격). 확장(content-chain.js)과 노드 시험(tests/chain-logic.test.js)이 같이 씀.
(function (root) {
  const normName = (n) => String(n || '').replace(/\([^)]*\)|（[^）]*）/g, '').replace(/아파트\s*$/, '').replace(/[\s·.\-_,]/g, '').toLowerCase();
  const itemKey = (it) => normName(it && it.name) + '|' + String((it && it.dong) || '').replace(/\s/g, '');

  // 네이버 검색 결과의 단지 링크 중 이 단지(이름·동)와 맞는 것 하나. 이름이 정확히 같은 것 → 서로 포함(3글자 이상) 순. 동이 맞는 것을 우선. 못 찾으면 null(엉뚱한 단지를 열지 않음)
  function pickComplexLink(links, item) {
    const t = normName(item && item.name), dong = String((item && item.dong) || '').replace(/\s/g, '');
    if (!t || t.length < 2) return null;
    const cands = [];
    for (const l of links || []) {
      if (!l || !/\/complexes\/\d+/.test(l.href || '')) continue;
      const ln = normName(l.text);
      if (!ln) continue;
      let score = 0;
      if (ln === t) score = 3;
      else if (ln.length >= 3 && t.length >= 3 && (ln.indexOf(t) >= 0 || t.indexOf(ln) >= 0)) score = 2;
      if (!score) continue;
      if (dong && String(l.ctx || '').replace(/\s/g, '').indexOf(dong) >= 0) score += 1;
      cands.push({ href: l.href, score });
    }
    if (!cands.length) return null;
    cands.sort((a, b) => b.score - a.score);
    return cands[0].href;
  }

  // 대기열(items) 중 아직 처리 안 한 첫 항목
  function nextItem(q, handled) {
    const h = handled || {};
    for (const it of (q && q.items) || []) {
      const k = it.key || itemKey(it);
      if (!h[k]) return Object.assign({ key: k }, it);
    }
    return null;
  }

  // 로그인·캡차·접속 제한 화면이면 멈출 이유를 돌려줌(없으면 null)
  function blockedReason(url, text) {
    const u = String(url || ''), t = String(text || '').slice(0, 6000);
    if (/nid\.naver\.com|login|captcha/i.test(u)) return '로그인·확인 화면이 떴어요';
    if (/자동\s*입력\s*방지|로봇이\s*아닙니다|보안\s*문자|캡차|captcha/i.test(t)) return '캡차(자동입력 방지) 화면이 떴어요';
    if (/과도한\s*접속|비정상적인\s*접근|접근이\s*제한|잠시\s*후\s*다시\s*시도|이용이\s*제한/.test(t)) return '네이버가 접속 제한 안내를 띄웠어요';
    return null;
  }

  // 다음 단지까지 쉬는 시간(ms): min~max 사이 무작위
  const jitter = (min, max, rnd) => Math.round(min + (max - min) * (typeof rnd === 'number' ? rnd : Math.random()));
  const dayKey = (d) => { const x = d || new Date(); return x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0') + '-' + String(x.getDate()).padStart(2, '0'); };

  // 오늘 처리 건수·연속 실패로 계속할지 판단
  function shouldStop(st, limit, failLimit) {
    if ((st.count || 0) >= limit) return '오늘 ' + limit + '곳을 다 했어요 ✅';
    if ((st.fails || 0) >= failLimit) return failLimit + '번 연속으로 못 읽어서 멈췄어요(네이버 화면이 바뀌었을 수 있어요)';
    return null;
  }

  // 지도 위 단지 표시 후보(화면 요소) 중 목표 단지 이름과 맞는 것을 고름: 이름이 정확히 같은 것 우선, 그다음 화면 가운데(주소 검색으로 지도가 옮겨 간 자리)에 가까운 것. cands: [{ n: 정규화한 글자, x, y }]
  function rankCandidates(cands, target, cx, cy) {
    const T = normName(target); if (!T) return [];
    return (cands || []).filter((c) => c && c.n && (c.n === T || sameComplex(c.t || c.n, target)))
      .map((c) => Object.assign({}, c, { exact: c.n === T ? 0 : 1, d: Math.hypot((c.x || 0) - cx, (c.y || 0) - cy) }))
      .sort((a, b) => (a.exact - b.exact) || (a.d - b.d));
  }
  // 화면에 나온 단지 이름(매물 머리줄 '집주인보라맨션 비동'·자동완성 첫 줄 등)이 목표 단지와 같은 단지인지. 이름 앞뒤에 '9단지'·'2차' 같은 구분이 더 붙으면 다른 단지(동 이름 '비동'·'910동'은 무시)
  const sp = (x) => String(x || '').replace(/[\s·.\-_,()]/g, '').toLowerCase();
  const coreName = (n) => sp(String(n || '').replace(/\([^)]*\)|（[^）]*）/g, '').replace(/아파트\s*$/, ''));
  // 단지 이름 비교용 정본: '○차·○단지' 번호 + 한글 글자(정렬) - 같은 단지를 '장암2단지주공'(국토부)·'장암주공2단지'(네이버)처럼 순서만 다르게 적는 경우를 같게 봄(앱 호가 반영의 canonName과 같은 방식)
  const canon = (n) => { const s0 = String(n || '').replace(/\([^)]*\)|（[^）]*）/g, '').replace(/집주인/g, '').replace(/아파트/g, ''); const ch = (s0.match(/\d+\s*(?:차|단지)/g) || []).map((x) => x.replace(/\s/g, '')).sort().join(','); const hg = (s0.replace(/\d+\s*(?:차|단지)/g, '').match(/[가-힣]/g) || []).sort().join(''); return ch + '|' + hg; };
  function sameComplex(label, target) {
    const lbl = String(label || '').replace(/\s*[0-9A-Za-z가-힣]{0,4}동\s*$/, '');
    const c1 = canon(lbl), c2 = canon(target); if (c1 === c2 && c2.split('|')[1].length >= 3) return true;
    const T = coreName(target); let Lb = sp(String(label || '').replace(/집주인/g, '')).replace(/아파트/g, '');
    if (!T || !Lb) return false;
    const i = Lb.indexOf(T); if (i < 0) return false;
    let rest = Lb.slice(0, i) + Lb.slice(i + T.length);
    rest = rest.replace(/[가-힣a-z0-9]{0,4}동$/, '');
    return rest.length <= 1;
  }
  // 보내기 전 확인: 읽은 매물 글(머리줄 = '매매…' 줄 바로 위)의 단지 이름이 목표 단지와 같은지. true/false, 머리줄이 없으면 null(판단 불가)
  const ITEMLINE = /^매매\s*\d[\d,]*(?:억|만)?(?:\s*[\d,]+)?(?:\s*~\s*[\d,억만\s]+)?$/;
  function headersMatch(text, target) {
    const lines = String(text || '').split(/\r?\n/).map((x) => x.trim()).filter(Boolean), hs = [];
    for (let i = 1; i < lines.length; i++) if (ITEMLINE.test(lines[i]) && !/^(매매|전세|월세)/.test(lines[i - 1]) && lines[i - 1].length < 60) hs.push(lines[i - 1]);
    if (!hs.length) return null;
    const ok = hs.filter((h) => sameComplex(h, target)).length;
    return ok >= Math.ceil(hs.length / 2);
  }
  // 검색창 자동완성 후보 중 목표 단지를 고름. cands: [{ first: 첫 줄(단지 이름), full: 전체 글자 }] → 인덱스(없으면 -1). 같은 이름이 여럿이면 지번 주소의 동·읍·면·리가 들어 있는 것 우선
  function pickSuggestion(cands, item) {
    const toks = String((item && (item.addr || '')) || '').split(/\s+/).filter((t) => /(동|읍|면|리|가)$/.test(t) && t.length >= 2);
    if (item && item.dong) toks.push(String(item.dong));
    let best = -1, bs = -1;
    (cands || []).forEach((c, i) => {
      if (!sameComplex(c.first, item && item.name)) return;
      const f = sp(c.full); let sc = 1; toks.forEach((t) => { if (f.indexOf(sp(t)) >= 0) sc += 2; });
      if (sc > bs) { bs = sc; best = i; }
    });
    return best;
  }
  const api = { sameComplex, headersMatch, pickSuggestion, coreName, rankCandidates, normName, itemKey, pickComplexLink, nextItem, blockedReason, jitter, dayKey, shouldStop };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.HGChain = api;
})(typeof self !== 'undefined' ? self : this);
