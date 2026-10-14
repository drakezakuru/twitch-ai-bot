const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function classes() {
  const values = new Set();
  return { add: (...xs) => xs.forEach(x => values.add(x)), remove: (...xs) => xs.forEach(x => values.delete(x)),
    contains: x => values.has(x), toggle(x, on) { on ??= !values.has(x); on ? values.add(x) : values.delete(x); } };
}
function node(id) {
  return { id, value: '', innerHTML: '', textContent: '', disabled: false, dataset: {}, classList: classes(),
    querySelectorAll: () => [], addEventListener() {}, closest() { return this; } };
}
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }
function harness() {
  const nodes = new Map();
  const calls = [];
  const context = vm.createContext({
    console, LANGS: {ru: {}, en: {}, ua: {}}, lang: 'en',
    $: id => { if (!nodes.has(id)) nodes.set(id, node(id)); return nodes.get(id); },
    esc: x => String(x ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    jopts: (method, body) => ({method, body: JSON.stringify(body)}),
    api: async (url, options) => { calls.push({url, options}); return {prompts: [], suggestions: []}; },
    apiErrorInfo: payload => ({message: payload.error.code === 'known' ? 'Translated safe error' : 'Safe fallback'}),
    document: {querySelectorAll: () => []}, clearDirty() {}, bindDirtyWatch() {}, toast() {}, confirmDirty: () => true,
  });
  vm.runInContext("function t(key) { return LANGS[lang][key] || LANGS.ru[key] || key; }", context);
  vm.runInContext(fs.readFileSync('static/app/20_director.js', 'utf8'), context);
  const run = script => vm.runInContext(script, context);
  run("_directorChannel = 'alpha'; _directorState = {config:{provider:'fake', model:'model-a'}};");
  return {context, nodes, calls, run};
}
const promptFixture = {id: 7, version: 1, prompt_text: 'Owner instructions', content_hash: 'hash', tested: true, active: false,
  replay_metadata: {run_id: 'reviewed-run', provider: 'fake', model: 'model-a', passed: true, cases: [{id: 'silence', passed: true, reason: '', response: '{"groups":[]}'}]}};
function seed(h, prompt = promptFixture) {
  h.context.promptFixture = structuredClone(prompt);
  h.run('_directorReview().prompts = [promptFixture]; _directorReview().loaded = true; renderDirectorReview();');
}

test('activation requires successful exact-model replay and explicit quality confirmation', async () => {
  const h = harness(); seed(h);
  await h.context.directorActivatePrompt('7');
  assert.equal(h.calls.length, 0);
  h.context.directorQualityChanged('7', true);
  h.run("_directorState.config.model = 'different'; renderDirectorReview();");
  await h.context.directorActivatePrompt('7');
  assert.equal(h.calls.length, 0);
  h.run("_directorState.config.model = 'model-a';");
  await h.context.directorActivatePrompt('7');
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, '/api/director/alpha/prompts/7/activate');
  assert.deepEqual(JSON.parse(h.calls[0].options.body), {quality_confirmed: true, replay_run_id: 'reviewed-run'});
});

test('replay sends no client metadata, blocks double clicks and invalidates quality', async () => {
  const h = harness(); seed(h); h.context.directorQualityChanged('7', true);
  const pending = deferred();
  h.context.api = (url, options) => { h.calls.push({url, options}); return pending.promise; };
  const action = h.context.directorReplayPrompt('7');
  await h.context.directorReplayPrompt('7');
  await h.context.directorActivatePrompt('7');
  assert.equal(h.calls.length, 1);
  assert.deepEqual(JSON.parse(h.calls[0].options.body), {});
  assert.match(h.nodes.get('directorPrompts').innerHTML, /directorReplayPrompt[^>]*disabled/);
  pending.resolve({prompts: [{...promptFixture, tested: false, replay_metadata: {...promptFixture.replay_metadata, passed: false}}]});
  await action;
  assert.match(h.nodes.get('directorPrompts').innerHTML, /Replay failed/);
  assert.equal(h.run('_directorReview().quality.size'), 0);
  await h.context.directorActivatePrompt('7');
  assert.equal(h.calls.length, 1);
});

test('creation preserves a newer draft while pending and rejects empty input locally', async () => {
  const h = harness();
  h.context.directorPromptDraftChanged('  ');
  await h.context.directorCreatePrompt();
  assert.equal(h.calls.length, 0);
  assert.match(h.nodes.get('directorReviewStatus').textContent, /Enter instructions/);
  h.context.directorPromptDraftChanged('first draft');
  const pending = deferred(); h.context.api = (url, options) => { h.calls.push({url, options}); return pending.promise; };
  const action = h.context.directorCreatePrompt();
  assert.equal(h.nodes.get('directorPromptCreate').disabled, true);
  await h.context.directorCreatePrompt();
  h.context.directorPromptDraftChanged('newer draft');
  pending.resolve({prompts: [promptFixture]}); await action;
  assert.equal(h.calls.length, 1);
  assert.deepEqual(JSON.parse(h.calls[0].options.body), {prompt_text: 'first draft'});
  assert.equal(h.nodes.get('directorPromptDraft').value, 'newer draft');
  assert.equal(h.nodes.get('directorPromptCreate').disabled, false);
});

test('single-record create responses refresh the authoritative prompt list', async () => {
  const h = harness();
  h.context.directorPromptDraftChanged('created prompt');
  h.context.api=async(url,options)=>{
    h.calls.push({url,options});
    return options ? {id:7,version:1,content_hash:'hash',tested:false} : {prompts:[promptFixture],suggestions:[]};
  };
  await h.context.directorCreatePrompt(); await Promise.resolve();
  assert.ok(h.calls.some(call=>call.url.endsWith('/prompts')&&!call.options));
  assert.match(h.nodes.get('directorPrompts').innerHTML,/Owner instructions/);
});

test('suggestions preserve edited order and approve only as examples, followed by refresh', async () => {
  const h = harness();
  h.run("_directorReview().suggestions = [{id:9,decision:null,messages:[{text:'one',worker_id:3},{text:'two',worker_id:4}]}]; renderDirectorReview();");
  h.context.directorSuggestionChanged('9', 1, 'edited second');
  const pending = deferred();
  h.context.api = (url, options) => { h.calls.push({url, options}); return options ? pending.promise : Promise.resolve({prompts:[], suggestions:[]}); };
  const action = h.context.directorDecideSuggestion('9', 'approve');
  await h.context.directorDecideSuggestion('9', 'approve');
  await h.context.directorDecideSuggestion('9', 'reject');
  assert.equal(h.calls.length, 1);
  assert.match(h.nodes.get('directorSuggestions').innerHTML, /directorDecideSuggestion[^>]*disabled/);
  assert.deepEqual(JSON.parse(h.calls[0].options.body), {messages: [{text:'one'}, {text:'edited second'}]});
  pending.resolve({ok:true, example_id:88}); await action; await Promise.resolve();
  assert.equal(h.calls[0].url, '/api/director/alpha/suggestions/9/approve');
  assert.ok(h.calls.some(call => call.url.endsWith('/suggestions') && !call.options));
  assert.ok(h.calls.every(call => !/send|dispatch/.test(call.url)));
});

test('reject uses an empty body, retains edits on safe API error, and permits retry', async () => {
  const h = harness();
  h.run("_directorReview().suggestions = [{id:9,decision:null,messages:[{text:'one'}]}];");
  h.context.directorSuggestionChanged('9', 0, 'edited');
  h.context.api = async (url, options) => { h.calls.push({url, options}); throw {payload:{error:{code:'known'}}, message:'PRIVATE INTERNAL TRACE'}; };
  await h.context.directorDecideSuggestion('9', 'reject');
  assert.equal(h.calls[0].url, '/api/director/alpha/suggestions/9/reject');
  assert.deepEqual(JSON.parse(h.calls[0].options.body), {});
  assert.match(h.nodes.get('directorSuggestions').innerHTML, />edited<\/textarea>/);
  assert.equal(h.nodes.get('directorReviewStatus').textContent, 'Translated safe error');
  await h.context.directorDecideSuggestion('9', 'reject');
  assert.equal(h.calls.length, 2);
});

test('channel-scoped late reads and mutation responses never populate another channel', async () => {
  const h = harness();
  const pending = deferred(); h.context.api = () => pending.promise;
  const read = h.context.loadDirectorReview();
  h.run("_directorChannel = 'beta'; directorPromptDraftChanged('beta draft'); renderDirectorReview();");
  pending.resolve({prompts:[promptFixture], suggestions:[]}); await read;
  assert.equal(h.nodes.get('directorPromptDraft').value, 'beta draft');
  assert.doesNotMatch(h.nodes.get('directorPrompts').innerHTML, /Owner instructions/);
  h.run("_directorChannel = 'alpha'; directorPromptDraftChanged('alpha draft');");
  const mutation = deferred(); h.context.api = () => mutation.promise;
  const action = h.context.directorCreatePrompt();
  h.run("_directorChannel = 'beta'; renderDirectorReview();");
  mutation.resolve({prompts:[promptFixture]}); await action;
  assert.equal(h.nodes.get('directorPromptDraft').value, 'beta draft');
  assert.doesNotMatch(h.nodes.get('directorPrompts').innerHTML, /Owner instructions/);
});

test('late status and audit responses are scoped to the requested channel', async () => {
  const h = harness(); const pending = deferred(); h.context.api = () => pending.promise;
  const status = h.context.loadDirectorChannel();
  const audit = h.context.loadDirectorAudit();
  h.run("_directorChannel = 'beta'; _directorState = {config:{model:'beta'}};");
  pending.resolve({config:{model:'alpha'},entries:[{action:'alpha-only'}]}); await Promise.all([status,audit]);
  assert.equal(h.run('_directorState.config.model'), 'beta');
  assert.doesNotMatch(h.nodes.get('directorAudit').innerHTML, /alpha-only/);
});

test('polling ignores earlier results and preserves prompt, suggestion and confirmation drafts in all locales', async () => {
  const h = harness(); seed(h);
  h.context.directorPromptDraftChanged('my prompt');
  h.run("_directorReview().suggestions = [{id:9,decision:null,messages:[{text:'one'}]}];");
  h.context.directorSuggestionChanged('9', 0, 'edited');
  h.context.directorQualityChanged('7', true);
  for (const language of ['ru','en','ua']) {
    h.context.lang = language; h.context.renderDirectorReview();
    assert.equal(h.nodes.get('directorPromptDraft').value, 'my prompt');
    assert.match(h.nodes.get('directorSuggestions').innerHTML, />edited<\/textarea>/);
    assert.match(h.nodes.get('directorPrompts').innerHTML, /directorQualityChanged[^>]* checked/);
  }
  const early = deferred(); const late = deferred(); let n = 0;
  h.context.api = () => (++n <= 2 ? early.promise : late.promise);
  const first = h.context.loadDirectorReview(); const second = h.context.loadDirectorReview();
  late.resolve({prompts:[promptFixture], suggestions:[{id:9,decision:null,messages:[{text:'one'}]}]}); await second;
  early.resolve({prompts:[], suggestions:[]}); await first;
  assert.match(h.nodes.get('directorPrompts').innerHTML, /Owner instructions/);
  assert.match(h.nodes.get('directorSuggestions').innerHTML, />edited<\/textarea>/);
});

test('prompt/model output and suggestion content are escaped, including attribute identifiers', () => {
  const h = harness();
  seed(h, {...promptFixture,id:'\" onclick=\"evil()',prompt_text:'</pre><script>evil()</script>',replay_metadata:{...promptFixture.replay_metadata,cases:[{id:'<img>',passed:false,response:'</pre><img onerror=evil()>',reason:'<svg>'}]}});
  h.run("_directorReview().suggestions = [{id:'\" onclick=\"evil()',decision:null,messages:[{text:'</textarea><script>evil()</script>'}]}]; renderDirectorReview();");
  const html = h.nodes.get('directorPrompts').innerHTML + h.nodes.get('directorSuggestions').innerHTML;
  assert.doesNotMatch(html, /<script>|<img|<svg|data-(?:prompt|suggestion)-id="" onclick=/);
  assert.match(html, /&quot; onclick=&quot;evil/);
  assert.match(html, /&lt;\/textarea&gt;/);
});

test('review rerender retains focused editor selection and open replay reports', () => {
  const h = harness();
  const active = {tagName:'TEXTAREA',type:'textarea',dataset:{suggestionId:'9',messageIndex:'0'},selectionStart:2,selectionEnd:4,getAttribute:()=>null};
  let focused=false, selected=null;
  const replacement = {...active,focus:()=>{focused=true;},setSelectionRange:(start,end)=>{selected=[start,end];}};
  const detail={open:true};
  let replaced=false;
  const container={contains:el=>el===active,querySelectorAll:selector=>selector==='details'?[detail]:replaced?[replacement]:[active],
    set innerHTML(value){replaced=true; detail.open=false;}};
  h.context.document.activeElement=active;
  h.context._directorReviewHTML(container,'changed locale');
  assert.equal(focused,true);
  assert.deepEqual(selected,[2,4]);
  assert.equal(detail.open,true);
});

test('live reactions render sent texts read-only and decide via reactions/live endpoints', async () => {
  const h = harness();
  h.run("_directorReview().reactions = [{id:11,decision:null,status:'valid',messages:[{text:'sent one',account_id:1,sent_at:123},{text:'sent two',account_id:1,sent_at:124}]}]; renderDirectorReview();");
  const html = h.nodes.get('directorReactions').innerHTML;
  assert.match(html, /sent one/);
  assert.doesNotMatch(html, /<textarea/);
  const pending = deferred();
  h.context.api = (url, options) => { h.calls.push({url, options}); return options ? pending.promise : Promise.resolve({prompts:[], suggestions:[], reactions:[]}); };
  const action = h.context.directorDecideReaction('11', 'approve');
  await h.context.directorDecideReaction('11', 'approve');
  await h.context.directorDecideReaction('11', 'reject');
  assert.equal(h.calls.length, 1);
  assert.match(h.nodes.get('directorReactions').innerHTML, /directorDecideReaction[^>]*disabled/);
  assert.deepEqual(JSON.parse(h.calls[0].options.body), {});
  pending.resolve({ok:true, example_id:5}); await action; await Promise.resolve();
  assert.equal(h.calls[0].url, '/api/director/alpha/reactions/live/11/approve');
  assert.ok(h.calls.some(call => call.url.endsWith('/reactions/live') && !call.options));
});

test('loadDirectorReview fetches prompts, suggestions and live reactions together', async () => {
  const h = harness();
  const pending = deferred(); h.context.api = (url, options) => { h.calls.push({url, options}); return pending.promise; };
  const read = h.context.loadDirectorReview();
  pending.resolve({prompts:[], suggestions:[], reactions:[{id:12,decision:null,messages:[{text:'live text',account_id:2,sent_at:1}]}]});
  await read;
  assert.deepEqual(h.calls.map(call => call.url.replace('/api/director/alpha/', '')), ['prompts', 'suggestions', 'reactions/live']);
  assert.match(h.nodes.get('directorReactions').innerHTML, /live text/);
});

test('training export downloads a file and import posts parsed document with confirm', async () => {
  const h = harness();
  const doc = {kind: 'director-training-export/v1', prompts: [], examples: [], chants: [], templates: []};
  h.context.api = async (url, options) => { h.calls.push({url, options}); if (!options) return doc; return {ok: true}; };
  const created = [];
  h.context.document = {
    querySelectorAll: () => [],
    createElement: () => { const link = {href: '', download: '', click: () => created.push(link), remove: () => {}}; return link; },
    body: {appendChild: () => {}},
  };
  h.context.Blob = class { constructor(parts, opts) { this.parts = parts; this.opts = opts; } };
  h.context.URL = {createObjectURL: () => 'blob:x', revokeObjectURL: () => {}};
  await h.context.directorExportTraining();
  assert.equal(h.calls[0].url, '/api/director/alpha/training/export');
  assert.equal(created.length, 1);
  assert.match(created[0].download, /director-training-alpha\.json$/);
  const input = {files: [{text: async () => JSON.stringify(doc)}], value: 'x'};
  await h.context.directorImportTraining(input);
  assert.equal(input.value, '');
  const last = h.calls.at(-1);
  assert.equal(last.url, '/api/director/alpha/training/import');
  assert.deepEqual(JSON.parse(last.options.body), {data: doc, replace: false, confirm: true});
  const broken = {files: [{text: async () => 'not json'}], value: 'x'};
  await h.context.directorImportTraining(broken);
  assert.equal(h.calls.length, 2); // no request for unparsable files
  assert.match(h.nodes.get('directorReviewStatus').textContent, /Safe fallback/);
});

test('unknown replay errors use safe fallback and leave retry available', async () => {
  const h = harness(); seed(h);
  h.context.api=async()=>{throw {message:'PRIVATE TRACE',payload:{error:{code:'unexpected_provider_error'}}};};
  await h.context.directorReplayPrompt('7');
  assert.equal(h.nodes.get('directorReviewStatus').textContent,'Safe fallback');
  assert.equal(h.run('_directorReview().pending.size'),0);
});

test('new labels and template references resolve in RU, EN and UA without provider calls', () => {
  const h = harness();
  const keys = h.run('Object.keys(DIRECTOR_REVIEW_I18N)');
  const template = fs.readFileSync('templates/partials/bots.html', 'utf8');
  for (const lang of ['ru','en','ua']) {
    for (const key of keys) assert.ok(h.context.LANGS[lang][`director.${key}`], `${lang}: ${key}`);
    for (const code of h.run('Object.keys(DIRECTOR_REVIEW_ERRORS)')) assert.ok(h.context.LANGS[lang][`api.error.${code}`], `${lang}: ${code}`);
    for (const [, key] of template.matchAll(/data-i18n="(director\.[^"]+)"/g)) {
      if (keys.includes(key.slice('director.'.length))) assert.ok(h.context.LANGS[lang][key], `${lang}: ${key}`);
    }
    assert.match(h.context.LANGS[lang]['director.mode_hint'], /Suggest/);
  }
  assert.equal(h.calls.length, 0);
});
