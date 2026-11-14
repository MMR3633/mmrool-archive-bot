/* Угу: мини-апп. Чистый JS, без сборки. */
(() => {
'use strict';

/* ---------- окружение ---------- */
const TG = window.Telegram && window.Telegram.WebApp;
const params = new URLSearchParams(location.search);
const IN_TG = !!(TG && TG.initData);
const DEMO = params.get('demo') === '1' || !IN_TG;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pad = n => String(n).padStart(2, '0');
const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const pd = s => new Date(s.length === 10 ? s + 'T00:00' : s);
const wait = ms => new Promise(r => setTimeout(r, ms));
const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const WDL = ['воскресенье', 'понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу'];
const MON = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const MONN = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
const wdi = d => (d.getDay() + 6) % 7;
const plural = (n, a, b, c) => { const m = Math.abs(n) % 100, k = m % 10; return (m > 10 && m < 20) ? c : k === 1 ? a : (k > 1 && k < 5) ? b : c; };
const hm = d => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const dayDiff = d => Math.round((new Date(ymd(d) + 'T00:00') - new Date(ymd(new Date()) + 'T00:00')) / 864e5);
const dayWord = d => { const k = dayDiff(d); return k === 0 ? 'сегодня' : k === 1 ? 'завтра' : k === 2 ? 'послезавтра' : k === -1 ? 'вчера' : `${WD[wdi(d)].toLowerCase()}, ${d.getDate()} ${MON[d.getMonth()]}`; };
const whenLabel = s => { const d = pd(s); return `${dayWord(d)}, ${hm(d)}`; };
const relLabel = s => {
  const d = pd(s), mins = Math.round((d - Date.now()) / 60000);
  if (mins < 0) return 'просрочено';
  if (mins < 60) return `через ${Math.max(mins, 1)} мин`;
  if (dayDiff(d) === 0) return hm(d);
  return `${dayWord(d).split(',')[0]} ${hm(d)}`;
};
const chatTime = s => { const d = pd(s), k = dayDiff(d); return k === 0 ? hm(d) : k === -1 ? 'вчера' : WD[wdi(d)]; };
const dayChip = s => { const d = pd(s), k = dayDiff(d); return k === 0 ? 'Сегодня' : k === -1 ? 'Вчера' : `${d.getDate()} ${MON[d.getMonth()].slice(0, 3)}`; };
const PAL = ['#7C5CFF', '#FF8FB1', '#3D8BFF', '#34C759', '#FF9F0A', '#B66BFF', '#FF6B6B'];
const colorOf = s => { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return PAL[h % PAL.length]; };
const initial = s => (String(s || '?').trim()[0] || '?').toUpperCase();
const hl = (text, q) => {
  if (!q) return esc(text);
  const re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig');
  return String(text).split(re).map((p, i) => i % 2 ? `<mark>${esc(p)}</mark>` : esc(p)).join('');
};
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

const IC = {
  back: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
  send: '<svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
};
const TABS = [
  { id: 'today', title: 'Сегодня', svg: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>' },
  { id: 'chats', title: 'Чаты', svg: '<path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-5.4A8 8 0 1 1 21 12z"/>' },
  { id: 'plans', title: 'Планы', svg: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/>' },
  { id: 'notes', title: 'Заметки', svg: '<path d="M5 3h14a2 2 0 0 1 2 2v9l-6 7H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M15 21v-5a1 1 0 0 1 1-1h5"/>' },
  { id: 'ugu', title: 'Угу', svg: '<path d="M5 20V11a7 7 0 0 1 14 0v9l-2.3-1.8L14.3 20 12 18.2 9.7 20 7.3 18.2z"/><circle cx="9.5" cy="11" r=".7"/><circle cx="14.5" cy="11" r=".7"/>' },
];
const TAB_SUB = { chats: 'Архив переписок', plans: 'Дела и напоминания', notes: 'Всё важное под рукой', ugu: 'Спроси, найду, подскажу' };

/* ---------- Telegram ---------- */
const hap = (t = 'light') => {
  try {
    const h = TG && TG.HapticFeedback; if (!h) return;
    if (t === 'success' || t === 'error' || t === 'warning') h.notificationOccurred(t);
    else if (t === 'select') h.selectionChanged();
    else h.impactOccurred(t);
  } catch (e) { /* нет вибрации */ }
};
const openLink = u => { try { if (TG && TG.openLink) return TG.openLink(u); } catch (e) { /* ignore */ } window.open(u, '_blank', 'noopener'); };

function applyTheme() {
  const pref = localStorage.ugu_theme || 'system';
  const sys = IN_TG ? TG.colorScheme : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const scheme = params.get('theme') || (pref === 'system' ? sys : pref);
  const root = document.documentElement;
  root.dataset.theme = scheme;
  root.style.removeProperty('--bg'); root.style.removeProperty('--text');
  const tp = IN_TG ? TG.themeParams : null;
  if (tp && pref === 'system' && tp.bg_color && tp.text_color) { root.style.setProperty('--bg', tp.bg_color); root.style.setProperty('--text', tp.text_color); }
  const bg = getComputedStyle(root).getPropertyValue('--bg').trim() || '#0F0A24';
  try { if (TG) { TG.setHeaderColor(bg); TG.setBackgroundColor(bg); if (TG.setBottomBarColor) TG.setBottomBarColor(bg); } } catch (e) { /* ignore */ }
}

const stack = [];
function syncBack() {
  document.body.classList.toggle('lock', stack.length > 0);
  try { if (TG && TG.BackButton) { stack.length ? TG.BackButton.show() : TG.BackButton.hide(); } } catch (e) { /* ignore */ }
}
function back() { const t = stack[stack.length - 1]; if (t) t.close(); }
let mainFn = null;
function setMain(text, fn, disabled) {
  if (!IN_TG || !TG.MainButton) return false;
  document.body.classList.add('has-mb');
  const mb = TG.MainButton;
  if (mainFn) mb.offClick(mainFn);
  mainFn = fn; mb.setText(text); mb.onClick(fn);
  disabled ? mb.disable() : mb.enable(); mb.show();
  return true;
}
function hideMain() {
  document.body.classList.remove('has-mb');
  if (IN_TG && TG.MainButton) { if (mainFn) TG.MainButton.offClick(mainFn); mainFn = null; TG.MainButton.hide(); }
}

/* ---------- маскот ---------- */
const anims = [];
function mascot(el, name = 'ghost', loop = true) {
  if (!el) return null;
  const data = window.GHOSTS && window.GHOSTS[name];
  if (!window.lottie || !data) { el.innerHTML = '<img src="assets/ugu_ghost_avatar.jpg" alt="">'; return null; }
  el.innerHTML = '';
  const a = window.lottie.loadAnimation({ container: el, renderer: 'svg', loop, autoplay: !reduced, animationData: structuredClone(data) });
  if (reduced) a.addEventListener('DOMLoaded', () => a.goToAndStop(Math.floor(a.totalFrames / 3), true));
  anims.push(a);
  for (let i = anims.length - 1; i >= 0; i--) if (!anims[i].wrapper || !anims[i].wrapper.isConnected) { try { anims[i].destroy(); } catch (e) { /* ignore */ } anims.splice(i, 1); }
  return a;
}
const H = { name: '', until: 0, timer: 0 };
function mood(name, ms = 0) {
  const el = $('#mascot');
  clearTimeout(H.timer);
  if (H.name !== name) { H.name = name; mascot(el, name); }
  if (ms) { H.until = Date.now() + ms; H.timer = setTimeout(() => mood('ghost'), ms); } else H.until = 0;
}
function burst(x, y, n = 16) {
  if (reduced) return;
  const cols = ['#FFD60A', '#FF8FB1', '#7C5CFF', '#34C759', '#fff'];
  for (let i = 0; i < n; i++) {
    const s = document.createElement('i'); s.className = 'spk';
    s.textContent = ['✦', '✧', '✦', '✨', '★'][i % 5];
    const ang = (Math.PI * 2 * i) / n + Math.random() * .5, dist = 50 + Math.random() * 70;
    s.style.cssText = `left:${x}px;top:${y}px;color:${cols[i % cols.length]};--dx:${Math.cos(ang) * dist}px;--dy:${Math.sin(ang) * dist - 20}px;--rot:${Math.random() * 360}deg`;
    document.body.appendChild(s); setTimeout(() => s.remove(), 950);
  }
}
function celebrate(el) {
  mood('ok', 2400); hap('success');
  const r = (el || $('#mascot')).getBoundingClientRect();
  burst(r.left + r.width / 2, r.top + r.height / 2);
  const m = $('#mascot').getBoundingClientRect();
  if (el) burst(m.left + m.width / 2, m.top + m.height / 2, 10);
}
function render(el, html) {
  el.innerHTML = html;
  $$('.rise', el).forEach((n, i) => n.style.setProperty('--i', i));
  hydrate(el);
}
function hydrate(root) { $$('[data-m]', root).forEach(el => { if (!el.firstChild) mascot(el, el.dataset.m); }); }
function stateHTML({ m = 'sleep', title, text = '', btn = '', act = '' }) {
  return `<div class="state rise"><div class="m" data-m="${m}"></div><h3>${title}</h3><p class="muted">${text}</p>${btn ? `<button class="btn" data-act="${act}">${btn}</button>` : ''}</div>`;
}
function fail(el, retry, text = 'Не получилось загрузить. Попробуем ещё раз?') {
  mood('wow', 2600); hap('error');
  render(el, stateHTML({ m: 'wow', title: 'Ой, не вышло', text, btn: 'Ещё раз', act: 'retry' }));
  const s = $('.state', el); if (s) s._retry = retry;
}
const skRows = (n, h = 56) => Array.from({ length: n }, () => `<div class="sk" style="height:${h}px;margin-bottom:12px"></div>`).join('');
const skCard = (lines = 3) => `<div class="card"><div class="sk" style="height:20px;width:40%;margin-bottom:16px"></div>${Array.from({ length: lines }, () => '<div class="sk" style="height:40px;margin-bottom:8px"></div>').join('')}</div>`;

let toastT;
function toast(text, err) {
  const t = $('#toast'); t.textContent = text; t.classList.toggle('err', !!err); t.classList.add('on');
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), 2600);
}

/* ---------- API ---------- */
const API = '/u';
let token = null, loginP = null, pending = 0, thinkT = 0, thinking = false;
async function login() {
  const r = await fetch(API + '/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ initData: TG ? TG.initData : '' }) });
  if (!r.ok) throw new Error('login ' + r.status);
  token = (await r.json()).token;
}
async function api(method, path, body, opts = {}) {
  pending++;
  if (pending === 1) thinkT = setTimeout(() => { if (pending > 0 && Date.now() > H.until) { thinking = true; mood('think'); } }, 380);
  try {
    if (DEMO) return await window.UguMock.handle(method, path, body, opts);
    if (!token) await (loginP = loginP || login().finally(() => { loginP = null; }));
    const isForm = body instanceof FormData;
    const go = () => fetch(API + path, { method, headers: { Authorization: 'Bearer ' + token, ...(body && !isForm ? { 'Content-Type': 'application/json' } : {}) }, body: body ? (isForm ? body : JSON.stringify(body)) : undefined });
    let res = await go();
    if (res.status === 401) { token = null; await (loginP = loginP || login().finally(() => { loginP = null; })); res = await go(); }
    if (!res.ok) throw new Error(res.status);
    const ct = res.headers.get('content-type') || '';
    if (opts.any) return ct.includes('image') ? { blob: await res.blob() } : { json: await res.json() };
    return ct.includes('json') ? await res.json() : {};
  } finally {
    pending--;
    if (pending === 0) { clearTimeout(thinkT); if (thinking && Date.now() > H.until) mood('ghost'); thinking = false; }
  }
}
const qs = o => Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
const arr = r => Array.isArray(r) ? r : (r && (r.items || r.chats || r.days || r.messages || r.results)) || [];

const mediaCache = new Map();
async function getMedia(chat, id) {
  const k = chat + '|' + id;
  if (mediaCache.has(k)) return mediaCache.get(k);
  let url;
  if (DEMO) { await wait(200); url = window.UguMock.mediaUrl(chat, id); }
  else {
    if (!token) await (loginP = loginP || login().finally(() => { loginP = null; }));
    const r = await fetch(`${API}/api/media?${qs({ chat, id })}`, { headers: { Authorization: 'Bearer ' + token } });
    if (!r.ok) throw new Error(r.status);
    url = URL.createObjectURL(await r.blob());
  }
  mediaCache.set(k, url); return url;
}
const mediaObs = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(e => {
  if (!e.isIntersecting) return;
  const img = e.target; mediaObs.unobserve(img);
  const [chat, id] = img.dataset.media.split('|');
  getMedia(chat, id).then(u => { img.src = u; img.classList.add('ld'); }).catch(() => { img.alt = 'Не загрузилось'; });
}), { rootMargin: '200px' }) : null;
function hydrateMedia(root) { $$('img[data-media]', root).forEach(i => mediaObs ? mediaObs.observe(i) : getMedia(...i.dataset.media.split('|')).then(u => { i.src = u; })); }

/* ---------- безопасный html от Угу ---------- */
const ALLOW = new Set(['B', 'STRONG', 'I', 'EM', 'U', 'S', 'STRIKE', 'DEL', 'A', 'CODE', 'PRE', 'BR', 'BLOCKQUOTE', 'TG-SPOILER']);
function clean(html) {
  const doc = new DOMParser().parseFromString('<body>' + String(html || '') + '</body>', 'text/html');
  (function walk(n) {
    [...n.childNodes].forEach(c => {
      if (c.nodeType === 3) return;
      if (c.nodeType !== 1) { c.remove(); return; }
      if (!ALLOW.has(c.tagName)) { c.replaceWith(doc.createTextNode(c.textContent)); return; }
      [...c.attributes].forEach(a => { if (!(c.tagName === 'A' && a.name === 'href')) c.removeAttribute(a.name); });
      if (c.tagName === 'A') { const h = c.getAttribute('href') || ''; if (!/^(https?:|tg:)/i.test(h)) c.removeAttribute('href'); }
      if (c.tagName === 'TG-SPOILER') { const s = doc.createElement('span'); s.className = 'spoiler'; s.innerHTML = c.innerHTML; c.replaceWith(s); walk(s); return; }
      walk(c);
    });
  })(doc.body);
  return doc.body.innerHTML;
}

/* ---------- разбор напоминания (для превью) ---------- */
function parseRemind(raw) {
  let text = ' ' + String(raw || '').trim() + ' ';
  const l = () => text.toLowerCase();
  const now = new Date(); let when = null, m;
  text = text.replace(/\s(напомни(ть)?|мне)(?=\s)/gi, ' ');
  if ((m = l().match(/\sчерез\s+(\d+)\s*(мин\S*|час\S*|ч|м)(?=\s|$)/))) {
    const n = +m[1], mins = /^ч/.test(m[2]) ? n * 60 : n;
    when = new Date(now.getTime() + mins * 60000); text = text.replace(m[0], ' ');
    return { when, text: tidy(text), exact: true };
  }
  let off = null;
  if ((m = l().match(/\sпослезавтра(?=\s)/))) { off = 2; text = text.replace(m[0], ' '); }
  else if ((m = l().match(/\sзавтра(?=\s)/))) { off = 1; text = text.replace(m[0], ' '); }
  else if ((m = l().match(/\sсегодня(?=\s)/))) { off = 0; text = text.replace(m[0], ' '); }
  else if ((m = l().match(/\s(?:в|на)\s+(понедельник|вторник|сред[ауы]|четверг|пятниц[ауы]|суббот[ауы]|воскресенье)(?=\s)/))) {
    const idx = ['понед', 'вторн', 'сред', 'четв', 'пятн', 'субб', 'воск'].findIndex(p => m[1].startsWith(p));
    off = (idx - wdi(now) + 7) % 7 || 7; text = text.replace(m[0], ' ');
  }
  let h = null, mi = 0;
  if ((m = l().match(/\s(?:в|к)\s+(\d{1,2})(?:[:.](\d{2}))?(?=\s|$)/))) { h = +m[1]; mi = +(m[2] || 0); text = text.replace(m[0], ' '); }
  else if ((m = l().match(/\s(утром|днём|днем|вечером)(?=\s|$)/))) { h = { 'утром': 9, 'днём': 13, 'днем': 13, 'вечером': 19 }[m[1]]; text = text.replace(m[0], ' '); }
  if (h === null && off === null) return { when: null, text: tidy(text) };
  if (h !== null && h > 23) return { when: null, text: tidy(text) };
  when = new Date(now); when.setHours(h ?? 9, mi, 0, 0);
  if (off !== null) when.setDate(when.getDate() + off);
  else if (when < now) when.setDate(when.getDate() + 1);
  return { when, text: tidy(text) };
}
const tidy = t => { t = t.replace(/\s+/g, ' ').replace(/^[\s,.:;-]+|[\s,.:;-]+$/g, ''); return t ? t[0].toUpperCase() + t.slice(1) : ''; };
window.UguParse = parseRemind;

/* ---------- шторки и страницы ---------- */
const layers = $('#layers');
function openSheet({ title, html, mount, onClose }) {
  const ov = document.createElement('div'); ov.className = 'overlay';
  ov.innerHTML = `<div class="sheet" role="dialog" aria-label="${esc(title || '')}"><div class="grab"></div>${title ? `<div class="sheet-h"><h2>${esc(title)}</h2><button class="icon-b" data-act="close" aria-label="Закрыть">${IC.x}</button></div>` : ''}<div class="sheet-body">${html}</div></div>`;
  layers.appendChild(ov);
  const body = $('.sheet-body', ov);
  const rec = { el: ov, body, close() { const i = stack.indexOf(rec); if (i < 0) return; stack.splice(i, 1); ov.classList.remove('open'); syncBack(); setTimeout(() => ov.remove(), 420); if (onClose) onClose(); } };
  ov.addEventListener('click', e => { if (e.target === ov) rec.close(); });
  stack.push(rec); syncBack();
  $$('.rise', ov).forEach((n, i) => n.style.setProperty('--i', i));
  hydrate(ov);
  if (mount) mount(rec);
  requestAnimationFrame(() => requestAnimationFrame(() => ov.classList.add('open')));
  hap('light');
  return rec;
}
function confirmSheet({ title, text, ok, danger, fn }) {
  const s = openSheet({ title, html: `<p class="muted" style="margin-bottom:16px">${esc(text)}</p><div class="stack"><button class="btn ${danger ? 'danger' : ''}" data-ok>${esc(ok)}</button><button class="btn soft" data-act="close">Отмена</button></div>` });
  $('[data-ok]', s.el).onclick = () => { s.close(); fn(); };
}

/* ---------- вкладки ---------- */
const S = { me: null, tab: 'today', loaded: {}, tier: 'pro', period: 'month' };
const VIEWS = {};
function renderTabs() {
  $('#tabs').innerHTML = TABS.map(t => `<button data-act="tab" data-id="${t.id}" aria-label="${t.title}"><svg viewBox="0 0 24 24">${t.svg}</svg>${t.title}</button>`).join('');
}
function greeting() {
  const h = new Date().getHours();
  return h >= 5 && h < 12 ? 'Доброе утро' : h < 18 && h >= 12 ? 'Добрый день' : h >= 18 && h < 23 ? 'Добрый вечер' : 'Доброй ночи';
}
function setHeader() {
  const d = new Date(), name = S.me ? S.me.user.name : '';
  if (S.tab === 'today') {
    $('#hTitle').textContent = name ? `${greeting()}, ${name}` : greeting();
    $('#hSub').textContent = `${WD[wdi(d)]}, ${d.getDate()} ${MON[d.getMonth()]}`;
  } else {
    $('#hTitle').textContent = TABS.find(t => t.id === S.tab).title;
    $('#hSub').textContent = TAB_SUB[S.tab];
  }
}
function setUser() {
  const me = S.me; if (!me) return;
  $('#hBadge').textContent = me.tier;
  const ava = $('#hAva'), photo = IN_TG && TG.initDataUnsafe && TG.initDataUnsafe.user && TG.initDataUnsafe.user.photo_url;
  ava.innerHTML = photo ? `<img src="${esc(photo)}" alt="">` : esc(initial(me.user.name));
  setHeader();
}
function go(id, { force = false, quiet = false } = {}) {
  if (id === S.tab && !force && S.loaded[id]) return;
  const ids = TABS.map(t => t.id), dir = ids.indexOf(id) >= ids.indexOf(S.tab) ? 'in-r' : 'in-l';
  if (id !== S.tab) {
    $$('.view').forEach(v => v.classList.remove('on', 'in-r', 'in-l'));
    const v = $('#v-' + id); v.classList.add('on'); if (!reduced) v.classList.add(dir);
    S.tab = id; window.scrollTo(0, 0);
    $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.id === id));
    if (!quiet) hap('select');
    setHeader();
  }
  if (!S.loaded[id] || force || Date.now() - S.loaded[id] > 60000) { S.loaded[id] = Date.now(); VIEWS[id].load(); }
}

/* ============ СЕГОДНЯ ============ */
VIEWS.today = {
  async load() {
    const el = $('#v-today');
    if (!$('#tCards', el)) {
      render(el, `<div class="card askbar rise"><input id="askIn" data-enter="ask-go" placeholder="Спроси Угу…" enterkeyhint="send" autocomplete="off" aria-label="Спроси Угу"><button class="send" data-act="ask-go" aria-label="Спросить">${IC.send}</button></div><div id="askOut"></div><div id="tCards" class="stack" style="margin-top:16px"></div>`);
    }
    const box = $('#tCards');
    if (!box.children.length) render(box, skCard(3) + skCard(2) + skCard(1));
    const t0 = new Date(), t1 = new Date(); t1.setDate(t1.getDate() + 14);
    try {
      const [today, plans] = await Promise.all([
        api('GET', '/api/today').catch(() => null),
        api('GET', `/api/plans?${qs({ from: ymd(t0), to: ymd(t1) })}`),
      ]);
      this.draw(box, today || { counters: { deleted: 0, edited: 0, voice: 0 }, waiting: [], birthdays: null }, arr(plans));
    } catch (e) { fail(box, () => this.load()); }
  },
  draw(box, today, plans) {
    const now = Date.now();
    const rem = plans.filter(p => p.kind === 'remind' && !p.done && pd(p.when) >= now - 36e5).sort((a, b) => a.when.localeCompare(b.when)).slice(0, 3);
    const wait3 = today.waiting || [];
    const bd = (today.birthdays || plans.filter(p => p.kind === 'birthday').map(p => ({ name: p.text.replace(/^День рождения\s*/i, ''), days: dayDiff(pd(p.date)), date: p.date }))).filter(b => b.days >= 0 && b.days <= 14);
    const c = today.counters || { deleted: 0, edited: 0, voice: 0 };
    const quiet = !rem.length && !wait3.length && !bd.length && !(c.deleted + c.edited + c.voice);
    if (quiet) return render(box, stateHTML({ title: 'Сегодня тихо', text: 'Отдыхай, я посторожу.' }));
    const remRows = rem.length ? rem.map(p => `<div class="item" data-id="${esc(p.id)}"><div class="time">${esc(relLabel(p.when))}</div><div class="grow"><div class="t1">${esc(p.text)}</div>${p.chat ? `<div class="t2 muted">из чата ${esc(p.chat)}</div>` : ''}</div><button class="done-b" data-act="done" data-id="${esc(p.id)}" aria-label="Готово">${IC.check}</button></div>`).join('') : '<p class="muted">Ничего срочного. Можно выдохнуть.</p>';
    const waitCard = wait3.length ? `<div class="card rise"><h2>⏳ Ждут ответа</h2>${wait3.map(w => `<div class="item"><div class="av" style="background:${colorOf(w.name)}">${esc(initial(w.name))}</div><div class="grow"><div class="t1">${esc(w.name)} <span class="muted" style="font-weight:600">· ${w.hours} ч</span></div><div class="t2 muted">${esc(w.text)}</div></div><button class="btn soft sm" data-act="open-chat" data-id="${esc(w.chat_id)}" data-name="${esc(w.name)}">Открыть</button></div>`).join('')}</div>` : '';
    const bdCard = bd.length ? `<div class="card rise"><h2>🎂 Скоро день рождения</h2>${bd.map(b => `<div class="item"><div class="av" style="background:${colorOf(b.name)}">${esc(initial(b.name))}</div><div class="grow"><div class="t1">${esc(b.name)}</div><div class="t2 muted">${b.days === 0 ? 'сегодня' : b.days === 1 ? 'завтра' : `через ${b.days} ${plural(b.days, 'день', 'дня', 'дней')}`}</div></div></div>`).join('')}</div>` : '';
    render(box, `
      <div class="card rise" id="remCard"><h2>📅 Ближайшее</h2><div id="remRows">${remRows}</div></div>
      ${waitCard}
      <div class="card rise"><h2>📊 За сегодня</h2><div class="counters">
        <button class="counter red" data-act="counter" data-k="deleted"><b>${c.deleted}</b><span class="muted">удалено</span></button>
        <button class="counter" data-act="counter" data-k="edited"><b>${c.edited}</b><span class="muted">изменено</span></button>
        <button class="counter" data-act="counter" data-k="voice"><b>${c.voice}</b><span class="muted">ГС в текст</span></button></div></div>
      ${bdCard}`);
  },
};

/* ответы Угу (общая часть) */
async function askUgu(q, kind) { return api('POST', '/api/ask', { q, ...(kind ? { kind } : {}) }); }
function answerHTML(r, q, ctx) {
  const imgs = (r.images || []).length ? `<div class="ans-imgs">${r.images.map(i => `<img src="${esc(i.thumb || i.url)}" data-full="${esc(i.url)}" data-act="zoom" alt="" loading="lazy">`).join('')}</div>` : '';
  const ch = (r.choices || []).length ? `<div class="row wrap" style="margin-top:12px;gap:8px">${r.choices.map(c => `<button class="chip" data-act="choice" data-kind="${esc(c.kind)}" data-q="${esc(q)}" data-ctx="${ctx}">${esc(c.label)}</button>`).join('')}</div>` : '';
  return `<div class="ans" style="white-space:pre-line">${clean(r.html)}</div>${imgs}${ch}`;
}
const typingHTML = '<div class="typing"><i></i><i></i><i></i></div>';

/* ============ ЧАТЫ ============ */
const CS = { q: '', only: '', cur: null };
VIEWS.chats = {
  async load() {
    const el = $('#v-chats');
    if (!$('#chList', el)) {
      render(el, `<div class="search rise">${IC.search}<input class="inp" id="chQ" data-input="chats" placeholder="Поиск по всем чатам" autocomplete="off" aria-label="Поиск"></div>
        <div class="chips rise" style="margin:12px -16px" id="chF"></div><div id="chList"></div>`);
    }
    $('#chQ').value = CS.q;
    $('#chF').innerHTML = [['', 'Все'], ['deleted', '🗑 Только удалённое'], ['media', '🖼 Только медиа']].map(([k, l]) => `<button class="chip ${CS.only === k ? 'on' : ''}" data-act="chfilter" data-k="${k}">${l}</button>`).join('');
    const box = $('#chList');
    if (!box.children.length || box.dataset.stale) render(box, skRows(6, 64));
    box.dataset.stale = '';
    const searching = CS.q || CS.only;
    try {
      if (searching) {
        const r = arr(await api('GET', `/api/search?${qs({ q: CS.q, deleted: CS.only === 'deleted' ? 1 : '', media: CS.only === 'media' ? 1 : '' })}`));
        const items = r.filter(h => (CS.only !== 'deleted' || h.deleted) && (CS.only !== 'media' || h.media));
        if (!items.length) return render(box, stateHTML({ m: 'find', title: 'Ничего не нашёл', text: 'Попробуй другое слово.' }));
        render(box, `<div class="card rise">${items.map(h => `<button class="hit" data-act="open-chat" data-id="${esc(h.chat)}" data-name="${esc(h.chat_name)}" data-day="${esc(h.day)}"><div class="row" style="gap:8px"><b>${esc(h.chat_name)}</b><span class="muted t2">${esc(dayChip(h.day))}, ${esc(h.time)}</span>${h.deleted ? `<span class="del-b">🗑 ${esc(h.deleted)}</span>` : ''}</div><div class="t2" style="white-space:normal;margin-top:2px">${hl(h.text, CS.q)}</div></button>`).join('')}</div>`);
      } else {
        const items = arr(await api('GET', '/api/chats'));
        if (!items.length) return render(box, stateHTML({ title: 'Пока пусто', text: 'Подключи меня к Telegram для бизнеса, и переписки появятся здесь.', btn: 'Как подключить', act: 'onb' }));
        render(box, `<div class="card rise" style="padding:4px 16px">${items.map(c => `<button class="item" style="width:100%;text-align:left" data-act="open-chat" data-id="${esc(c.id)}" data-name="${esc(c.name)}"><div class="av" style="background:${colorOf(c.name)}">${esc(initial(c.name))}</div><div class="grow"><div class="t1">${esc(c.name)}</div><div class="t2 muted">${esc(c.last)}</div></div><div style="text-align:right;display:flex;flex-direction:column;gap:4px;align-items:flex-end"><span class="t2 muted">${esc(chatTime(c.ts))}</span>${c.deleted ? `<span class="del-b">🗑 ${c.deleted}</span>` : ''}</div></button>`).join('')}</div>`);
      }
    } catch (e) { fail(box, () => this.load()); }
  },
};

function openChat(id, name, day) {
  const pg = document.createElement('div'); pg.className = 'page';
  pg.innerHTML = `<div class="page-in"><div class="page-h"><button class="icon-b" data-act="close" aria-label="Назад">${IC.back}</button><div class="av" style="background:${colorOf(name)}">${esc(initial(name))}</div><div class="grow"><div class="t1" style="font-size:18px">${esc(name)}</div><div class="t2 muted">архив переписки</div></div></div>
    <div class="chips wrapc" style="margin-bottom:12px"><button class="chip" data-act="chat-ai" data-k="Кратко">✨ Кратко</button><button class="chip" data-act="chat-ai" data-k="Договорённости">🤝 Договорённости</button><button class="chip" data-act="chat-ai" data-k="Статистика">📈 Статистика</button></div>
    <div class="dayrow" id="cDays">${skRows(1, 36)}</div><div class="msgs" id="cMsgs">${skRows(4, 48)}</div></div>`;
  layers.appendChild(pg);
  const rec = { el: pg, close() { const i = stack.indexOf(rec); if (i < 0) return; stack.splice(i, 1); pg.classList.remove('open'); syncBack(); setTimeout(() => pg.remove(), 420); CS.cur = null; } };
  stack.push(rec); syncBack();
  requestAnimationFrame(() => requestAnimationFrame(() => pg.classList.add('open')));
  CS.cur = { id, name, msgs: {}, day: null, days: [] };
  hap('light');
  loadDays(day);
}
async function loadDays(want) {
  const c = CS.cur; if (!c) return;
  const box = $('#cDays');
  try {
    c.days = arr(await api('GET', `/api/days?${qs({ chat: c.id })}`));
    if (!c.days.length) { box.innerHTML = ''; return render($('#cMsgs'), stateHTML({ title: 'Здесь пока тихо', text: 'Сообщений в архиве нет.' })); }
    box.innerHTML = c.days.map(d => `<button class="chip" data-act="pick-day" data-day="${esc(d.day)}">${esc(dayChip(d.day))}${d.deleted ? ' <span style="color:var(--del)">●</span>' : ''}</button>`).join('');
    pickDay(want && c.days.some(d => d.day === want) ? want : c.days[0].day);
  } catch (e) { box.innerHTML = ''; fail($('#cMsgs'), () => loadDays(want)); }
}
async function pickDay(day) {
  const c = CS.cur; if (!c) return; c.day = day;
  $$('#cDays .chip').forEach(b => b.classList.toggle('on', b.dataset.day === day));
  const on = $('#cDays .chip.on'); if (on) on.scrollIntoView({ inline: 'center', block: 'nearest' });
  const box = $('#cMsgs'); render(box, skRows(4, 48));
  try {
    const ms = arr(await api('GET', `/api/messages?${qs({ chat: c.id, day })}`));
    if (c.day !== day) return;
    c.msgs = {}; ms.forEach(m => { c.msgs[m.id] = m; });
    if (!ms.length) return render(box, stateHTML({ title: 'В этот день тихо', text: '' }));
    render(box, ms.map(m => bubbleHTML(m, c)).join(''));
    $$('.bub', box).forEach((n, i) => n.style.setProperty('--i', Math.min(i, 8)));
    hydrateMedia(box);
  } catch (e) { fail(box, () => pickDay(day)); }
}
function bubbleHTML(m, c) {
  const me = m.from === 'me';
  let media = '';
  if (m.media) media = m.media.kind === 'voice'
    ? `<div class="voice"><i>🎤</i><span>голосовое ${esc(m.media.dur || '')}</span></div>`
    : `<img class="media" data-media="${esc(c.id)}|${esc(m.media.id)}" data-act="zoom-media" alt="">`;
  const text = m.media && m.media.kind === 'voice' ? esc(String(m.text || '').replace(/^Голосовое:\s*/, '')) : esc(m.text || '');
  return `<div class="bub rise ${me ? 'me' : 'them'} ${m.deleted ? 'dead' : ''}" data-mid="${esc(m.id)}">
    ${!me && m.name ? `<div class="who">${esc(m.name)}</div>` : ''}
    ${m.deleted ? `<div class="plaque">🗑 удалено ${esc(m.deleted)}</div><br>` : ''}
    ${media}${text ? `<div>${text}</div>` : ''}
    ${m.was ? `<div class="edit"><div><span class="muted">было:</span> <s>${esc(m.was)}</s></div><div><span class="muted">стало:</span> ${esc(m.text)}</div></div>` : ''}
    <div class="tm">${esc(m.time)}</div></div>`;
}
function msgActions(mid) {
  const c = CS.cur, m = c && c.msgs[mid]; if (!m) return;
  const txt = m.text || '';
  const s = openSheet({ title: 'Сообщение', html: `<div class="card" style="margin-bottom:16px"><div class="t2 muted">${esc(m.name || 'Ты')}, ${esc(m.time)}</div><div style="margin-top:4px">${esc(txt) || '[медиа]'}</div></div>
    <button class="set" data-a="note"><span>📝</span><span class="grow">В заметки</span></button>
    <button class="set" data-a="remind"><span>⏰</span><span class="grow">Напомнить</span></button>
    <button class="set" data-a="copy"><span>📋</span><span class="grow">Скопировать</span></button>` });
  s.el.addEventListener('click', async e => {
    const a = e.target.closest('[data-a]'); if (!a) return;
    if (a.dataset.a === 'copy') { copy(txt); s.close(); toast('Скопировано'); }
    if (a.dataset.a === 'note') {
      s.close();
      try { await api('POST', '/api/notes', { title: `Из чата ${c.name}`, body: txt, color: 'violet' }); S.loaded.notes = 0; toast('Сохранил в заметки'); mood('love', 2200); hap('success'); }
      catch (er) { toast('Не получилось сохранить', true); }
    }
    if (a.dataset.a === 'remind') { s.close(); setTimeout(() => addSheet('remind', `напомни завтра в 9 ${txt}`), 200); }
  });
}
function copy(t) {
  try { navigator.clipboard.writeText(t); } catch (e) { const a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select(); try { document.execCommand('copy'); } catch (er) { /* ignore */ } a.remove(); }
}
function zoom(src, q) {
  const lb = document.createElement('div'); lb.className = 'lightbox';
  lb.innerHTML = `<img src="${esc(src)}" alt=""><div class="row">${q ? '<button class="btn grow" data-s>Отправить в чат</button>' : ''}<button class="btn soft ${q ? 'sm' : 'grow'}" data-x>Закрыть</button></div>`;
  document.body.appendChild(lb);
  const rec = { el: lb, close() { const i = stack.indexOf(rec); if (i < 0) return; stack.splice(i, 1); lb.classList.remove('open'); syncBack(); setTimeout(() => lb.remove(), 300); } };
  stack.push(rec); syncBack();
  requestAnimationFrame(() => lb.classList.add('open'));
  lb.addEventListener('click', e => { if (e.target === lb || e.target.closest('[data-x]')) rec.close(); });
  const sb = $('[data-s]', lb);
  if (sb) sb.onclick = () => shareInline(q);
}
function shareInline(q) {
  hap('medium');
  if (IN_TG && TG.switchInlineQuery) { try { TG.switchInlineQuery(q, ['users', 'groups', 'channels']); return; } catch (e) { /* ignore */ } }
  toast('В Telegram здесь откроется выбор чата');
}

/* ============ ПЛАНЫ ============ */
const PS = { week: null, sel: ymd(new Date()), items: [], busy: null };
const mondayOf = d => { const x = new Date(d); x.setDate(x.getDate() - wdi(x)); x.setHours(0, 0, 0, 0); return x; };
PS.week = mondayOf(new Date());
VIEWS.plans = {
  async load(quiet) {
    const el = $('#v-plans');
    if (!$('#pBody', el)) render(el, `<div id="pBusy"></div><div class="card rise" id="pWeek"></div><div id="pBody" class="stack" style="margin-top:16px;padding-bottom:80px"></div><button class="fab" data-act="add" aria-label="Добавить">${IC.plus}</button>`);
    this.drawWeek();
    const box = $('#pBody');
    if (!quiet) render(box, skCard(3));
    const end = new Date(PS.week); end.setDate(end.getDate() + 6);
    try {
      const r = await api('GET', `/api/plans?${qs({ from: ymd(PS.week), to: ymd(end) })}`);
      PS.items = arr(r); PS.busy = (r && r.busy) || null;
      this.drawBusy(); this.drawWeek(); this.drawDay();
    } catch (e) { fail(box, () => this.load()); }
  },
  drawBusy() {
    const b = PS.busy;
    render($('#pBusy'), `<div class="card rise" style="margin-bottom:16px"><button class="row" style="width:100%;text-align:left" data-act="busy"><span style="font-size:26px">🌙</span><div class="grow"><div class="t1">Режим «занят»</div><div class="t2 muted" style="white-space:normal">${b ? `до ${esc(hm(pd(b.until)))} · ${esc(b.text)}` : 'Отвечу за тебя, пока ты занят'}</div></div><span class="sw ${b ? 'on' : ''}"></span></button></div>`);
  },
  drawWeek() {
    const d0 = PS.week, d6 = new Date(d0); d6.setDate(d6.getDate() + 6);
    const todayS = ymd(new Date());
    const has = new Set(PS.items.filter(i => i.kind !== 'task').map(i => (i.when || i.date || '').slice(0, 10)));
    const title = d0.getMonth() === d6.getMonth() ? `${MONN[d0.getMonth()]}, ${d0.getDate()}-${d6.getDate()}` : `${d0.getDate()} ${MON[d0.getMonth()].slice(0, 3)} - ${d6.getDate()} ${MON[d6.getMonth()].slice(0, 3)}`;
    const days = Array.from({ length: 7 }, (_, i) => { const d = new Date(d0); d.setDate(d.getDate() + i); return d; });
    $('#pWeek').innerHTML = `<div class="row" style="margin-bottom:8px"><button class="icon-b" data-act="week" data-d="-1" aria-label="Назад">${IC.back}</button><div class="grow t1" style="text-align:center;font-size:17px">${title}</div><button class="icon-b" data-act="week" data-d="1" aria-label="Вперёд" style="transform:scaleX(-1)">${IC.back}</button></div>
      <div class="week">${days.map((d, i) => `<button class="wd ${ymd(d) === PS.sel ? 'on' : ''} ${ymd(d) === todayS ? 'today' : ''}" data-act="pday" data-d="${ymd(d)}"><small>${WD[i]}</small><b>${d.getDate()}</b><i class="${has.has(ymd(d)) ? 'has' : ''}"></i></button>`).join('')}</div>`;
  },
  drawDay() {
    const box = $('#pBody'), sel = PS.sel;
    const rems = PS.items.filter(i => i.kind === 'remind' && i.when.slice(0, 10) === sel).sort((a, b) => a.when.localeCompare(b.when));
    const bds = PS.items.filter(i => i.kind === 'birthday' && i.date === sel);
    const tasks = PS.items.filter(i => i.kind === 'task');
    const d = pd(sel);
    const remHTML = rems.map(p => `<div class="pitem" data-id="${esc(p.id)}"><div class="item"><div class="time" style="${p.done ? 'opacity:.5' : ''}">${esc(p.when.slice(11))}</div><div class="grow" style="${p.done ? 'opacity:.5;text-decoration:line-through' : ''}"><div class="t1">${esc(p.text)}</div>${p.chat ? `<div class="t2 muted">из чата ${esc(p.chat)}</div>` : ''}</div>${p.done ? `<span class="done-b on">${IC.check}</span>` : `<button class="done-b" data-act="done" data-id="${esc(p.id)}" aria-label="Готово">${IC.check}</button>`}<button class="dots" data-act="pmore" aria-label="Ещё">⋯</button></div>
      <div class="acts"><button class="chip" data-act="snooze" data-id="${esc(p.id)}" data-k="hour">+1 час</button><button class="chip" data-act="snooze" data-id="${esc(p.id)}" data-k="evening">Вечер</button><button class="chip" data-act="snooze" data-id="${esc(p.id)}" data-k="tomorrow">Завтра</button><button class="chip" style="color:var(--del)" data-act="pdel" data-id="${esc(p.id)}" aria-label="Удалить">🗑</button></div></div>`).join('');
    const bdHTML = bds.map(b => `<div class="pitem"><div class="item"><div class="time">🎂</div><div class="grow t1">${esc(b.text)}</div></div></div>`).join('');
    const dayCard = (rems.length || bds.length)
      ? `<div class="card rise"><h2>${dayWord(d) === 'сегодня' ? 'Сегодня' : esc(dayWord(d)[0].toUpperCase() + dayWord(d).slice(1))}</h2>${bdHTML}${remHTML}</div>`
      : `<div class="card rise">${stateHTML({ title: 'На этот день пусто', text: 'Нажми плюс, и я запомню.' }).replace('rise', '')}</div>`;
    const taskCard = `<div class="card rise"><h2>✅ Задачи <small class="muted">${tasks.filter(t => !t.done).length} открыто</small></h2>${tasks.map(t => `<button class="task ${t.done ? 'on' : ''}" data-act="ttoggle" data-id="${esc(t.id)}"><span class="cb">${IC.check}</span><span class="grow">${esc(t.text)}</span></button>`).join('') || '<p class="muted">Задач нет.</p>'}
      <div class="row" style="margin-top:12px"><input class="inp" id="tIn" data-enter="tadd" placeholder="Новая задача" maxlength="200" aria-label="Новая задача"><button class="send" data-act="tadd" aria-label="Добавить">${IC.plus}</button></div></div>`;
    render(box, dayCard + taskCard);
  },
};
function snoozeMinutes(p, k) {
  if (k === 'hour') return 60;
  const w = pd(p.when), t = new Date(w);
  if (k === 'evening') { t.setHours(19, 0, 0, 0); if (t <= w) return 180; }
  else { t.setDate(t.getDate() + 1); t.setHours(9, 0, 0, 0); }
  return Math.max(5, Math.round((t - w) / 60000));
}

/* ============ ЗАМЕТКИ ============ */
const NOTE_COLORS = [['none', 'Без метки'], ['violet', 'Идея'], ['pink', 'Личное'], ['yellow', 'Важное'], ['green', 'Дела'], ['blue', 'Работа']];
const NS = { q: '', items: [] };
VIEWS.notes = {
  async load() {
    const el = $('#v-notes');
    if (!$('#nBody', el)) render(el, `<div class="search rise">${IC.search}<input class="inp" id="nQ" data-input="notes" placeholder="Поиск по заметкам" autocomplete="off" aria-label="Поиск по заметкам"></div><div id="nBody" style="margin-top:16px;padding-bottom:80px"></div><button class="fab" data-act="note-new" aria-label="Новая заметка">${IC.plus}</button>`);
    const box = $('#nBody');
    render(box, `<div class="masonry">${[90, 130, 110, 80, 120, 100].map(h => `<div class="sk" style="height:${h}px;margin-bottom:12px;border-radius:18px"></div>`).join('')}</div>`);
    try {
      NS.items = arr(await api('GET', `/api/notes?${qs({ q: NS.q })}`));
      this.draw();
    } catch (e) { fail(box, () => this.load()); }
  },
  draw() {
    const box = $('#nBody');
    if (!NS.items.length) return render(box, stateHTML({ title: NS.q ? 'Ничего не нашёл' : 'Заметок пока нет', text: NS.q ? 'Попробуй другое слово.' : 'Запиши мысль, я сохраню.', btn: NS.q ? '' : 'Новая заметка', act: 'note-new' }));
    const card = n => `<button class="note rise nc-${esc(n.color || 'none')}" data-act="note-open" data-id="${esc(n.id)}">${n.pinned ? '<span class="pin">📌</span>' : ''}${n.title ? `<b>${hl(n.title, NS.q)}</b>` : ''}<p>${hl(n.body, NS.q)}</p>${n.color && n.color !== 'none' ? `<span class="lab">${esc(NOTE_COLORS.find(c => c[0] === n.color)[1])}</span>` : ''}</button>`;
    const pin = NS.items.filter(n => n.pinned), rest = NS.items.filter(n => !n.pinned);
    render(box, `${pin.length ? `<div class="sec-t muted" style="margin-top:0">Закреплённые</div><div class="masonry">${pin.map(card).join('')}</div>` : ''}${rest.length ? `${pin.length ? '<div class="sec-t muted">Остальные</div>' : ''}<div class="masonry">${rest.map(card).join('')}</div>` : ''}`);
  },
};
function noteSheet(id) {
  const n = id ? NS.items.find(x => x.id === id) : null;
  let color = n ? n.color || 'none' : 'none';
  const s = openSheet({
    title: n ? 'Заметка' : 'Новая заметка',
    html: `<div class="stack"><input class="inp" id="nT" placeholder="Заголовок" maxlength="120" value="${esc(n ? n.title : '')}" aria-label="Заголовок"><textarea class="inp" id="nB" rows="5" placeholder="Что запомнить?" maxlength="5000" aria-label="Текст">${esc(n ? n.body : '')}</textarea>
      <div><div class="sec-t muted" style="margin-top:0">Метка</div><div class="swatches">${NOTE_COLORS.map(([k, l]) => `<button class="swatch sw-${k} ${k === color ? 'on' : ''}" data-c="${k}" aria-label="${l}" title="${l}"></button>`).join('')}</div></div>
      <button class="btn" data-save>Сохранить</button>
      ${n ? `<div class="row wrap"><button class="btn soft sm grow" data-pin>${n.pinned ? '📌 Открепить' : '📌 Закрепить'}</button><button class="btn soft sm grow" data-rem>⏰ Напомнить</button></div><button class="btn danger" data-del>Удалить заметку</button>` : ''}</div>`,
  });
  const r = s.el;
  r.addEventListener('click', async e => {
    const c = e.target.closest('[data-c]');
    if (c) { color = c.dataset.c; $$('.swatch', r).forEach(x => x.classList.toggle('on', x === c)); hap('select'); return; }
    if (e.target.closest('[data-save]')) {
      const title = $('#nT', r).value.trim(), body = $('#nB', r).value.trim();
      if (!title && !body) { toast('Напиши хоть пару слов', true); hap('error'); return; }
      try {
        if (n) await api('PUT', `/api/notes/${encodeURIComponent(n.id)}`, { title, body, color });
        else await api('POST', '/api/notes', { title, body, color });
        s.close(); hap('success'); toast('Сохранил'); VIEWS.notes.load();
      } catch (er) { toast('Не получилось сохранить', true); hap('error'); }
    }
    if (e.target.closest('[data-pin]')) {
      try {
        const r2 = await api('POST', `/api/notes/${encodeURIComponent(n.id)}/pin`);
        const nowPinned = r2 && typeof r2.pinned === 'boolean' ? r2.pinned : !n.pinned;
        s.close(); VIEWS.notes.load();
        if (nowPinned) { mood('love', 2600); hap('success'); const m = $('#mascot').getBoundingClientRect(); burst(m.left + m.width / 2, m.top + m.height / 2, 12); toast('Закрепил наверху'); }
      } catch (er) { toast('Не получилось', true); }
    }
    if (e.target.closest('[data-rem]')) { const t = ($('#nT', r).value + ' ' + $('#nB', r).value).trim(); s.close(); setTimeout(() => addSheet('remind', 'напомни завтра в 9 ' + t.slice(0, 120)), 250); }
    if (e.target.closest('[data-del]')) confirmSheet({ title: 'Удалить заметку?', text: 'Вернуть её не получится.', ok: 'Удалить', danger: true, fn: async () => { try { await api('DELETE', `/api/notes/${encodeURIComponent(n.id)}`); s.close(); hap('success'); toast('Удалил'); VIEWS.notes.load(); } catch (er) { toast('Не получилось', true); } } });
  });
}

/* ============ УГУ ============ */
const US = { seg: 'ans', log: [], imgQ: 'котики', imgOff: 0, imgNext: 0, imgBusy: false, file: null, fileUrl: '', act: 'describe' };
try { US.log = JSON.parse(localStorage.ugu_log || '[]').slice(-20); } catch (e) { US.log = []; }
const CAM_ACTS = [['describe', '🔎 Что это'], ['product', '🛍 Найти товар'], ['demotivator', '🖼 Демотиватор'], ['shakal', '📉 Шакал'], ['zhmykh', '🌀 Жмых'], ['meme', '😂 Мем']];
const SUGG = ['Погода завтра', 'Курс доллара', 'Скинь мем', 'Что у меня на неделе'];
VIEWS.ugu = {
  load() {
    const el = $('#v-ugu');
    if ($('#uBody', el)) return;
    render(el, `<div class="seg rise" id="uSeg"><i></i><button data-act="useg" data-k="ans">Ответы</button><button data-act="useg" data-k="img">Картинки</button><button data-act="useg" data-k="cam">Камера</button></div><div id="uBody" style="margin-top:16px"></div>`);
    this.seg(US.seg, true);
  },
  seg(k, first) {
    US.seg = k;
    const i = ['ans', 'img', 'cam'].indexOf(k);
    $$('#uSeg button').forEach((b, j) => b.classList.toggle('on', j === i));
    $('#uSeg i').style.cssText = `width:calc((100% - 8px)/3);transform:translateX(${i * 100}%)`;
    const box = $('#uBody'); box.className = first || reduced ? '' : 'rise'; void box.offsetWidth; box.className = 'rise';
    if (k === 'ans') this.ans(); else if (k === 'img') this.img(); else this.cam();
  },
  ans() {
    const box = $('#uBody');
    const log = US.log.length ? US.log.map(m => m.r ? `<div class="a">${answerHTML(m.r, m.q, 'log')}</div>` : `<div class="q">${esc(m.q)}</div>`).join('') : `<div class="state" style="padding:16px"><div class="m" data-m="hi"></div><h3>Привет, я Угу</h3><p class="muted">Спроси что угодно или выбери подсказку.</p></div>`;
    render(box, `<div class="log" id="uLog">${log}</div><div class="chips" style="margin-bottom:8px">${SUGG.map(s => `<button class="chip" data-act="sugg" data-q="${esc(s)}">${esc(s)}</button>`).join('')}</div><div class="card askbar inputbar"><input id="uIn" data-enter="u-go" placeholder="Спроси Угу…" enterkeyhint="send" autocomplete="off" aria-label="Вопрос"><button class="send" data-act="u-go" aria-label="Спросить">${IC.send}</button></div>`);
    $$('#uLog .q, #uLog .a').forEach(n => n.classList.remove('rise'));
  },
  async img(more) {
    const box = $('#uBody');
    if (!more) {
      US.imgOff = 0; US.imgNext = 0;
      render(box, `<div class="search">${IC.search}<input class="inp" id="iQ" data-enter="img-go" placeholder="Что найти?" value="${esc(US.imgQ)}" enterkeyhint="search" autocomplete="off" aria-label="Поиск картинок"></div>
        <div class="chips" style="margin:12px -16px">${['котики', 'мемы', 'аниме', 'природа', 'еда'].map(s => `<button class="chip ${US.imgQ === s ? 'on' : ''}" data-act="img-chip" data-q="${s}">${s}</button>`).join('')}</div><div class="grid3" id="iGrid">${Array.from({ length: 9 }, () => '<div class="im sk"></div>').join('')}</div><div id="iMore" style="height:48px"></div>`);
    }
    if (US.imgBusy) return; US.imgBusy = true;
    const grid = $('#iGrid'), q = US.imgQ;
    try {
      const r = await api('GET', `/api/images?${qs({ q, offset: US.imgOff })}`);
      if (q !== US.imgQ) return;
      const items = arr(r);
      if (!more) grid.innerHTML = '';
      if (!items.length && !more) return render(grid.parentNode.querySelector('#iMore'), stateHTML({ m: 'find', title: 'Ничего не нашёл', text: 'Попробуй другое слово.' }));
      grid.insertAdjacentHTML('beforeend', items.map((i, k) => `<button class="im" style="animation-delay:${k * 30}ms" data-act="zoom" data-full="${esc(i.url)}" data-q="${esc(q)}"><img src="${esc(i.thumb || i.url)}" alt="" loading="lazy"></button>`).join(''));
      US.imgNext = r.next; US.imgOff = r.next || 0;
      if (r.next && 'IntersectionObserver' in window) { const sentinel = $('#iMore'); const io = new IntersectionObserver(es => { if (es[0].isIntersecting) { io.disconnect(); VIEWS.ugu.img(true); } }, { rootMargin: '400px' }); io.observe(sentinel); }
    } catch (e) { if (!more) fail($('#uBody'), () => this.img()); else toast('Дальше не загрузилось', true); }
    finally { US.imgBusy = false; }
  },
  cam() {
    const box = $('#uBody');
    const txtOn = ['demotivator', 'meme'].includes(US.act);
    render(box, `<div class="stack"><label class="drop" for="camF" tabindex="0">${US.fileUrl ? `<img src="${esc(US.fileUrl)}" alt="">` : `<div class="m" style="width:88px;height:88px" data-m="photo"></div><b>Снять или выбрать фото</b><span class="muted t2">Скажу, что на нём, или сделаю эффект</span>`}</label>
      <input type="file" id="camF" accept="image/*" capture="environment" class="hide">
      <div class="acts-g">${CAM_ACTS.map(([k, l]) => `<button class="chip ${US.act === k ? 'on' : ''}" data-act="cam-act" data-k="${k}">${l}</button>`).join('')}</div>
      ${txtOn ? '<input class="inp" id="camT" placeholder="Подпись" maxlength="120" aria-label="Подпись">' : ''}
      <button class="btn" data-act="cam-go" ${US.file ? '' : 'disabled'}>Сделать</button><div id="camOut"></div></div>`);
  },
};

/* ============ ДЕЙСТВИЯ ============ */
function addSheet(kind, preset) {
  let mode = kind || 'remind';
  const s = openSheet({
    title: 'Добавить', html: `<div class="seg" id="aSeg" style="margin-bottom:16px"><i></i><button data-k="remind">⏰ Напоминание</button><button data-k="task">✅ Задача</button></div><div id="aBody"></div>`,
    mount(rec) {
      const draw = () => {
        $$('#aSeg button', rec.el).forEach(b => b.classList.toggle('on', b.dataset.k === mode));
        $('#aSeg i', rec.el).style.cssText = `width:calc((100% - 8px)/2);transform:translateX(${mode === 'remind' ? 0 : 100}%)`;
        const b = $('#aBody', rec.el);
        b.innerHTML = mode === 'remind'
          ? `<textarea class="inp" id="aT" rows="3" maxlength="300" placeholder="напомни завтра в 6 созвон" aria-label="Что напомнить">${esc(preset || '')}</textarea><div class="prev" id="aPrev"></div><button class="btn" style="margin-top:16px" data-go data-mb>Запомнить</button>`
          : `<input class="inp" id="aT" maxlength="200" placeholder="Что нужно сделать?" aria-label="Задача"><button class="btn" style="margin-top:16px" data-go>Добавить</button>`;
        const t = $('#aT', rec.el);
        if (mode === 'remind') { const upd = () => { const r = parseRemind(t.value); $('#aPrev', rec.el).innerHTML = !t.value.trim() ? '<span class="muted">Напиши, когда и что. Я сам разберу время.</span>' : r.when ? `📅 <b>${esc(dayWord(r.when))}, ${hm(r.when)}</b><br><span class="muted">${esc(r.text || '(без текста)')}</span>` : '<span class="muted">Времени не вижу. Завтра в 9 подойдёт?</span>'; }; t.oninput = upd; upd(); }
        setTimeout(() => { try { t.focus({ preventScroll: true }); } catch (e) { /* ignore */ } }, 450);
      };
      rec.el.addEventListener('click', async e => {
        const k = e.target.closest('#aSeg button'); if (k) { mode = k.dataset.k; preset = ''; hap('select'); draw(); return; }
        if (!e.target.closest('[data-go]')) return;
        const text = $('#aT', rec.el).value.trim();
        if (!text) { hap('error'); toast('Напиши текст', true); return; }
        try {
          if (mode === 'remind') {
            const r = await api('POST', '/api/plans/remind', { text });
            rec.close(); celebrate(); toast(r && r.when ? `Напомню ${whenLabel(r.when)}` : 'Запомнил');
            if (r && r.when) { PS.sel = r.when.slice(0, 10); PS.week = mondayOf(pd(r.when)); }
          } else { await api('POST', '/api/tasks', { text }); rec.close(); hap('success'); toast('Задача добавлена'); }
          S.loaded.today = 0; if (S.tab === 'plans') VIEWS.plans.load(true); else S.loaded.plans = 0;
        } catch (er) { mood('wow', 2200); toast('Не получилось. Попробуем ещё?', true); hap('error'); }
      });
      draw();
    },
  });
  return s;
}

function busySheet() {
  let hours = 3;
  const s = openSheet({
    title: 'Режим «занят»',
    html: `<p class="muted" style="margin-bottom:16px">Отвечу в личках за тебя, пока ты занят.</p><div class="sec-t muted" style="margin-top:0">На сколько</div><div class="chips" id="bH" style="margin-bottom:16px">${[[1, '1 час'], [3, '3 часа'], [12, 'До завтра']].map(([h, l]) => `<button class="chip ${h === 3 ? 'on' : ''}" data-h="${h}">${l}</button>`).join('')}</div><div class="sec-t muted" style="margin-top:0">Что отвечать</div><textarea class="inp" id="bT" rows="3" maxlength="300" aria-label="Текст автоответа">Сейчас занят, отвечу позже.</textarea><button class="btn" style="margin-top:16px" data-go>Включить</button>`,
  });
  s.el.addEventListener('click', async e => {
    const c = e.target.closest('[data-h]'); if (c) { hours = +c.dataset.h; $$('#bH .chip', s.el).forEach(x => x.classList.toggle('on', x === c)); hap('select'); }
    if (e.target.closest('[data-go]')) {
      try { await api('POST', '/api/busy', { hours, text: $('#bT', s.el).value.trim() }); s.close(); hap('success'); toast('Режим включён'); VIEWS.plans.load(true); }
      catch (er) { toast('Не получилось', true); hap('error'); }
    }
  });
}

/* тариф */
const TIERS = [
  { id: 'free', name: 'Free', rub: 0, stars: 0, tag: 'Затянуть и показать пользу', f: ['Архив и удалённое, 30 дней', '30 запросов к Угу в день', '5 напоминаний, 20 заметок', 'Мини-апп: Сегодня и Архив'] },
  { id: 'lite', name: 'Lite', rub: 99, stars: 75, tag: 'Для себя, каждый день', f: ['Архив 6 месяцев', '150 запросов в день', '30 напоминаний, 200 заметок', 'Вечерний дайджест', 'Все разделы мини-аппа'] },
  { id: 'pro', name: 'Pro', rub: 299, stars: 230, hit: true, tag: 'Умный помощник', f: ['Архив без срока', 'Запросы без лимита*', 'Умные ответы и пересказ', 'Сводки по всем чатам', 'Голосовые заметки'] },
  { id: 'ultra', name: 'Ultra', rub: 790, stars: 600, tag: 'Агент, который пишет за тебя', f: ['Всё из Pro', 'Автоответ в твоём стиле', 'Черновики ответов', 'Утренний брифинг', 'До 3 аккаунтов'] },
];
const CMP = [
  ['Архив', '30 дн', '6 мес', 'без срока', 'без срока'], ['Запросы к Угу', '30 в день', '150 в день', 'безлимит*', 'безлимит*'], ['Ответы из интернета', '10 в день', '50 в день', 'безлимит*', 'безлимит*'],
  ['Напоминания и задачи', '5', '30', '200', 'безлимит'], ['Заметки', '20', '200', '2000', 'безлимит'], ['ГС в текст, мин в мес', '10', '60', '300', '1000'],
  ['Что на фото', '5 в день', '30 в день', 'безлимит*', 'безлимит*'], ['Фото-эффекты', '5 в день', '30 в день', 'безлимит*', 'безлимит*'], ['Сводки по чатам', '7 дней', '30 дней', 'все чаты', 'все чаты'],
  ['Дайджест', 'нет', 'вечерний', 'вечерний', 'вечер + утро'], ['Режим «занят»', 'нет', 'текст', 'текст + расписание', 'в твоём стиле'], ['Выгрузка переписки', 'нет', '1 в мес', 'безлимит', 'безлимит'],
  ['Умные ответы', 'нет', 'нет', '300 в мес', 'безлимит*'], ['Агент: черновики и автоответ', 'нет', 'нет', 'нет', 'да'], ['Аккаунтов', '1', '1', '1', 'до 3'],
];
const price = (t, per) => { const k = per === 'year' ? 12 * .8 : 1; return { rub: Math.round(t.rub * k), stars: Math.round(t.stars * k) }; };
function tariffSheet(pre) {
  if (pre) S.tier = pre;
  const cur = S.me ? S.me.tier : 'free';
  const draw = rec => {
    const per = S.period, sel = TIERS.find(t => t.id === S.tier);
    $('.sheet-body', rec.el).innerHTML = `<div class="state" style="padding:0 0 8px"><div class="m" data-m="love" style="width:104px;height:104px"></div><p class="muted">Выбери, как мне помогать тебе. Новичку 3 дня Lite бесплатно, по ссылке друга 7.</p></div>
      <div class="seg" style="margin-bottom:16px"><i style="width:calc((100% - 8px)/2);transform:translateX(${per === 'year' ? 100 : 0}%)"></i><button class="${per === 'month' ? 'on' : ''}" data-p="month">Месяц</button><button class="${per === 'year' ? 'on' : ''}" data-p="year">Год -20%</button></div>
      ${TIERS.map(t => { const p = price(t, per); return `<button class="tier ${t.id === S.tier ? 'sel' : ''} ${t.hit ? 'hit-t' : ''}" data-t="${t.id}"><div class="nm">${t.name}${t.hit ? '<span class="now-b hit-b">хит</span>' : ''}${t.id === cur ? '<span class="now-b">сейчас у тебя</span>' : ''}</div><div class="muted t2">${t.tag}</div>
        <div class="pr">${t.rub ? `${p.rub} ₽` : '0 ₽'} <small>${t.rub ? `/ ${p.stars} ⭐ ${per === 'year' ? 'в год' : 'в мес'}` : ''}</small></div><ul>${t.f.map(x => `<li>${x}</li>`).join('')}</ul></button>`; }).join('')}
      <div style="margin:16px 0 8px"><button class="btn" data-buy data-mb ${sel.id === 'free' || sel.id === cur ? 'disabled' : ''}>${sel.id === cur ? 'Сейчас у тебя' : sel.id === 'free' ? 'Бесплатный тариф' : `Оплатить ⭐ ${price(sel, per).stars}`}</button></div>
      <details><summary>Сравнить все тарифы</summary><div class="cmp"><table><thead><tr><th></th>${TIERS.map(t => `<th>${t.name}</th>`).join('')}</tr></thead><tbody>${CMP.map(r => `<tr><td>${r[0]}</td>${r.slice(1).map(x => `<td>${x}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="note-foot muted" style="margin-top:8px">* с честным использованием: защита от ботов и перепродажи.</p></details>
      ${cur !== 'free' ? '<p style="text-align:center;margin-top:16px"><button class="link muted" data-cancel>Отменить подписку</button></p>' : ''}`;
    hydrate(rec.el); $$('.rise', rec.el).forEach((n, i) => n.style.setProperty('--i', i));
    const canBuy = sel.id !== 'free' && sel.id !== cur;
    if (canBuy) setMain(`Оплатить ⭐ ${price(sel, per).stars}`, () => buy('stars')); else hideMain();
  };
  const buy = async method => {
    const sel = S.tier;
    try {
      hap('medium');
      const r = await api('POST', '/api/tariff/buy', { tier: sel, period: S.period, ...(method === 'card' ? { method: 'card' } : {}) });
      if (method === 'card') { openLink(r.pay_url || r.url || r.invoice_link); return; }
      const link = r.invoice_link;
      if (TG && TG.openInvoice && IN_TG) TG.openInvoice(link, st => {
        if (st === 'paid') { S.me.tier = sel; setUser(); rec.close(); celebrate(); toast(`Теперь ты на ${TIERS.find(t => t.id === sel).name}`); }
        else if (st === 'failed') { toast('Оплата не прошла', true); mood('sad', 2500); }
      });
      else { S.me.tier = sel; setUser(); rec.close(); celebrate(); toast(`Демо: теперь ты на ${TIERS.find(t => t.id === sel).name}`); }
    } catch (e) { toast('Не получилось открыть оплату', true); mood('wow', 2200); hap('error'); }
  };
  const rec = openSheet({
    title: 'Сделай Угу умнее', html: '', onClose: hideMain,
    mount(r) {
      draw(r);
      r.el.addEventListener('click', e => {
        const p = e.target.closest('[data-p]'), t = e.target.closest('[data-t]');
        if (p) { S.period = p.dataset.p; hap('select'); const o = r.el.querySelector('.sheet').scrollTop; draw(r); r.el.querySelector('.sheet').scrollTop = o; }
        else if (t) { S.tier = t.dataset.t; hap('select'); const o = r.el.querySelector('.sheet').scrollTop; draw(r); r.el.querySelector('.sheet').scrollTop = o; }
        else if (e.target.closest('[data-buy]')) buy('stars');
        else if (e.target.closest('[data-card]')) buy('card');
        else if (e.target.closest('[data-cancel]')) { if (TG && TG.openTelegramLink && IN_TG) TG.openTelegramLink('https://t.me/ugu_ai'); else toast('Подписка отменяется в настройках Telegram'); }
      });
    },
  });
}

/* партнёрка */
function loadScript(src) { return new Promise((ok, no) => { const s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = no; document.head.appendChild(s); }); }
function partnerSheet() {
  const s = openSheet({ title: 'Партнёрка', html: skRows(1, 90) + skRows(2, 60) });
  const body = s.body;
  const run = async () => {
    try {
      const p = await api('GET', '/api/partner');
      const st = p.stats || {}, lv = p.level || {}, left = Math.max(0, (lv.next_target || 0) - (lv.paid || 0)), pct = lv.next_target ? Math.min(100, (lv.paid || 0) / lv.next_target * 100) : 100;
      body.innerHTML = `<div class="stack">
        <div class="card rise" style="text-align:center"><div class="muted t2">Получено бонусом</div><div class="big-n">🎁 ${st.bonus_days || 0} ${plural(st.bonus_days || 0, 'день', 'дня', 'дней')}</div><p class="t2 muted" style="margin-top:8px">Друг по ссылке получает 7 дней Lite. Оплатил: тебе +7 дней тарифа. 10 оплативших: Pro навсегда, 50: Ultra.</p></div>
        <div class="card rise"><div class="t2 muted" style="margin-bottom:8px">Моя ссылка</div><div class="linkbox"><span class="grow">${esc(p.link)}</span></div><div class="row" style="margin-top:12px"><button class="btn grow" data-share>Поделиться</button><button class="btn soft sm" data-copy>Копировать</button></div><div id="qr" style="margin-top:16px"></div></div>
        <div class="card rise"><h2>Воронка</h2><div class="funnel"><div><b>${st.clicks || 0}</b><span class="muted">переходов</span></div><div class="ar">›</div><div><b>${st.connected || 0}</b><span class="muted">подключили</span></div><div class="ar">›</div><div><b>${st.paid || 0}</b><span class="muted">оплатили</span></div></div></div>
        ${lv.next_target ? `<div class="card rise"><h2>Уровень</h2><div class="bar"><i id="lvBar"></i></div><p class="t2" style="margin-top:8px"><b>${left > 0 ? `Ещё ${left} ${plural(left, 'оплата', 'оплаты', 'оплат')}` : 'Уровень открыт'}</b> до «${esc(lv.next_reward)}». Сейчас ${lv.paid || 0} из ${lv.next_target}.</p></div>` : ''}
        <div class="card rise"><h2>История начислений</h2>${(p.history || []).length ? p.history.map(h => `<div class="item"><div class="av" style="background:${colorOf(h.name)}">${esc(initial(h.name))}</div><div class="grow"><div class="t1">${esc(h.name)}</div><div class="t2 muted">${esc(dayChip(h.date))}</div></div><b style="color:var(--ok)">+${h.days} дн</b></div>`).join('') : '<p class="muted">Начислений пока нет.</p>'}</div></div>`;
      $$('.rise', body).forEach((n, i) => n.style.setProperty('--i', i));
      setTimeout(() => { const b = $('#lvBar', body); if (b) b.style.width = pct + '%'; }, 300);
      body.onclick = e => {
        if (e.target.closest('[data-copy]')) { copy(p.link); hap('success'); toast('Ссылка скопирована'); }
        if (e.target.closest('[data-share]')) {
          hap('medium'); const u = 'https://t.me/share/url?url=' + encodeURIComponent(p.link) + '&text=' + encodeURIComponent('Угу помнит всё, даже удалённое');
          if (IN_TG && TG.openTelegramLink) TG.openTelegramLink(u); else if (navigator.share) navigator.share({ url: p.link }).catch(() => {}); else { copy(p.link); toast('Ссылка скопирована'); }
        }
        if (e.target.closest('[data-out]')) toast('Stars выводятся через Telegram в профиле бота');
      };
      const qr = $('#qr', body);
      try {
        if (!window.QRCode) await loadScript('https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js');
        new window.QRCode(qr, { text: p.link, width: 176, height: 176, colorDark: '#1B1630', colorLight: '#ffffff' });
      } catch (e) { qr.remove(); }
    } catch (e) { fail(body, run); }
  };
  run();
}

/* профиль */
function profileSheet() {
  const s = openSheet({ title: 'Профиль', html: skRows(1, 80) + skRows(3, 48) });
  const body = s.body;
  const run = async () => {
    try {
      const me = await api('GET', '/api/me'); S.me = me; setUser();
      const st = me.settings || {}, pref = localStorage.ugu_theme || 'system';
      const SET = [['notify_deleted', 'Удалённые сообщения', 'Пришлю в личку'], ['notify_edited', 'Изменённые сообщения', 'Покажу было и стало'], ['digest', 'Вечерний дайджест', 'Коротко о дне'], ['voice_auto', 'ГС в текст', 'Расшифровывать сам']];
      body.innerHTML = `<div class="stack"><div class="card row rise"><div class="avatar" style="width:56px;height:56px;font-size:22px">${esc(initial(me.user.name))}</div><div class="grow"><div class="t1" style="font-size:18px">${esc(me.user.name)}</div><div class="t2 muted">id ${esc(me.user.id)}</div></div><span class="badge">${esc(me.tier)}</span></div>
        <div class="card rise"><h2>Лимиты на сегодня</h2>${(me.limits || []).map(l => { const pc = l.max ? Math.min(100, l.used / l.max * 100) : 0; return `<div style="margin-bottom:12px"><div class="row t2"><span class="grow">${esc(l.name)}</span><b>${l.used}${l.max ? ` / ${l.max}` : ' · безлимит'}</b></div><div class="bar ${pc > 85 ? 'warn' : ''}" style="margin-top:6px"><i style="width:${pc}%"></i></div></div>`; }).join('')}<div class="row wrap"><button class="btn sm" data-tariff>Тариф</button><button class="btn soft sm" data-partner>Партнёрка</button></div></div>
        <div class="card rise" style="padding:4px 16px"><h2 style="margin:12px 0 0">Уведомления</h2>${SET.map(([k, l, d]) => `<button class="set" data-set="${k}"><div class="grow"><div class="t1">${l}</div><div class="t2 muted">${d}</div></div><span class="sw ${st[k] ? 'on' : ''}"></span></button>`).join('')}</div>
        <div class="card rise"><h2>Тема</h2><div class="seg"><i style="width:calc((100% - 8px)/3);transform:translateX(${['system', 'light', 'dark'].indexOf(pref) * 100}%)"></i>${[['system', 'Как в Telegram'], ['light', 'Светлая'], ['dark', 'Тёмная']].map(([k, l]) => `<button class="${pref === k ? 'on' : ''}" data-th="${k}" style="font-size:13px">${l}</button>`).join('')}</div></div>
        <div class="card rise" style="padding:4px 16px"><button class="set" data-onb><span>👻</span><span class="grow">Как подключить Угу</span><span class="muted">›</span></button><button class="set" data-wipe style="color:var(--del)"><span>🗑</span><span class="grow">Удалить мои данные</span></button></div></div>`;
      $$('.rise', body).forEach((n, i) => n.style.setProperty('--i', i));
      body.onclick = async e => {
        const set = e.target.closest('[data-set]'), th = e.target.closest('[data-th]');
        if (set) {
          const k = set.dataset.set, prev = me.settings[k]; me.settings[k] = !prev;
          $('.sw', set).classList.toggle('on', me.settings[k]); hap('select');
          try { await api('PUT', '/api/settings', me.settings); } catch (er) { me.settings[k] = prev; $('.sw', set).classList.toggle('on', prev); toast('Не сохранилось', true); hap('error'); }
        }
        if (th) { localStorage.ugu_theme = th.dataset.th; applyTheme(); hap('select'); $$('[data-th]', body).forEach(b => b.classList.toggle('on', b === th)); $('.seg i', body).style.transform = `translateX(${['system', 'light', 'dark'].indexOf(th.dataset.th) * 100}%)`; }
        if (e.target.closest('[data-tariff]')) { s.close(); setTimeout(() => tariffSheet(), 300); }
        if (e.target.closest('[data-partner]')) { s.close(); setTimeout(partnerSheet, 300); }
        if (e.target.closest('[data-onb]')) { s.close(); setTimeout(() => showOnb(3), 300); }
        if (e.target.closest('[data-wipe]')) confirmSheet({ title: 'Удалить все данные?', text: 'Архив, заметки и планы сотрутся насовсем. Вернуть не получится.', ok: 'Да, удалить', danger: true, fn: async () => { try { await api('DELETE', '/api/me/data'); mood('sad', 3000); toast('Всё удалил'); S.loaded = {}; s.close(); go('today', { force: true }); } catch (er) { toast('Не получилось удалить', true); hap('error'); } } });
      };
    } catch (e) { fail(body, run); }
  };
  run();
}

/* ---------- онбординг ---------- */
const SLIDES = [
  { m: 'hi', t: 'Сохраняю всё, даже удалённое', p: 'Ничего не потеряешь. Удалённое и изменённое придёт тебе в личку.' },
  { m: 'alarm', t: 'Напоминаю и веду дела', p: 'Скажи «напомни завтра в 6 созвон», и я не забуду.' },
  { m: 'find', t: 'Зови меня угубот в любой переписке', p: 'Напиши «угубот, что у меня на неделе», и я отвечу.' },
  { m: 'see', t: 'Подключи меня', steps: ['Открой Настройки Telegram', 'Выбери «Telegram для бизнеса»', 'Затем «Чат-боты» и добавь @ugu_ai', 'Включи «Отвечать на сообщения» и «Удаление сообщений»'] },
  { m: 'ok', t: 'Готово!', p: 'Попробуй написать в любой переписке: «угубот, что у меня на неделе».' },
];
function showOnb(start = 0) {
  const o = $('#onb'); let i = start;
  o.classList.add('on'); document.body.classList.add('lock');
  o.innerHTML = `<div class="onb-in"><div class="onb-slides">${SLIDES.map((s, k) => `<div class="onb-s" data-k="${k}"><div class="m" data-m=""></div><h2>${s.t}</h2>${s.p ? `<p class="muted">${s.p}</p>` : ''}${s.steps ? `<ol class="steps">${s.steps.map(x => `<li>${x}</li>`).join('')}</ol>` : ''}</div>`).join('')}</div>
    <div class="dotsrow">${SLIDES.map(() => '<i></i>').join('')}</div><div class="stack"><button class="btn" data-next data-mb></button><div class="row" style="justify-content:center"><button class="link muted" data-skip>Пропустить</button></div></div></div>`;
  const draw = () => {
    const last = i === SLIDES.length - 1;
    $$('.onb-s', o).forEach((n, k) => { n.classList.toggle('on', k === i); n.classList.toggle('past', k < i); if (k === i) { const m = $('.m', n); mascot(m, SLIDES[k].m, SLIDES[k].m !== 'ok'); } });
    $$('.dotsrow i', o).forEach((d, k) => d.classList.toggle('on', k === i));
    const btn = $('[data-next]', o);
    btn.textContent = i === 3 ? 'Открыть настройки' : last ? 'Начать' : 'Дальше';
    $('[data-skip]', o).textContent = i === 3 ? 'Подключу позже' : 'Пропустить';
    $('[data-skip]', o).style.visibility = last ? 'hidden' : '';
    if (last) setTimeout(() => { const r = $('.onb-s.on .m', o).getBoundingClientRect(); burst(r.left + r.width / 2, r.top + r.height / 2, 22); hap('success'); }, 500);
    setMain(btn.textContent, next);
  };
  const finish = () => { localStorage.ugu_onb = '1'; o.classList.remove('on'); o.innerHTML = ''; document.body.classList.remove('lock'); hideMain(); mood('hi', 2400); };
  const next = () => {
    hap('light');
    if (i === 3) { if (IN_TG && TG.openTelegramLink) { try { TG.openTelegramLink('tg://settings'); } catch (e) { /* ignore */ } } else toast('Настройки Telegram, раздел «Telegram для бизнеса»'); }
    if (i >= SLIDES.length - 1) return finish();
    i++; draw();
  };
  o.onclick = e => {
    if (e.target.closest('[data-next]')) next();
    if (e.target.closest('[data-skip]')) { if (i === 3) { i = 4; draw(); } else if (i < 3) { i = 3; draw(); } }
  };
  let x0 = null;
  o.ontouchstart = e => { x0 = e.touches[0].clientX; };
  o.ontouchend = e => { if (x0 === null) return; const dx = e.changedTouches[0].clientX - x0; x0 = null; if (dx < -60 && i < SLIDES.length - 1) { i++; draw(); } if (dx > 60 && i > 0) { i--; draw(); } };
  draw();
}

/* ---------- обработка кликов ---------- */
const ACT = {
  tab: t => go(t.dataset.id),
  poke: () => { mood('love', 1800); hap('light'); const m = $('#mascot').getBoundingClientRect(); burst(m.left + m.width / 2, m.top + m.height / 2, 8); },
  profile: () => profileSheet(),
  tariff: () => tariffSheet(),
  close: () => back(),
  retry: t => { const s = t.closest('.state'); if (s && s._retry) s._retry(); },
  onb: () => showOnb(3),
  'ask-go': async () => {
    const inp = $('#askIn'), q = inp.value.trim(); if (!q) { inp.focus(); return; }
    inp.value = ''; hap('light');
    const out = $('#askOut'); out.innerHTML = `<div class="card rise" style="margin-top:16px"><div class="muted t2" style="margin-bottom:4px">${esc(q)}</div>${typingHTML}</div>`;
    await runAsk(out.firstChild, q, '', 'today');
  },
  choice: async t => {
    const q = t.dataset.q, kind = t.dataset.kind;
    if (t.dataset.ctx === 'log') { pushLog(q, kind, t.textContent); return; }
    const card = $('#askOut .card'); if (card) { card.innerHTML = `<div class="muted t2" style="margin-bottom:4px">${esc(t.textContent)}</div>${typingHTML}`; await runAsk(card, q, kind, 'today'); }
  },
  done: async t => {
    const id = t.dataset.id; t.classList.add('on'); hap('success');
    try {
      await api('POST', `/api/plans/${encodeURIComponent(id)}/done`);
      celebrate(t);
      const row = t.closest('.item'); if (row && S.tab === 'today') { row.classList.add('gone'); setTimeout(() => { S.loaded.today = 0; VIEWS.today.load(); }, 650); }
      else if (S.tab === 'plans') setTimeout(() => VIEWS.plans.load(true), 500);
      S.loaded.plans = S.tab === 'plans' ? Date.now() : 0;
    } catch (e) { t.classList.remove('on'); toast('Не получилось отметить', true); mood('wow', 2000); hap('error'); }
  },
  'open-chat': t => openChat(t.dataset.id, t.dataset.name, t.dataset.day),
  counter: t => { CS.q = ''; CS.only = t.dataset.k === 'deleted' ? 'deleted' : t.dataset.k === 'voice' ? 'media' : ''; S.loaded.chats = 0; go('chats', { force: true }); },
  chfilter: t => { CS.only = t.dataset.k; hap('select'); VIEWS.chats.load(); },
  'pick-day': t => { hap('select'); pickDay(t.dataset.day); },
  'chat-ai': t => {
    const c = CS.cur; if (!c) return; const k = t.dataset.k;
    const [q, kind] = { 'Кратко': ['кратко за неделю', 'summary'], 'Договорённости': ['договорённости за месяц', 'promises'], 'Статистика': ['статистика чата', 'stats'] }[k];
    const s = openSheet({ title: k, html: `<div class="card" id="caBox">${typingHTML}</div>` });
    const box = $('#caBox', s.el);
    (DEMO ? askUgu(`${q} с ${c.name}`, '') : api('POST', '/api/ask', { q, kind, chat: +c.id }))
      .then(r => { box.innerHTML = answerHTML(r, q, 'sheet'); })
      .catch(() => { box.innerHTML = '<p class="muted">Не получилось, попробуй ещё раз.</p>'; });
  },
  'zoom-media': t => { if (t.src) zoom(t.src); },
  zoom: t => zoom(t.dataset.full || t.src, t.dataset.q),
  week: t => { PS.week = new Date(PS.week.getTime() + 7 * 864e5 * +t.dataset.d); PS.week.setHours(0, 0, 0, 0); PS.sel = ymd(PS.week); hap('select'); VIEWS.plans.load(); },
  pday: t => { PS.sel = t.dataset.d; hap('select'); VIEWS.plans.drawWeek(); VIEWS.plans.drawDay(); },
  pmore: t => { hap('light'); t.closest('.pitem').classList.toggle('open'); },
  snooze: async t => {
    const p = PS.items.find(x => x.id === t.dataset.id); if (!p) return;
    try { await api('POST', `/api/plans/${encodeURIComponent(p.id)}/snooze`, { minutes: snoozeMinutes(p, t.dataset.k) }); hap('success'); toast('Перенёс'); VIEWS.plans.load(true); }
    catch (e) { toast('Не получилось перенести', true); hap('error'); }
  },
  pdel: t => confirmSheet({ title: 'Удалить напоминание?', text: 'Оно пропадёт насовсем.', ok: 'Удалить', danger: true, fn: async () => { try { await api('DELETE', `/api/plans/${encodeURIComponent(t.dataset.id)}`); hap('success'); toast('Удалил'); VIEWS.plans.load(true); } catch (e) { toast('Не получилось удалить', true); hap('error'); } } }),
  ttoggle: async t => {
    const task = PS.items.find(x => x.id === t.dataset.id); if (!task) return;
    task.done = !task.done; t.classList.toggle('on', task.done); hap(task.done ? 'success' : 'select');
    if (task.done) { const r = $('.cb', t).getBoundingClientRect(); burst(r.left + 13, r.top + 13, 8); }
    try { await api('POST', `/api/tasks/${encodeURIComponent(task.id)}/toggle`); }
    catch (e) { task.done = !task.done; t.classList.toggle('on', task.done); toast('Не получилось', true); }
  },
  tadd: async () => {
    const i = $('#tIn'), text = i.value.trim(); if (!text) { i.focus(); return; }
    try { await api('POST', '/api/tasks', { text }); hap('success'); VIEWS.plans.load(true); } catch (e) { toast('Не получилось добавить', true); hap('error'); }
  },
  add: () => addSheet('remind'),
  busy: async () => {
    if (PS.busy) { try { await api('DELETE', '/api/busy'); hap('success'); toast('Режим выключен'); VIEWS.plans.load(true); } catch (e) { toast('Не получилось', true); } }
    else busySheet();
  },
  'note-new': () => noteSheet(),
  'note-open': t => noteSheet(t.dataset.id),
  useg: t => { hap('select'); VIEWS.ugu.seg(t.dataset.k); },
  sugg: t => { $('#uIn').value = t.dataset.q; ACT['u-go'](); },
  'u-go': () => { const i = $('#uIn'), q = i.value.trim(); if (!q) { i.focus(); return; } i.value = ''; pushLog(q); },
  'img-go': () => { const v = $('#iQ').value.trim(); if (!v) return; US.imgQ = v; hap('light'); VIEWS.ugu.img(); },
  'img-chip': t => { US.imgQ = t.dataset.q; hap('select'); VIEWS.ugu.img(); },
  'cam-act': t => { US.act = t.dataset.k; hap('select'); VIEWS.ugu.cam(); },
  'cam-go': async () => {
    if (!US.file) return;
    const out = $('#camOut'); out.innerHTML = `<div class="card">${typingHTML}</div>`;
    const fd = new FormData(); fd.append('file', US.file); fd.append('action', US.act); fd.append('text', ($('#camT') && $('#camT').value.trim()) || '');
    try {
      const r = await api('POST', '/api/photo', fd, { any: true });
      if (r.blob) { const u = URL.createObjectURL(r.blob); out.innerHTML = `<div class="card rise"><img src="${u}" alt="" style="width:100%;border-radius:14px;display:block" data-act="zoom" data-full="${u}"><a class="btn soft" style="margin-top:12px" href="${u}" download="ugu.jpg">Сохранить</a></div>`; celebrate(); out.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' }); }
      else { out.scrollIntoView({ block: 'center' }); out.innerHTML = `<div class="card rise"><div class="ans" style="white-space:pre-line">${clean(r.json.html)}</div></div>`; mood('ok', 2000); hap('success'); }
    } catch (e) { out.innerHTML = ''; fail(out, () => ACT['cam-go']()); }
  },
};
async function runAsk(box, q, kind, ctx) {
  try {
    const r = await askUgu(q, kind);
    const head = box.querySelector('.muted.t2');
    box.innerHTML = (head ? head.outerHTML : '') + answerHTML(r, q, ctx);
    const bad = /^\s*❓/.test(r.html); bad ? (mood('wow', 1800), hap('warning')) : (mood('ok', 1600), hap('success'));
    return r;
  } catch (e) { box.innerHTML = `<div class="ans">👻 Не получилось ответить. Попробуй ещё раз.</div>`; mood('wow', 2600); hap('error'); }
}
async function pushLog(q, kind, label) {
  US.log.push({ q: label || q }); saveLog();
  const log = $('#uLog');
  if (log) { const st = $('.state', log); if (st) st.remove(); log.insertAdjacentHTML('beforeend', `<div class="q rise">${esc(label || q)}</div><div class="a rise" id="uPend">${typingHTML}</div>`); $('#uPend').scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' }); }
  try {
    const r = await askUgu(q, kind);
    US.log.push({ q, r }); saveLog();
    const p = $('#uPend'); if (p) { p.removeAttribute('id'); p.classList.add('big'); p.innerHTML = answerHTML(r, q, 'log'); p.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' }); }
    /^\s*❓/.test(r.html) ? (mood('wow', 1800), hap('warning')) : (mood('ok', 1600), hap('success'));
  } catch (e) { const p = $('#uPend'); if (p) { p.removeAttribute('id'); p.textContent = '👻 Не получилось ответить. Попробуй ещё раз.'; } mood('wow', 2600); hap('error'); }
}
function saveLog() { try { localStorage.ugu_log = JSON.stringify(US.log.slice(-20).map(m => m.r ? { q: m.q, r: { html: m.r.html, choices: m.r.choices, images: (m.r.images || []).slice(0, 6).map(i => ({ url: i.url.startsWith('data:') ? i.thumb || i.url : i.url, thumb: i.thumb })) } } : m)); } catch (e) { /* квота */ } }

document.addEventListener('click', e => {
  const a = e.target.closest('a[href]');
  if (a && a.closest('.ans')) { e.preventDefault(); const h = a.getAttribute('href'); if (/^tg:|t\.me/.test(h) && IN_TG && TG.openTelegramLink) TG.openTelegramLink(h); else openLink(h); return; }
  const t = e.target.closest('[data-act]'); if (!t) return;
  const f = ACT[t.dataset.act]; if (f) { if (!['tab', 'done', 'ttoggle'].includes(t.dataset.act)) hap('light'); f(t, e); }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') back();
  if (e.key === 'Enter' && !e.shiftKey && e.target.dataset && e.target.dataset.enter) { e.preventDefault(); ACT[e.target.dataset.enter](e.target); }
});
document.addEventListener('input', debounce(e => {
  const k = e.target.dataset && e.target.dataset.input;
  if (k === 'chats') { CS.q = e.target.value.trim(); const b = $('#chList'); if (b) b.dataset.stale = '1'; VIEWS.chats.load(); }
  if (k === 'notes') { NS.q = e.target.value.trim(); VIEWS.notes.load(); }
}, 320));
document.addEventListener('change', e => {
  if (e.target.id === 'camF' && e.target.files[0]) {
    US.file = e.target.files[0]; if (US.fileUrl) URL.revokeObjectURL(US.fileUrl); US.fileUrl = URL.createObjectURL(US.file); VIEWS.ugu.cam(); hap('success');
  }
});
/* долгий тап по сообщению */
(() => {
  let timer = 0, sx = 0, sy = 0, bub = null;
  const clear = () => { clearTimeout(timer); if (bub) bub.classList.remove('pressing'); bub = null; };
  document.addEventListener('pointerdown', e => {
    const b = e.target.closest('.bub'); if (!b || e.target.closest('img')) return;
    bub = b; sx = e.clientX; sy = e.clientY; b.classList.add('pressing');
    timer = setTimeout(() => { const id = b.dataset.mid; clear(); hap('medium'); msgActions(id); }, 450);
  });
  document.addEventListener('pointermove', e => { if (bub && Math.hypot(e.clientX - sx, e.clientY - sy) > 8) clear(); });
  ['pointerup', 'pointercancel', 'scroll'].forEach(n => document.addEventListener(n, clear, true));
  document.addEventListener('contextmenu', e => { const b = e.target.closest('.bub'); if (b) { e.preventDefault(); msgActions(b.dataset.mid); } });
})();
/* свайп по напоминанию: влево открывает действия */
(() => {
  let x0 = 0, y0 = 0, it = null;
  document.addEventListener('touchstart', e => { it = e.target.closest('.pitem'); if (it) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; } }, { passive: true });
  document.addEventListener('touchend', e => {
    if (!it) return; const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    if (Math.abs(dy) < 30 && Math.abs(dx) > 50 && it.querySelector('.acts')) { it.classList.toggle('open', dx < 0); hap('select'); }
    it = null;
  }, { passive: true });
})();
/* потянуть для обновления */
(() => {
  const p = $('#ptr'); let y0 = null, dy = 0, busy = false;
  document.addEventListener('touchstart', e => { y0 = (!stack.length && window.scrollY <= 0 && !e.target.closest('input,textarea,.cmp,.chips,.dayrow')) ? e.touches[0].clientY : null; dy = 0; }, { passive: true });
  document.addEventListener('touchmove', e => {
    if (y0 === null || busy) return; dy = e.touches[0].clientY - y0;
    if (dy > 0) { const k = Math.min(dy * .5, 80); p.style.opacity = Math.min(1, k / 50); p.style.transform = `translateY(${k - 40}px) rotate(${k * 4}deg)`; }
  }, { passive: true });
  document.addEventListener('touchend', async () => {
    if (y0 === null || busy) return; y0 = null;
    if (dy > 140) {
      busy = true; p.classList.add('spin'); p.style.transform = 'translateY(30px)'; hap('medium'); mood('think');
      S.loaded[S.tab] = Date.now(); try { await VIEWS[S.tab].load(true); } catch (e) { /* ignore */ }
      await wait(600); mood('ghost'); busy = false; p.classList.remove('spin');
    }
    p.style.opacity = 0; p.style.transform = 'translateY(-60px)';
  }, { passive: true });
})();

/* ---------- старт ---------- */
async function boot() {
  try { if (TG) { TG.ready(); TG.expand(); if (TG.disableVerticalSwipes) TG.disableVerticalSwipes(); TG.BackButton && TG.BackButton.onClick(back); TG.onEvent('themeChanged', applyTheme); } } catch (e) { /* ignore */ }
  applyTheme(); renderTabs();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
  mood('ghost');
  $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.id === S.tab));
  setHeader();
  try { S.me = await api('GET', '/api/me'); setUser(); }
  catch (e) { return fail($('#v-today'), boot, 'Не удалось войти. Открой меня заново из Telegram.'); }
  S.loaded.today = Date.now(); VIEWS.today.load();
  if (!localStorage.ugu_onb || params.get('onb') === '1') showOnb(0);
}
window.__ugu = { go, tariffSheet, partnerSheet, profileSheet, addSheet, noteSheet, openChat, showOnb, busySheet, mood, US, S, ACT };
boot();
})();
