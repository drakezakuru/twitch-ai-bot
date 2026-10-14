'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const slugs = ['sub-goal','schedule','countdown','stream-session','subathon-timer','song-request','donation-challenge','top-donator','emoji-leaderboard','clip-moments','hype-meter','selected-chat','emoji-chat','soundboard'];
const runtime = fs.readFileSync(path.join(root, 'widgets/_shared/i18n.js'), 'utf8');
const escape = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const decode = s => s.replace(/&(?:amp|lt|gt|quot|#39);/g, c => ({'&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&#39;':"'"}[c]));

// Minimal offline DOM for the production widget scripts, with no layout or network.
class Element {
  constructor(tag = 'div', attrs = {}) { this.tagName = tag; this.attrs = attrs; this.children = []; this.style = {}; this.hidden = false; this._text = ''; }
  get className() { return this.attrs.class || ''; }
  set className(v) { this.attrs.class = v; }
  get classList() {
    const el = this;
    return {contains: c => el.className.split(/\s+/).includes(c),
      add(...cs) { el.className = [...new Set([...el.className.split(/\s+/).filter(Boolean), ...cs])].join(' '); },
      remove(...cs) { el.className = el.className.split(/\s+/).filter(c => !cs.includes(c)).join(' '); },
      toggle(c, force) { const on = force === undefined ? !this.contains(c) : force; this[on ? 'add' : 'remove'](c); return on; }};
  }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get innerHTML() { return escape(this._text) + this.children.map(c => c.outerHTML).join(''); }
  set innerHTML(v) { this._text = ''; this.children = []; parse(String(v), this); }
  get outerHTML() { return `<${this.tagName}${Object.entries(this.attrs).map(([k,v]) => ` ${k}="${escape(v)}"`).join('')}>${this.innerHTML}</${this.tagName}>`; }
  setAttribute(k,v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  appendChild(el) { this.children.push(el); el.parentNode = this; return el; }
  remove() { if(this.parentNode) this.parentNode.children = this.parentNode.children.filter(c => c !== this); }
  get firstElementChild() { return this.children[0]; }
  matches(selector) {
    if(selector.startsWith('[')) return Object.hasOwn(this.attrs, selector.slice(1,-1));
    if(selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if(selector.startsWith('#')) return this.attrs.id === selector.slice(1);
    return this.tagName === selector;
  }
  querySelectorAll(selector) { return this.children.flatMap(c => [...(c.matches(selector) ? [c] : []), ...c.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
function parse(html, parent) {
  const stack = [parent];
  for(const token of html.match(/<!--[\s\S]*?-->|<![^>]*>|<[^>]*>|[^<]+/g) || []) {
    if(token.startsWith('<!')) continue;
    if(token.startsWith('</')) { if(stack.length > 1) stack.pop(); continue; }
    if(!token.startsWith('<')) { stack.at(-1)._text += decode(token); continue; }
    const tag = token.match(/^<([\w-]+)/)?.[1];
    if(!tag) continue;
    const attrs = {};
    for(const m of token.slice(tag.length+1,-1).matchAll(/([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) attrs[m[1]] = decode(m[2] ?? m[3] ?? m[4] ?? '');
    const node = stack.at(-1).appendChild(new Element(tag,attrs));
    if(!['meta','link','img','br','input','hr'].includes(tag) && !token.endsWith('/>')) stack.push(node);
  }
}
async function flush() { for(let i=0;i<8;i++) await Promise.resolve(); }
async function boot(slug, lang, options = {}) {
  let html = fs.readFileSync(path.join(root,'widgets',slug,'index.html'),'utf8');
  html = html.replaceAll('__TITLE_OVERRIDE__', options.override || '').replaceAll('__TITLE__', options.title || '').replaceAll('__THEME__','neon').replaceAll('__PERIOD__','all').replaceAll('__TZ__','local');
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)].filter(m => !/\bsrc=/.test(m[1])).map(m => m[2]);
  const document = new Element('document');
  parse(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<style\b[^>]*>[\s\S]*?<\/style>/g,''), document);
  document.head = document.querySelector('head'); document.body = document.querySelector('body'); document.documentElement = document.querySelector('html');
  document.getElementById = id => document.querySelector('#'+id);
  document.createElement = tag => new Element(tag);
  const listeners = [];
  document.addEventListener = (event,fn) => { if(event === 'DOMContentLoaded') listeners.push(fn); };
  const intervals = [], sockets = [], messages = [], dictionaries = [];
  const search = options.search ?? `?ui_lang=${lang}&preview=${options.live ? '0' : '1'}${options.admin ? '&admin=1' : ''}`;
  const location = new URL('http://localhost/widget/'+slug+search);
  class WebSocket { constructor(url) { this.url=url; sockets.push(this); } close() { this.onclose?.(); } }
  class Audio { play() { return Promise.resolve(); } pause() {} }
  const context = vm.createContext({document,location,URL,URLSearchParams,console,navigator:{},WebSocket,Audio,
    widgetScopedUrl: url => url,
    setInterval: (fn,ms) => { intervals.push({fn,ms}); return intervals.length; },setTimeout: () => 1,clearTimeout(){},
    fetch: options.initialFetch || (() => new Promise(() => {})),
    ChatMessageCore: {loadSettings: async (slug,defaults) => defaults,loadEmotes: async () => ({}),apiBase: () => '',
      createList: () => ({add: message => messages.push(message)})}});
  context.window = context;
  vm.runInContext(runtime,context);
  const realAdd = context.WidgetI18n.add;
  context.WidgetI18n.add = translations => { dictionaries.push(translations); realAdd(translations); };
  for(const script of scripts) new vm.Script(script,{filename:slug+'/index.html'}).runInContext(context);
  await flush();
  return {context,document,intervals,sockets,messages,dictionaries,scripts,
    el: id => document.getElementById(id), t: (key,vars) => context.WidgetI18n.t(key,vars),
    run: code => vm.runInContext(code,context),
    domReady: () => listeners.forEach(fn => fn()),
    tick: ms => intervals.filter(i => i.ms===ms).forEach(i => i.fn()),
    respond(data, status=200) { context.fetch = async () => ({ok:status<400,status,json:async()=>data}); },
    fail() { context.fetch = async () => { throw new Error('PRIVATE /secret/token'); }; }};
}

for(const lang of ['ru','en','ua']) {
  for(const slug of slugs) test(`${slug}: ${lang} production preview, dictionary and late DOM readiness`, async () => {
    const h = await boot(slug,lang);
    assert.equal(h.context.WidgetI18n.lang,lang);
    assert.equal(h.document.documentElement.lang,lang==='ua'?'uk':lang);
    assert.equal(h.dictionaries.length,1);
    const dict = h.dictionaries[0];
    for(const locale of ['ru','en','ua']) {
      assert.deepEqual(Object.keys(dict[locale]),Object.keys(dict.ru));
      for(const [key,value] of Object.entries(dict[locale])) { assert.ok(key.startsWith(slug+'.')); assert.ok(value.trim()); }
    }
    const before = h.document.body.textContent;
    h.domReady();
    assert.equal(h.document.body.textContent,before,'late markers must not replace dynamic data');
    for(const node of h.document.querySelectorAll('[data-widget-i18n]')) assert.equal(node.textContent,h.t(node.getAttribute('data-widget-i18n')));
    assert.doesNotMatch(h.document.body.textContent,/Текст недоступен|__TITLE__|__TITLE_OVERRIDE__/);
  });

  test(`${lang}: localized timer states and user titles`, async () => {
    const h = await boot('countdown',lang);
    for(const state of ['paused','stopped','idle','error']) { h.run(`setState('${state}')`); assert.equal(h.el('state').textContent,h.t(state==='error'?'common.disconnected':'countdown.'+state)); }
    h.respond({title:'ПАУЗА <user>',state:'paused',remaining_sec:30}); await h.run('poll()');
    assert.equal(h.el('title').textContent,'ПАУЗА <user>');
    h.respond({},503); await h.run('poll()'); assert.equal(h.el('state').textContent,h.t('common.disconnected'));
    h.fail(); await h.run('poll()'); assert.equal(h.el('state').textContent,h.t('common.disconnected'));
    const sub = await boot('subathon-timer',lang);
    sub.run('running=false'); sub.tick(250); assert.equal(sub.document.querySelector('.hint').textContent,sub.t('subathon-timer.idle'));
    sub.respond({},503); await sub.run('load()'); sub.tick(250); assert.equal(sub.document.querySelector('.hint').textContent,sub.t('common.disconnected'));
    sub.fail(); await sub.run('load()'); sub.tick(250); assert.equal(sub.document.querySelector('.hint').textContent,sub.t('common.disconnected'));
    sub.respond({title:'SUBATHON user',running:true,remaining:4500}); await sub.run('load()'); sub.tick(250);
    assert.equal(sub.el('title').textContent,'SUBATHON user'); assert.equal(sub.document.querySelector('.hint').textContent,sub.t('subathon-timer.hint'));
  });

  test(`${lang}: stream-session live failure remains hidden`, async () => {
    const h = await boot('stream-session',lang,{live:true});
    h.fail(); await h.run('poll()'); h.tick(500);
    assert.equal(h.el('box').classList.contains('live'),false); assert.equal(h.el('box').classList.contains('state'),false);
    assert.equal(h.el('box').querySelector('.label').textContent,h.t('common.unavailable'));
    h.respond({is_live:true,start_time:new Date(Date.now()-60000).toISOString()}); await h.run('poll()'); h.tick(500);
    assert.equal(h.el('box').classList.contains('live'),true); assert.equal(h.el('box').querySelector('.label').textContent,h.t('stream-session.live'));
    h.respond({is_live:true,start_time:new Date().toISOString()},503); await h.run('poll()'); h.tick(500);
    assert.equal(h.el('box').classList.contains('live'),false); assert.equal(h.el('box').classList.contains('state'),false);
  });

  test(`${lang}: schedule fallback only when unconfigured, empty/error and escaped user data`, async () => {
    const h = await boot('schedule',lang);
    assert.equal(h.el('title').textContent,h.t('schedule.title'));
    const saved = await boot('schedule',lang,{title:'Расписание'}); assert.equal(saved.el('title').textContent,'Расписание');
    h.run('render([])'); assert.equal(h.el('content').textContent,h.t('schedule.empty'));
    h.run(`render([{title:'<user & title>',emoji:'<svg>',start_time:'00:00'}])`);
    assert.match(h.el('content').innerHTML,/&lt;user &amp; title&gt;/); assert.match(h.el('content').innerHTML,/&lt;svg&gt;/);
    assert.equal(h.el('content').querySelector('.badge').textContent,h.t('schedule.now'));
    h.respond([],503); await h.run('poll()'); assert.equal(h.el('content').textContent,h.t('common.unavailable_http',{status:503}));
    h.fail(); await h.run('poll()'); assert.equal(h.el('content').textContent,h.t('common.disconnected'));
  });

  test(`${lang}: sub-goal custom titles and named existing +/- controls`, async () => {
    const h = await boot('sub-goal',lang,{admin:true});
    h.run("apply({title:'Цель',current:1,target:25})"); assert.equal(h.el('title').textContent,'Цель');
    h.run('apply({current:1,target:25})'); assert.equal(h.el('title').textContent,h.t('sub-goal.fallback'));
    const buttons=h.document.querySelectorAll('button'); assert.equal(buttons.length,2);
    ['increment','decrement'].forEach((key,i)=> { assert.equal(buttons[i].getAttribute('aria-label'),h.t('sub-goal.'+key)); assert.equal(typeof buttons[i].onclick,'function'); });
    const override=await boot('sub-goal',lang,{override:'My goal'}); assert.equal(override.el('title').textContent,'My goal');
    h.respond({},403); await h.run('poll()'); assert.equal(h.el('count').textContent,h.t('common.unavailable_http',{status:403}));
    h.fail(); await h.run('poll()'); assert.equal(h.el('count').textContent,h.t('common.disconnected'));
  });

  test(`${lang}: song queue starts empty and recovers unchanged IDs after errors`, async () => {
    const h=await boot('song-request',lang,{live:true});
    assert.equal(h.el('queue').textContent,h.t('common.loading'));
    h.respond({visible:true,queue:[]}); await h.run('poll()'); assert.equal(h.el('queue').textContent,h.t('song-request.empty'));
    const data={visible:true,now_playing:{id:1,title:'<Track>',requested_by:'<Viewer & user>'},queue:[{id:2,title:'<Next>',requested_by:'Друг'}]};
    h.respond(data); await h.run('poll()'); assert.match(h.el('nowPlaying').innerHTML,/&lt;Track&gt;/); assert.match(h.el('nowPlaying').innerHTML,/&lt;Viewer &amp; user&gt;/);
    h.respond({},502); await h.run('poll()'); assert.equal(h.el('queue').textContent,h.t('common.unavailable_http',{status:502}));
    h.respond(data); await h.run('poll()'); assert.match(h.el('queue').innerHTML,/&lt;Next&gt;/);
    h.fail(); await h.run('poll()'); assert.equal(h.el('queue').textContent,h.t('common.disconnected'));
    h.respond(data); await h.run('poll()'); assert.match(h.el('nowPlaying').innerHTML,/&lt;Track&gt;/);
    h.domReady(); assert.match(h.el('queue').innerHTML,/&lt;Next&gt;/);
  });

  test(`${lang}: donation states preserve user title and reward`,async()=>{
    const h=await boot('donation-challenge',lang);
    h.run("apply({title:'Donation Challenge',reward_text:'<User reward>',progress_pct:30})");
    assert.equal(h.el('title').textContent,'Donation Challenge'); assert.equal(h.el('reward').textContent,'<User reward>');
    h.respond({active:false}); await h.run('poll()'); assert.equal(h.el('noChallenge').textContent,h.t('donation-challenge.empty'));
    h.respond({},500); await h.run('poll()'); assert.equal(h.el('noChallenge').textContent,h.t('common.unavailable_http',{status:500}));
    h.fail(); await h.run('poll()'); assert.equal(h.el('noChallenge').textContent,h.t('common.disconnected'));
  });

  for(const slug of ['top-donator','emoji-leaderboard','clip-moments']) test(`${slug}: ${lang} empty, HTTP failure and safe exceptions`,async()=>{
    const h=await boot(slug,lang);
    const load=slug==='top-donator'?'poll()':'load()';
    h.respond(slug==='top-donator'?{title:'User title',donors:[]}:slug==='emoji-leaderboard'?{items:[]}:[]); await h.run(load);
    assert.equal(h.el('list').textContent,h.t(slug+'.empty'));
    h.respond({},403); await h.run(load);
    assert.equal(h.el('list').textContent,h.t(slug==='clip-moments'?'clip-moments.unavailable_http':'common.unavailable_http',{status:403}));
    h.fail(); await h.run(load); assert.equal(h.el('list').textContent,h.t('common.disconnected'));
    assert.doesNotMatch(h.el('list').textContent,/PRIVATE|secret|token/);
    if(slug==='top-donator') h.run("render({title:'Топ донатеров',donors:[{username:'<Name & user>',total:1}]})");
    else if(slug==='emoji-leaderboard') h.run("render([{username:'<Name & user>',count:2}])");
    else {
      h.run("renderItems([{channel:'<Name & user>',rate:2,timestamp:'2026-01-01 12:00:00',clip_url:'Example'}])");
      assert.equal(h.run(`esc('" onmouseover="secret')`),'&quot; onmouseover=&quot;secret');
      assert.equal(h.el('list').querySelector('a').textContent,h.t('clip-moments.clip'));
      assert.equal(h.el('list').querySelector('.rate').textContent,h.t('clip-moments.rate',{rate:2}));
    }
    assert.match(h.el('list').innerHTML,/&lt;Name &amp; user&gt;/);
    h.domReady(); assert.match(h.el('list').innerHTML,/&lt;Name &amp; user&gt;/);
  });

  test(`${lang}: chat and soundboard connection states`,async()=>{
    const emoji=await boot('emoji-chat',lang,{live:true}); emoji.run('connect()');
    emoji.sockets.at(-1).onopen(); assert.equal(emoji.el('state').textContent,emoji.t('emoji-chat.empty'));
    emoji.sockets.at(-1).onclose(); assert.equal(emoji.el('state').textContent,emoji.t('common.disconnected'));
    assert.match(emoji.run("renderMessage('<User> 👋')"),/&lt;User&gt;/);
    const selected=await boot('selected-chat',lang,{live:true,initialFetch:async()=>({ok:false})});
    assert.equal(selected.el('chatState').textContent,selected.t('selected-chat.history_error'));
    const chat=selected.sockets[0]; chat.onopen();
    assert.equal(selected.el('chatState').textContent,selected.t('selected-chat.empty'));
    chat.onmessage({data:JSON.stringify({type:'chat',trusted:true,author:'<User>',message:'Original текст 👋'})});
    assert.equal(selected.messages[0].message,'Original текст 👋'); assert.equal(selected.el('chatState').hidden,true);
    chat.onclose(); assert.equal(selected.el('chatState').textContent,selected.t('common.disconnected'));
    const failed=await boot('selected-chat',lang,{live:true,initialFetch:async()=>{throw new Error('secret')}});
    assert.equal(failed.el('chatState').textContent,failed.t('selected-chat.history_error'));
    const preview=await boot('selected-chat',lang); assert.equal(preview.messages[0].message,preview.t('selected-chat.demo_people'));
    const sound=await boot('soundboard',lang,{live:true}); const ws=sound.sockets[0];
    ws.onopen(); assert.equal(sound.el('state').textContent,sound.t('soundboard.status',{text:sound.t('soundboard.ready')}));
    ws.onmessage({data:JSON.stringify({type:'soundboard',kind:'play',track_id:7})}); await flush();
    assert.equal(sound.el('state').textContent,sound.t('soundboard.status',{text:sound.t('soundboard.playing',{id:7})}));
    sound.run("Audio.prototype.play=()=>Promise.reject(new Error('private audio error'))");
    ws.onmessage({data:JSON.stringify({type:'soundboard',kind:'play',track_id:8})}); await flush();
    assert.equal(sound.el('state').textContent,sound.t('soundboard.status',{text:sound.t('soundboard.unavailable',{id:8})}));
    ws.onmessage({data:JSON.stringify({type:'soundboard',kind:'stop'})}); assert.equal(sound.el('state').textContent,sound.t('soundboard.status',{text:sound.t('soundboard.stopped')}));
    ws.onclose(); assert.equal(sound.el('state').textContent,sound.t('soundboard.status',{text:sound.t('common.disconnected')}));
    const hype=await boot('hype-meter',lang,{live:true}); hype.tick(500); assert.equal(hype.el('pct').textContent,hype.t('hype-meter.disconnected'));
  });
}

test('UI locale overrides legacy lang and invalid locales fall back to Russian',async()=>{
  for(const [search,expected] of [['?ui_lang=en&lang=ua&preview=1','en'],['?lang=ua&preview=1','ua'],['?ui_lang=unknown&preview=1','ru']]) {
    const h=await boot('soundboard','ru',{search}); assert.equal(h.context.WidgetI18n.lang,expected);
    h.context.WidgetI18n.add({ru:{'test.russian_only':'Русский текст'}});
    assert.equal(h.t('test.russian_only'),'Русский текст'); assert.equal(h.t('test.missing'),'Текст недоступен');
  }
});
