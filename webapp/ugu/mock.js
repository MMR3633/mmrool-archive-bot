/* Демо-данные: вся апка кликабельна в обычном браузере (?demo=1) */
(() => {
'use strict';
const pad = n => String(n).padStart(2, '0');
const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const iso = d => `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const at = (off, hm) => { const d = new Date(); d.setDate(d.getDate() + off); const [h, m] = hm.split(':'); d.setHours(+h, +m, 0, 0); return d; };
const inMin = n => new Date(Date.now() + n * 60000);
let seq = 100;
const wait = ms => new Promise(r => setTimeout(r, ms));

const tile = (seed, label, w = 400, h = 400) => {
  const hues = [[124, 92, 255], [255, 143, 177], [61, 107, 255], [52, 199, 89], [255, 159, 10], [182, 107, 255]];
  const a = hues[seed % hues.length], b = hues[(seed * 3 + 2) % hues.length];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="rgb(${a})"/><stop offset="1" stop-color="rgb(${b})"/></linearGradient></defs><rect width="100%" height="100%" fill="url(#g)"/><circle cx="${w * .75}" cy="${h * .25}" r="${h * .16}" fill="rgba(255,255,255,.28)"/><text x="50%" y="56%" font-size="${h * .34}" text-anchor="middle" dominant-baseline="middle">${label}</text></svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
};
const EMO = { 'котики': ['🐱', '😺', '🐈', '😸', '🐾', '😻'], 'мемы': ['😂', '🤡', '🗿', '💀', '🫠', '🤪'], 'аниме': ['🌸', '⚔️', '🍥', '🎌', '🌙', '✨'], 'природа': ['🌲', '🏔️', '🌊', '🌅', '🍃', '🌻'], 'еда': ['🍕', '🍣', '🍩', '🥐', '🍓', '🍜'] };
const emoFor = (q, i) => { const k = Object.keys(EMO).find(x => (q || '').toLowerCase().includes(x.slice(0, 4))) || 'котики'; return EMO[k][i % 6]; };

const S = {
  me: { user: { id: 184273, name: 'Расул' }, tier: 'lite', limits: [{ name: 'Запросы к Угу', used: 42, max: 150 }, { name: 'ГС в текст, мин', used: 34, max: 60 }, { name: 'Интернет', used: 18, max: 50 }], settings: { notify_deleted: true, notify_edited: true, digest: false, voice_auto: true } },
  chats: [
    { id: 'c1', name: 'Лера', last: 'Ок, до вечера 💜', ts: iso(at(0, '18:12')), deleted: 2 },
    { id: 'c2', name: 'Twixi', last: 'Фото с выставки', ts: iso(at(0, '16:40')), deleted: 0 },
    { id: 'c3', name: 'Захар', last: 'Скинь макет, как сможешь', ts: iso(at(0, '15:20')), deleted: 1 },
    { id: 'c4', name: 'Дизайн-команда', last: 'Марина: правки в пятницу', ts: iso(at(-1, '21:05')), deleted: 0 },
    { id: 'c5', name: 'Мама', last: 'Не забудь позвонить бабушке', ts: iso(at(-2, '10:30')), deleted: 0 },
    { id: 'c6', name: 'Самокат', last: 'Курьер уже рядом', ts: iso(at(-4, '19:50')), deleted: 0 },
  ],
  plans: [
    { id: 'p1', kind: 'remind', text: 'Утренняя зарядка', when: iso(at(0, '08:00')), chat: '', done: true },
    { id: 'p2', kind: 'remind', text: 'Созвон с Захаром', when: iso(inMin(50)), chat: 'Захар', done: false },
    { id: 'p3', kind: 'remind', text: 'Оплатить интернет', when: iso(inMin(260)), chat: '', done: false },
    { id: 'p4', kind: 'remind', text: 'Созвон по макету', when: iso(at(1, '06:00')), chat: 'Дизайн-команда', done: false },
    { id: 'p5', kind: 'remind', text: 'Купить цветы Лере', when: iso(at(2, '14:00')), chat: 'Лера', done: false },
    { id: 'p6', kind: 'remind', text: 'Отправить отчёт', when: iso(at(3, '11:30')), chat: '', done: false },
    { id: 'p7', kind: 'remind', text: 'Записаться к стоматологу', when: iso(at(5, '10:00')), chat: 'Мама', done: false },
    { id: 'b1', kind: 'birthday', text: 'День рождения Леры', date: ymd(at(3, '00:00')) },
    { id: 'b2', kind: 'birthday', text: 'День рождения Захара', date: ymd(at(10, '00:00')) },
    { id: 't1', kind: 'task', text: 'Отправить макет Захару', done: false },
    { id: 't2', kind: 'task', text: 'Заказать торт', done: false },
    { id: 't3', kind: 'task', text: 'Продлить домен', done: true },
  ],
  busy: null,
  notes: [
    { id: 'n1', title: 'Идеи для подарка Лере', body: 'Тёплый плед, билеты на концерт, набор для рисования. Спросить размер у Twixi.', color: 'pink', pinned: true, ts: iso(at(-1, '12:00')) },
    { id: 'n2', title: 'Пароль от wi-fi в студии', body: 'ugu-studio-2026', color: 'yellow', pinned: true, ts: iso(at(-3, '12:00')) },
    { id: 'n3', title: 'План на неделю', body: 'Пн: макеты\nВт: созвон\nСр: отчёт\nЧт: правки\nПт: релиз', color: 'violet', pinned: false, ts: iso(at(-2, '09:00')) },
    { id: 'n4', title: 'Купить', body: 'Молоко, хлеб, кофе, бананы', color: 'green', pinned: false, ts: iso(at(-1, '20:00')) },
    { id: 'n5', title: '', body: 'Договорились с Захаром: макет до пятницы, оплата после правок.', color: 'blue', pinned: false, ts: iso(at(0, '11:00')) },
    { id: 'n6', title: 'Мысли', body: 'Сделать короткий ролик про призрака, который всё помнит. Музыка спокойная, без слов.', color: 'none', pinned: false, ts: iso(at(-5, '23:10')) },
  ],
  partner: { link: 'https://t.me/ugu_ai?start=r_184273', stats: { clicks: 128, connected: 41, paid: 7, bonus_days: 49 }, level: { paid: 7, next_target: 10, next_reward: 'Pro навсегда' },
    history: [{ date: ymd(at(-1, '0:0')), name: 'Twixi', days: 7 }, { date: ymd(at(-3, '0:0')), name: 'Марина', days: 7 }, { date: ymd(at(-6, '0:0')), name: 'Артур', days: 7 }, { date: ymd(at(-9, '0:0')), name: 'Лейла', days: 7 }, { date: ymd(at(-14, '0:0')), name: 'Захар', days: 7 }] },
};

const MSG = {
  c1: {
    0: [
      { id: 'm1', from: 'them', name: 'Лера', text: 'Ты когда освободишься?', time: '17:40' },
      { id: 'm2', from: 'me', text: 'Часам к семи, надо доделать макет', time: '17:42' },
      { id: 'm3', from: 'them', name: 'Лера', text: 'Купи мне кофе, а то я не доживу', time: '17:50', deleted: '17:51' },
      { id: 'm4', from: 'them', name: 'Лера', text: 'Встретимся в 19:30 у входа', was: 'Встретимся в 19:00 у входа', time: '18:05' },
      { id: 'm5', from: 'them', name: 'Лера', text: '', time: '18:08', media: { kind: 'photo', id: 'ph1' } },
      { id: 'm6', from: 'them', name: 'Лера', text: 'Голосовое: «Захвати зонтик, обещали дождь, и не опаздывай, пожалуйста»', time: '18:10', media: { kind: 'voice', id: 'v1', dur: '0:14' } },
      { id: 'm7', from: 'me', text: 'Ок, до вечера 💜', time: '18:12' },
    ],
    1: [
      { id: 'm8', from: 'them', name: 'Лера', text: 'Сорри, вчера было не до того', time: '21:00', deleted: '21:03' },
      { id: 'm9', from: 'me', text: 'Всё нормально, увидимся завтра', time: '21:10' },
    ],
    3: [
      { id: 'm10', from: 'them', name: 'Лера', text: 'Какой у тебя размер перчаток?', time: '12:00' },
      { id: 'm11', from: 'me', text: 'M, но не надо ничего дарить', time: '12:04' },
    ],
  },
  c3: { 0: [{ id: 'z1', from: 'them', name: 'Захар', text: 'Привет, как макет?', time: '14:00' }, { id: 'z2', from: 'them', name: 'Захар', text: 'Не отправляй пока, поменял бриф', time: '14:30', deleted: '14:33' }, { id: 'z3', from: 'them', name: 'Захар', text: 'Скинь макет, как сможешь', time: '15:20' }] },
};
const DAYS = { c1: [0, 1, 3], c2: [0, 2], c3: [0, 1], c4: [1, 4], c5: [2], c6: [4] };
const msgsFor = (cid, off) => (MSG[cid] && MSG[cid][off]) || [
  { id: `g${cid}${off}a`, from: 'them', name: S.chats.find(c => c.id === cid).name, text: 'Привет! Ты тут?', time: '10:15' },
  { id: `g${cid}${off}b`, from: 'me', text: 'Да, на связи', time: '10:20' },
  { id: `g${cid}${off}c`, from: 'them', name: S.chats.find(c => c.id === cid).name, text: S.chats.find(c => c.id === cid).last, time: '10:31' },
];

const ASK = (q, kind) => {
  const s = (q || '').toLowerCase();
  if (s.includes('перескажи')) return { html: '✨ <b>Кратко</b>\nДоговорились встретиться в 19:30 у входа. Лера просила зонтик, ты обещал быть вовремя.' };
  if (s.includes('договорённост')) return { html: '🤝 <b>Договорённости</b>\n• Встреча в 19:30 у входа\n• Взять зонтик\n• Подарок обсудить в субботу' };
  if (s.includes('статистик')) return { html: '📈 <b>Статистика</b>\nСообщений: 148, удалено: 2, изменено: 1.\nЧаще всего пишете вечером.' };
  if (kind === 'weather' || s.includes('погод')) return { html: '🌐 <b>Завтра в Москве</b>: +3°, облачно, к вечеру дождь.\nЗонт возьми ☂️' };
  if (kind === 'rates' || s.includes('курс') || s.includes('доллар')) return { html: '🌐 <b>Доллар</b> 92,40 ₽\n<b>Евро</b> 101,15 ₽\n<i>Точные данные на сейчас.</i>' };
  if (s.includes('мем')) return { html: '🔎 Держи подборку.', images: [0, 1, 2, 3, 4, 5].map(i => ({ url: tile(i, emoFor('мемы', i), 800, 800), thumb: tile(i, emoFor('мемы', i)) })) };
  if (s.includes('недел')) {
    const items = S.plans.filter(p => p.kind === 'remind' && !p.done).slice(0, 5).map(p => `• ${p.when.slice(5, 10).split('-').reverse().join('.')} ${p.when.slice(11)}  ${p.text}`).join('\n');
    return { html: `📅 <b>На неделе</b>\n${items}\n\nСкоро день рождения у Леры 🎂` };
  }
  if (s.includes('кто тебя') || s.includes('создал')) return { html: '👻 Это тайна. Призраки о своём происхождении не рассказывают.' };
  if (kind === 'search') return { html: '🌐 Поискал в интернете: <a href="https://t.me/ugu_ai">ничего подозрительного</a>.' };
  return { html: '❓ Не понял, что именно нужно. Выбери вариант:', choices: [{ kind: 'weather', label: 'Погода' }, { kind: 'rates', label: 'Курс валют' }, { kind: 'search', label: 'Поискать в интернете' }] };
};

async function handle(method, path, body, opts) {
  await wait(260 + Math.random() * 260);
  if (window.UGU_FAIL && path.includes(window.UGU_FAIL)) throw new Error('demo fail');
  const u = new URL(path, 'http://x');
  const p = u.pathname, q = u.searchParams;
  const M = method.toUpperCase();
  let m;
  if (p === '/api/login') return { token: 'demo' };
  if (p === '/api/me' && M === 'GET') return JSON.parse(JSON.stringify(S.me));
  if (p === '/api/me/data' && M === 'DELETE') return { ok: true };
  if (p === '/api/settings' && M === 'PUT') { Object.assign(S.me.settings, body); return { ok: true }; }
  if (p === '/api/today') {
    return { counters: { deleted: 3, edited: 2, voice: 4 }, waiting: [{ chat_id: 'c3', name: 'Захар', hours: 4, text: 'Скинь макет, как сможешь' }, { chat_id: 'c2', name: 'Twixi', hours: 3, text: 'Фото с выставки' }],
      birthdays: [{ name: 'Лера', date: ymd(at(3, '0:0')), days: 3 }, { name: 'Захар', date: ymd(at(10, '0:0')), days: 10 }] };
  }
  if (p === '/api/chats') {
    const s = (q.get('q') || '').toLowerCase();
    return { items: S.chats.filter(c => !s || c.name.toLowerCase().includes(s)) };
  }
  if (p === '/api/days') {
    const cid = q.get('chat');
    return { items: (DAYS[cid] || [0]).map(off => { const ms = msgsFor(cid, off); return { day: ymd(at(-off, '0:0')), count: ms.length, deleted: ms.filter(x => x.deleted).length }; }) };
  }
  if (p === '/api/messages') {
    const cid = q.get('chat'), day = q.get('day');
    const off = Math.round((new Date(ymd(new Date()) + 'T00:00') - new Date(day + 'T00:00')) / 864e5);
    return { items: msgsFor(cid, off) };
  }
  if (p === '/api/search') {
    const s = (q.get('q') || '').toLowerCase();
    const onlyDel = q.get('deleted') === '1', onlyMedia = q.get('media') === '1';
    const out = [];
    S.chats.forEach(c => (DAYS[c.id] || [0]).forEach(off => msgsFor(c.id, off).forEach(x => out.push({ chat: c.id, chat_name: c.name, day: ymd(at(-off, '0:0')), id: x.id, text: x.text || (x.media ? '[медиа]' : ''), time: x.time, deleted: x.deleted || null, media: x.media || null }))));
    return { items: out.filter(x => (!s || x.text.toLowerCase().includes(s)) && (!onlyDel || x.deleted) && (!onlyMedia || x.media)).slice(0, 30) };
  }
  if (p === '/api/media') return { demo: true, label: q.get('id') };
  if (p === '/api/plans' && M === 'GET') {
    const from = q.get('from'), to = q.get('to');
    return { items: S.plans.filter(x => x.kind === 'task' || (x.kind === 'birthday' ? x.date >= from && x.date <= to : x.when.slice(0, 10) >= from && x.when.slice(0, 10) <= to)), busy: S.busy };
  }
  if (p === '/api/plans/remind' && M === 'POST') {
    const r = window.UguParse(body.text);
    const when = r.when || at(1, '09:00');
    const it = { id: 'p' + (++seq), kind: 'remind', text: r.text || body.text, when: iso(when), chat: '', done: false };
    S.plans.push(it); return it;
  }
  if ((m = p.match(/^\/api\/plans\/([^/]+)\/(snooze|done)$/)) && M === 'POST') {
    const it = S.plans.find(x => x.id === m[1]); if (!it) throw new Error('404');
    if (m[2] === 'done') it.done = true; else { const d = new Date(it.when); d.setMinutes(d.getMinutes() + (body.minutes || 60)); it.when = iso(d); }
    return it;
  }
  if ((m = p.match(/^\/api\/plans\/([^/]+)$/)) && M === 'DELETE') { S.plans = S.plans.filter(x => x.id !== m[1]); return { ok: true }; }
  if (p === '/api/tasks' && M === 'POST') { const it = { id: 't' + (++seq), kind: 'task', text: body.text, done: false }; S.plans.push(it); return it; }
  if ((m = p.match(/^\/api\/tasks\/([^/]+)\/toggle$/))) { const it = S.plans.find(x => x.id === m[1]); it.done = !it.done; return it; }
  if (p === '/api/busy') {
    if (M === 'POST') { S.busy = { until: iso(inMin((body.hours || 1) * 60)), text: body.text || 'Занят, отвечу позже' }; return S.busy; }
    S.busy = null; return { ok: true };
  }
  if (p === '/api/notes' && M === 'GET') {
    const s = (q.get('q') || '').toLowerCase();
    return { items: S.notes.filter(n => !s || (n.title + ' ' + n.body).toLowerCase().includes(s)) };
  }
  if (p === '/api/notes' && M === 'POST') { const n = { id: 'n' + (++seq), title: body.title || '', body: body.body || '', color: body.color || 'none', pinned: false, ts: iso(new Date()) }; S.notes.unshift(n); return n; }
  if ((m = p.match(/^\/api\/notes\/([^/]+)(\/pin)?$/))) {
    const n = S.notes.find(x => x.id === m[1]); if (!n) throw new Error('404');
    if (m[2]) { n.pinned = !n.pinned; return n; }
    if (M === 'PUT') { Object.assign(n, { title: body.title, body: body.body, color: body.color }); return n; }
    if (M === 'DELETE') { S.notes = S.notes.filter(x => x !== n); return { ok: true }; }
  }
  if (p === '/api/ask') return ASK(body.q, body.kind);
  if (p === '/api/images') {
    const s = q.get('q') || 'котики', off = +q.get('offset') || 0;
    const items = Array.from({ length: 18 }, (_, i) => ({ url: tile(off + i, emoFor(s, off + i), 900, 900), thumb: tile(off + i, emoFor(s, off + i), 240, 240) }));
    return { items, next: off < 54 ? off + 18 : null };
  }
  if (p === '/api/photo') {
    const act = body.get('action'), file = body.get('file');
    const txt = { describe: '🔎 На фото <b>призрак на фиолетовом фоне</b>. Милый, с румянцем и завитком на макушке.', product: '🌐 Похоже на <b>коллекционную фигурку</b>. Нашёл три магазина, пришлю ссылки в личку.' };
    if (txt[act]) return { json: { html: txt[act] } };
    return { blob: file };
  }
  if (p === '/api/tariff/buy') return { invoice_link: 'https://t.me/$demo_invoice', url: 'https://example.com/pay' };
  if (p === '/api/partner') return JSON.parse(JSON.stringify(S.partner));
  throw new Error('нет мока: ' + M + ' ' + p);
}

const mediaUrl = (chat, id) => {
  const k = { ph1: ['🌆', 11], v1: ['🎤', 3] }[id] || ['🖼️', 5];
  return tile(k[1], k[0], 480, 360);
};

window.UguMock = { handle, mediaUrl, tile, emoFor };
})();
