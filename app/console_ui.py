CONSOLE_UI_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>VIE 控制台</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--line:#dde2ea;--ink:#172033;--mute:#667085;--accent:#1d4ed8;--ok:#137333;--okbg:#e7f4ea;--warn:#9a5b00;--warnbg:#fff4d6;--bad:#b42318;--badbg:#fdecea;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;color:var(--ink);background:var(--bg)}
*{box-sizing:border-box}body{margin:0;font-size:14px;line-height:1.5}
header{background:#111827;color:#fff;display:flex;align-items:center;gap:16px;padding:12px 20px;flex-wrap:wrap}
header strong{font-size:17px}header .sub{color:#aeb8c9;font-size:13px;flex:1}
header input{border:0;border-radius:8px;padding:8px 10px;font:inherit;width:220px}
button{border:1px solid var(--line);background:#fff;border-radius:8px;padding:8px 14px;font:inherit;font-weight:600;cursor:pointer;color:var(--ink)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}button.danger{color:var(--bad)}button:disabled{opacity:.5;cursor:not-allowed}
.shell{display:grid;grid-template-columns:300px minmax(0,1fr);min-height:calc(100vh - 56px)}
@media(max-width:900px){.shell{grid-template-columns:1fr}}
aside{background:var(--card);border-right:1px solid var(--line);padding:16px;overflow:auto}
main{padding:20px;min-width:0}
h2{font-size:15px;margin:0 0 10px}h3{font-size:14px;margin:16px 0 8px}
.drop{border:2px dashed #b8c2d3;border-radius:10px;padding:16px;text-align:center;color:var(--mute);cursor:pointer;margin-bottom:14px}
.drop.over{border-color:var(--accent);background:#eff6ff}
.run{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0;cursor:pointer}
.run.active{border-color:var(--accent);background:#eff6ff}.run .name{font-weight:600;word-break:break-all}.run small{color:var(--mute);display:block}
.pill{display:inline-block;border-radius:999px;padding:2px 9px;font-size:12px;font-weight:600;background:#eef1f5;color:#475467}
.pill.ok{background:var(--okbg);color:var(--ok)}.pill.warn{background:var(--warnbg);color:var(--warn)}.pill.bad{background:var(--badbg);color:var(--bad)}.pill.run_{background:#e0ecff;color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.steps{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
@media(max-width:700px){.steps{grid-template-columns:1fr}}
.step{border:1px solid var(--line);border-radius:10px;padding:10px;background:#fafbfc}
.step b{display:block}.step small{color:var(--mute)}
.step.done{border-color:#b7dfc1;background:var(--okbg)}.step.now{border-color:#f2d58a;background:var(--warnbg)}.step.fail{border-color:#f5c2bd;background:var(--badbg)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}.tabs button.on{background:#111827;color:#fff;border-color:#111827}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.grow{flex:1}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:600;font-size:12px}
tbody tr.click{cursor:pointer}tbody tr.click:hover{background:#f6f8fb}
input[type=text],input[type=search],select,textarea{border:1px solid #c8d0dc;border-radius:8px;padding:8px 10px;font:inherit;width:100%}
.split{display:grid;grid-template-columns:260px minmax(0,1fr) 340px;gap:14px;align-items:start}
@media(max-width:1200px){.split{grid-template-columns:1fr}}
.task{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:6px;cursor:pointer}.task.active{border-color:var(--accent);background:#eff6ff}
.stage{position:relative;display:inline-block;max-width:100%}.stage img{display:block;max-width:100%;border:1px solid var(--line)}
.bbox{position:absolute;border:3px solid #ef4444;background:#ef444422;pointer-events:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.tile{border:1px solid var(--line);border-radius:10px;padding:8px;background:#fff;text-align:center}.tile img{max-width:100%;max-height:130px;display:block;margin:0 auto 6px}
.mute{color:var(--mute)}.msg{padding:8px 12px;border-radius:8px;margin-bottom:12px}.msg.err{background:var(--badbg);color:var(--bad)}.msg.info{background:#e0ecff;color:var(--accent)}
.kv{display:grid;grid-template-columns:110px minmax(0,1fr);gap:4px 10px}.kv dt{color:var(--mute)}.kv dd{margin:0;word-break:break-word}
progress{width:100%}label.field{display:block;margin:8px 0}label.field span{display:block;color:var(--mute);font-size:12px;margin-bottom:3px}
</style>
</head>
<body>
<header>
  <strong>Vocabulary Ingestion Engine</strong><span class="sub">词书 PDF → 可溯源词汇数据库</span>
  <form id="keyForm" class="row"><input id="token" type="password" autocomplete="off" placeholder="API 密钥"><button class="primary" type="submit">连接</button></form>
</header>
<div class="shell">
  <aside>
    <h2>1 · 上传词书</h2>
    <div class="drop" id="drop">点击选择或拖入 PDF<input id="file" type="file" accept="application/pdf" hidden></div>
    <div id="uploadState"></div>
    <h2>词书与运行</h2>
    <div id="runs"><div class="mute">输入 API 密钥后载入</div></div>
  </aside>
  <main>
    <div id="message"></div>
    <div id="detail"><div class="card mute">从左侧上传一本词书，或选择一次已有的运行。</div></div>
  </main>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const S={token:sessionStorage.getItem('vieToken')||'',runs:[],run:null,runId:null,tab:'overview',reviews:[],task:null,gold:null,goldRun:null,media:null,mediaRun:null,page:0,query:'',auto:localStorage.getItem('vieAuto')!=='0',timer:null,busy:false};
$('token').value=S.token;
const ACTIVE=['QUEUED','STARTING','RUNNING'];
const STATUS={READY:'待处理',QUEUED:'排队中',STARTING:'启动中',RUNNING:'处理中',REVIEW_REQUIRED:'待人工复核',COMPLETED:'已完成',FAILED:'失败',OCR_REQUIRED:'需要 OCR',QUEUE_FAILED:'排队失败'};
const REASON={LOW_OCR_CONFIDENCE:'OCR 置信度低',STRUCTURED_EXTRACTION_UNCERTAIN:'结构化结果待确认',G4_VALIDATION_FAILED:'字段校验失败',NO_TEXT_LAYER:'无文本层页面',SOURCE_MEDIA_ASSOCIATION_UNCERTAIN:'原书图片归属待确认'};
function pill(status){const cls=status==='COMPLETED'||status==='PASS'?'ok':status==='REVIEW_REQUIRED'?'warn':['FAILED','FAIL','QUEUE_FAILED','OCR_REQUIRED'].includes(status)?'bad':ACTIVE.includes(status)?'run_':'';return `<span class="pill ${cls}">${esc(STATUS[status]||status)}</span>`}
function message(text,kind='err'){$('message').innerHTML=text?`<div class="msg ${kind}">${esc(text)}</div>`:''}
async function api(path,options={}){const headers={...(options.headers||{}),Authorization:`Bearer ${S.token}`};if(options.json){headers['Content-Type']='application/json';options.body=JSON.stringify(options.json)}const r=await fetch(path,{...options,headers});if(!r.ok){let b={};try{b=await r.json()}catch{}throw new Error(b.detail||`请求失败 (${r.status})`)}return r}
const getJson=async(path,options)=>(await api(path,options)).json();
const blobCache=new Map();
async function blobUrl(path){if(!blobCache.has(path))blobCache.set(path,api(path).then(r=>r.blob()).then(b=>URL.createObjectURL(b)).catch(e=>{blobCache.delete(path);throw e}));return blobCache.get(path)}
function lazyImages(root){const io=new IntersectionObserver(entries=>entries.forEach(e=>{if(!e.isIntersecting)return;io.unobserve(e.target);blobUrl(e.target.dataset.src).then(u=>e.target.src=u).catch(()=>{})}),{rootMargin:'200px'});root.querySelectorAll('img[data-src]').forEach(img=>io.observe(img))}

$('keyForm').onsubmit=e=>{e.preventDefault();S.token=$('token').value.trim();sessionStorage.setItem('vieToken',S.token);loadRuns(true)};
async function loadRuns(announce){if(!S.token)return;try{S.runs=(await getJson('/api/v1/runs')).items;renderRuns();if(announce)message('');if(!S.runId&&S.runs[0])selectRun(S.runs[0].id)}catch(e){message(e.message);$('runs').innerHTML='<div class="mute">无法载入，请检查 API 密钥</div>'}}
function renderRuns(){$('runs').innerHTML=S.runs.length?S.runs.map(r=>`<div class="run ${r.id===S.runId?'active':''}" data-id="${r.id}"><div class="name">${esc(r.filename)}</div><div class="row" style="margin-top:4px">${pill(r.status)}${r.open_reviews?`<span class="pill warn">${r.open_reviews} 项待复核</span>`:''}</div><small>${r.page_count} 页 · ${esc(String(r.created_at).slice(0,16).replace('T',' '))}</small></div>`).join(''):'<div class="mute">还没有运行</div>';$('runs').querySelectorAll('.run').forEach(el=>el.onclick=()=>selectRun(el.dataset.id))}

const drop=$('drop');drop.onclick=()=>$('file').click();$('file').onchange=()=>$('file').files[0]&&upload($('file').files[0]);
drop.ondragover=e=>{e.preventDefault();drop.classList.add('over')};drop.ondragleave=()=>drop.classList.remove('over');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');const f=e.dataTransfer.files[0];if(f)upload(f)};
function upload(file){if(!S.token){message('请先输入 API 密钥并连接。');return}if(!/\.pdf$/i.test(file.name)){message('只支持 PDF 文件。');return}
const form=new FormData();form.append('file',file,file.name);const xhr=new XMLHttpRequest();xhr.open('POST','/api/v1/documents');xhr.setRequestHeader('Authorization',`Bearer ${S.token}`);
$('uploadState').innerHTML=`<div class="mute">上传 ${esc(file.name)}</div><progress id="bar" max="100" value="0"></progress>`;
xhr.upload.onprogress=e=>{if(e.lengthComputable){$('bar').value=e.loaded/e.total*100;if(e.loaded===e.total)$('uploadState').innerHTML='<div class="mute">已上传，正在渲染每一页（大书约需 1 分钟）…</div><progress></progress>'}};
xhr.onload=async()=>{$('file').value='';let body={};try{body=JSON.parse(xhr.responseText)}catch{}if(xhr.status>=300){$('uploadState').innerHTML='';message(body.detail||`上传失败 (${xhr.status})`);return}$('uploadState').innerHTML='';message(`已上传 ${body.filename}，共 ${body.page_count} 页。`,'info');await loadRuns();await selectRun(body.run_id);if(S.auto)enqueue()};
xhr.onerror=()=>{$('uploadState').innerHTML='';message('上传中断，请重试。')};xhr.send(form)}

async function selectRun(id){S.runId=id;S.tab='overview';S.task=null;renderRuns();await refreshRun();schedule()}
function schedule(){clearInterval(S.timer);S.timer=setInterval(tick,3000)}
async function tick(){if(!S.runId||S.busy)return;const before=S.run?.status;try{await refreshRun(true)}catch{return}
if(before!==S.run.status)loadRuns()}
async function refreshRun(quiet){S.busy=true;try{const id=S.runId;const [run,open,esc_]=await Promise.all([getJson(`/api/v1/runs/${id}`),getJson(`/api/v1/runs/${id}/reviews?status=OPEN`),getJson(`/api/v1/runs/${id}/reviews?status=ESCALATED`)]);if(id!==S.runId)return;const changed=!S.run||S.run.id!==run.id||S.run.status!==run.status||S.openCount!==open.count||JSON.stringify(S.run.gates)!==JSON.stringify(run.gates);S.run=run;S.reviews=[...open.items,...esc_.items];S.openCount=S.reviews.length;S.meta=S.runs.find(r=>r.id===id)||{};if(changed||!quiet)render()}finally{S.busy=false}}
async function enqueue(){try{await api(`/api/v1/runs/${S.runId}/enqueue`,{method:'POST'});message('');await refreshRun();loadRuns()}catch(e){if(!/already active/.test(e.message))message(e.message)}}

function gate(name){return (S.run.gates||[]).find(g=>g.gate===name)}
function stepState(gates,extra){const st=gates.map(n=>gate(n)?.status);if(st.some(x=>x==='FAIL'))return'fail';if(st.every(x=>x==='PASS')&&extra!==false)return'done';if(st.some(Boolean)||extra===false)return'now';return''}
function render(){const r=S.run,m=S.meta;const released=r.metrics?.gold_release_id;const g2=gate('G2')?.metrics||{},gm=gate('G3_MEDIA')?.metrics||{},g1=gate('G1')?.metrics||{};
const steps=[['上传与渲染',stepState(['G0']),`${m.page_count||r.metrics?.rendered_pages||'—'} 页`],['文本与图片识别',stepState(['G1','G2','G3']),g2.source_entry_count?`${g2.source_entry_count} 个词条 · ${gm.media_persisted??0} 张图`:(g1.text_block_count?`${g1.text_block_count} 个文本块`:'等待处理')],['人工复核',S.openCount?'now':(gate('G5')?.status==='PASS'?'done':''),S.openCount?`${S.openCount} 项待处理`:'无待办'],['校验',stepState(['G4','G3_MEDIA']),gate('G4')?`${gate('G4').metrics.verified_entries} 条已验证`:'—'],['发布数据集',released?'done':(gate('G6')?.status==='FAIL'?'fail':''),released?'已发布':'—']];
const canRun=['READY','REVIEW_REQUIRED','FAILED','QUEUE_FAILED','OCR_REQUIRED'].includes(r.status);
const action=ACTIVE.includes(r.status)?'<span class="mute">正在处理，页面会自动刷新…</span>':r.status==='COMPLETED'?'':S.openCount?`<button class="primary" id="goReview">去复核 ${S.openCount} 项</button>`:canRun?`<button class="primary" id="runBtn">${r.status==='READY'?'开始处理':'继续处理'}</button>`:'';
const tabs=[['overview','概览'],['reviews',`复核${S.openCount?` (${S.openCount})`:''}`],['entries','词条'],['media','原书图片'],['export','导出']];
$('detail').innerHTML=`<div class="card"><div class="row"><h2 class="grow" style="margin:0">${esc(m.filename||r.id)}</h2>${pill(r.status)}${action}</div>
<div class="steps" style="margin-top:12px">${steps.map((s,i)=>`<div class="step ${s[1]}"><b>${i+1} · ${s[0]}</b><small>${esc(s[2])}</small></div>`).join('')}</div>
<label class="row mute" style="margin-top:10px"><input type="checkbox" id="auto" ${S.auto?'checked':''}> 上传后自动开始；复核清空后自动继续</label></div>
<div class="tabs">${tabs.map(t=>`<button data-tab="${t[0]}" class="${S.tab===t[0]?'on':''}">${t[1]}</button>`).join('')}</div><div id="tab"></div>`;
$('auto').onchange=e=>{S.auto=e.target.checked;localStorage.setItem('vieAuto',S.auto?'1':'0')};
if($('runBtn'))$('runBtn').onclick=enqueue;if($('goReview'))$('goReview').onclick=()=>{S.tab='reviews';render()};
$('detail').querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{S.tab=b.dataset.tab;render()});
({overview:tabOverview,reviews:tabReviews,entries:tabEntries,media:tabMedia,export:tabExport})[S.tab]()}

function tabOverview(){const r=S.run;const order=['G0','G1','G2','G3','G3_MEDIA','G4','G5','G6'];const names={G0:'源文件与渲染',G1:'页面文本表示',G2:'词条切分',G3:'结构化抽取',G3_MEDIA:'原书图片保真',G4:'校验',G5:'复核完成',G6:'发布'};
const rows=order.map(n=>{const g=gate(n);return `<tr><td><b>${n}</b> ${names[n]}</td><td>${g?pill(g.status):'<span class="mute">未执行</span>'}</td><td class="mute">${g?esc(Object.entries(g.metrics||{}).map(([k,v])=>`${k}=${typeof v==='number'&&!Number.isInteger(v)?v.toFixed(3):v}`).join('  ')):''}</td></tr>`}).join('');
const err=r.error_summary&&r.status==='FAILED'?`<div class="msg err">${esc(r.error_summary.error_type||'')} ${esc(r.error_summary.message||JSON.stringify(r.error_summary))}</div>`:'';
$('tab').innerHTML=`${err}<div class="card"><h2>各阶段 Gate</h2><table><thead><tr><th>Gate</th><th>状态</th><th>指标</th></tr></thead><tbody>${rows}</tbody></table></div>
<div class="card"><dl class="kv"><dt>运行 ID</dt><dd>${esc(r.id)}</dd><dt>源文件 SHA256</dt><dd>${esc(S.meta.sha256||'—')}</dd><dt>流水线版本</dt><dd>${esc(r.pipeline_version)}</dd></dl></div>`}

function tabReviews(){if(!S.reviews.length){$('tab').innerHTML=`<div class="card">当前没有待复核项。${S.run.status==='REVIEW_REQUIRED'?' <button class="primary" id="cont">继续处理</button>':''}</div>`;if($('cont'))$('cont').onclick=enqueue;return}
if(!S.task||!S.reviews.find(t=>t.id===S.task.id))S.task=S.reviews[0];const t=S.task;
const list=S.reviews.map(i=>`<div class="task ${i.id===t.id?'active':''}" data-id="${i.id}"><span class="pill warn">${esc(REASON[i.reason_code]||i.reason_code)}</span>${i.status==='ESCALATED'?' <span class="pill bad">曾标记无法判断</span>':''}<div>第 ${esc(i.page?.page_number??'—')} 页</div></div>`).join('');
const box=t.bbox?.unit==='normalized'?`<div class="bbox" style="left:${t.bbox.x1*100}%;top:${t.bbox.y1*100}%;width:${(t.bbox.x2-t.bbox.x1)*100}%;height:${(t.bbox.y2-t.bbox.y1)*100}%"></div>`:'';
let edit='',extra='';
if(t.target_entity_type==='SourceBlock'){edit=`<label class="field"><span>红框内的正确文本</span><textarea id="value" rows="5">${esc(t.current_value)}</textarea></label>`;extra='<button id="discard">不是文字（噪声）</button>'}
else if(t.target_entity_type==='VocabularyEntry')edit=`<label class="field"><span>词条</span><input type="text" id="value" value="${esc(t.current_value)}"></label>`;
else if(t.target_entity_type==='SourceMedia')edit=`<label class="field"><span>红框内的原书图片属于哪个词条？</span><select id="value">${(t.media_candidates||[]).map(c=>`<option value="${esc(c.source_entry_id)}">词条：${esc(c.lemma||c.source_entry_id)}</option>`).join('')}<option value="NOT_VOCABULARY_MEDIA">不是词汇图片（装饰 / 二维码 / 封面）</option></select></label>`;
else edit='<label class="field"><span>页面分类</span><select id="value"><option value="NON_TEXT_PAGE">非文本页</option></select></label>';
$('tab').innerHTML=`<div class="split"><div class="card">${list}</div><div class="card">${t.page?`<div class="stage"><img id="pageImg" alt="第 ${esc(t.page.page_number)} 页">${box}</div>`:'<span class="mute">此项没有关联页面</span>'}</div>
<div class="card"><h2>${esc(REASON[t.reason_code]||t.reason_code)}</h2><dl class="kv"><dt>页码</dt><dd>${esc(t.page?.page_number??'—')}</dd><dt>置信度</dt><dd>${t.confidence==null?'—':Number(t.confidence).toFixed(3)}</dd><dt>机器结果</dt><dd>${esc(t.source_text||'—')}</dd></dl>
${edit}<label class="field"><span>复核人</span><input type="text" id="reviewer" value="${esc(localStorage.getItem('vieReviewer')||'')}" placeholder="真实姓名或工号"></label>
<label class="field"><span>备注（可选）</span><input type="text" id="notes"></label>
<div class="row"><button class="primary" id="accept">确认，下一项</button>${extra}<button class="danger" id="reject">无法判断</button></div></div></div>`;
$('tab').querySelectorAll('.task').forEach(el=>el.onclick=()=>{S.task=S.reviews.find(x=>x.id===el.dataset.id);tabReviews()});
if(t.page)blobUrl(t.page.image_url).then(u=>{if($('pageImg'))$('pageImg').src=u}).catch(e=>message(`原始页图载入失败：${e.message}`));
$('accept').onclick=()=>resolve('ACCEPT');$('reject').onclick=()=>resolve('REJECT');if($('discard'))$('discard').onclick=()=>resolve('DISCARD')}
async function resolve(decision){const t=S.task,reviewer=$('reviewer').value.trim();if(!reviewer){message('请填写复核人。');return}localStorage.setItem('vieReviewer',reviewer);
const body={reviewer_id:reviewer,decision,notes:$('notes').value.trim()||null},v=$('value').value;
if(t.target_entity_type==='VocabularyEntry')body.lemma=v;else if(t.target_entity_type==='SourceBlock'){if(decision==='ACCEPT')body.corrected_text=v}else if(t.target_entity_type==='SourceMedia'){if(v==='NOT_VOCABULARY_MEDIA')body.classification=v;else body.source_entry_id=v}else body.classification=v;
try{await api(`/api/v1/reviews/${t.id}/resolve`,{method:'POST',json:body});message('');S.task=null;await refreshRun();loadRuns();if(S.auto&&S.openCount===0&&S.run.status==='REVIEW_REQUIRED'){S.tab='overview';await enqueue()}}catch(e){message(e.message)}}

async function loadGold(){if(S.goldRun===S.runId&&S.gold)return S.gold;S.gold=await getJson(`/api/v1/runs/${S.runId}/gold`);S.goldRun=S.runId;return S.gold}
async function tabEntries(){$('tab').innerHTML='<div class="card mute">载入词条…</div>';let data;try{data=await loadGold()}catch(e){$('tab').innerHTML=`<div class="card">词条在全部验证通过后才能浏览。<div class="mute">${esc(e.message)}</div></div>`;return}
if(S.tab!=='entries')return;const q=S.query.trim().toLowerCase();const rows=q?data.records.filter(r=>r.lemma.toLowerCase().includes(q)||r.senses.some(s=>s.definitions.some(d=>d.includes(S.query.trim())))):data.records;
const size=50,pages=Math.max(1,Math.ceil(rows.length/size));S.page=Math.min(S.page,pages-1);const slice=rows.slice(S.page*size,S.page*size+size);
$('tab').innerHTML=`<div class="card"><div class="row"><input class="grow" type="search" id="q" placeholder="搜索词条或释义" value="${esc(S.query)}" style="max-width:320px"><span class="mute">${rows.length} / ${data.record_count} 条 · ${data.source_media_count} 张词条插画</span><span class="grow"></span><button id="prev" ${S.page?'':'disabled'}>上一页</button><span class="mute">${S.page+1} / ${pages}</span><button id="next" ${S.page<pages-1?'':'disabled'}>下一页</button></div>
<table style="margin-top:10px"><thead><tr><th>词条</th><th>音标</th><th>词性</th><th>释义</th><th>页</th><th>图</th></tr></thead><tbody>${slice.map(r=>`<tr class="click" data-id="${r.id}"><td><b>${esc(r.lemma)}</b></td><td>${esc(r.pronunciations.map(p=>p.ipa).filter(Boolean).join(' | '))}</td><td>${esc(r.senses.map(s=>s.part_of_speech).filter(Boolean).join(' | '))}</td><td>${esc(r.senses.flatMap(s=>s.definitions).join(' | '))}</td><td>${esc((r.source_pages||[]).join(', '))}</td><td>${r.source_media.length||''}</td></tr>`).join('')}</tbody></table></div><div id="entry"></div>`;
$('q').oninput=e=>{S.query=e.target.value;S.page=0;clearTimeout(S.qt);S.qt=setTimeout(()=>tabEntries().then(()=>{const el=$('q');if(el){el.focus();el.setSelectionRange(el.value.length,el.value.length)}}),250)};
$('prev').onclick=()=>{S.page--;tabEntries()};$('next').onclick=()=>{S.page++;tabEntries()};
$('tab').querySelectorAll('tr.click').forEach(tr=>tr.onclick=()=>showEntry(data.records.find(r=>r.id===tr.dataset.id)))}
const FIELD={MEMORY_NOTE:'记忆法',COLLOCATION:'搭配',EXAMPLE:'例句',DERIVATIVE:'派生词',SYNONYM:'同义词',ANTONYM:'反义词'};
function showEntry(r){const fields=Object.entries(r.source_fields||{}).map(([k,v])=>`<dt>${esc(FIELD[k]||k)}</dt><dd>${v.map(esc).join('<br>')}</dd>`).join('');
$('entry').innerHTML=`<div class="card"><h2>${esc(r.lemma)} <span class="pill ok">${r.verification_status==='HUMAN_VERIFIED'?'人工验证':'自动验证'}</span></h2><dl class="kv"><dt>音标</dt><dd>${esc(r.pronunciations.map(p=>p.ipa).filter(Boolean).join(' | ')||'原书未印')}</dd>${r.senses.map(s=>`<dt>${esc(s.part_of_speech||'释义')}</dt><dd>${s.definitions.map(esc).join('<br>')}</dd>`).join('')}${fields}<dt>原书页码</dt><dd>${esc((r.source_pages||[]).join(', '))}</dd></dl>
${r.source_media.length?`<h3>原书插画</h3><div class="grid">${r.source_media.map(m=>`<div class="tile"><img data-src="/api/v1/source-media/${m.media_id}/content" alt="${esc(r.lemma)} 的原书插画"><small class="mute">第 ${m.page} 页 · ${m.width}×${m.height}</small></div>`).join('')}</div>`:''}</div>`;lazyImages($('entry'));$('entry').scrollIntoView({behavior:'smooth',block:'nearest'})}

async function tabMedia(){$('tab').innerHTML='<div class="card mute">载入图片清单…</div>';try{if(S.mediaRun!==S.runId||!S.media||ACTIVE.includes(S.run.status)){S.media=await getJson(`/api/v1/runs/${S.runId}/source-media`);S.mediaRun=S.runId}}catch(e){$('tab').innerHTML=`<div class="card">${esc(e.message)}</div>`;return}
if(S.tab!=='media')return;const m=S.media.metrics,filter=S.mediaFilter||'ALL';const lemma={};if(S.goldRun===S.runId&&S.gold)S.gold.records.forEach(r=>lemma[r.id]=r.lemma);
const items=S.media.items.filter(i=>filter==='ALL'||i.media_role===filter);const ROLE={ENTRY_ILLUSTRATION:'词条插画',NON_VOCABULARY:'非词汇内容',UNRESOLVED:'待确认'};
$('tab').innerHTML=`<div class="card"><div class="row"><span>共 <b>${m.media_persisted}</b> 张 · 绑定词条 <b>${m.associated_with_vocabulary_entry}</b> · 非词汇 <b>${m.excluded_non_vocabulary}</b> · 待确认 <b>${m.unresolved_media}</b></span><span class="grow"></span><select id="mf" style="width:auto"><option value="ALL">全部</option>${Object.entries(ROLE).map(([k,v])=>`<option value="${k}" ${filter===k?'selected':''}>${v}</option>`).join('')}</select></div>
${items.length?`<div class="grid" style="margin-top:12px">${items.map(i=>`<div class="tile"><img data-src="${i.content_url}" alt="第 ${i.page} 页原书图片"><div>${esc(lemma[i.vocabulary_entry_id]||ROLE[i.media_role]||i.media_role)}</div><small class="mute">第 ${i.page} 页 · ${i.verification_status==='HUMAN_VERIFIED'?'人工确认':i.verification_status==='AUTO_VERIFIED'?'版面规则':'待确认'}</small></div>`).join('')}</div>`:'<p class="mute">这本书没有检出原书图片，或尚未处理到图片阶段。</p>'}</div>`;
$('mf').onchange=e=>{S.mediaFilter=e.target.value;tabMedia()};lazyImages($('tab'))}

async function tabExport(){const id=S.run.metrics?.gold_release_id;if(!id){$('tab').innerHTML=`<div class="card">数据集会在运行完成后自动发布。当前状态：${pill(S.run.status)}</div>`;return}
$('tab').innerHTML='<div class="card mute">载入发布信息…</div>';let rel;try{rel=await getJson(`/api/v1/gold/releases/${id}`)}catch(e){$('tab').innerHTML=`<div class="card">${esc(e.message)}</div>`;return}if(S.tab!=='export')return;
$('tab').innerHTML=`<div class="card"><h2>已发布的数据集</h2><dl class="kv"><dt>词条数</dt><dd>${rel.record_count}</dd><dt>Schema</dt><dd>${esc(rel.schema_version)}</dd><dt>版本</dt><dd>v${rel.version}</dd><dt>SHA256</dt><dd>${esc(rel.sha256)}</dd></dl>
<h3>下载</h3><div class="row"><button class="primary" data-f="json">JSON（最完整）</button><button data-f="csv">CSV</button><button data-f="xlsx">Excel</button></div>
<p class="mute">JSON 含记忆法、搭配、例句、原书图片引用与溯源；CSV 和 Excel 是精简表格。图片本身通过 API 获取，不在文件里。</p></div>`;
const base=(S.meta.filename||'vocabulary').replace(/\.pdf$/i,'');
$('tab').querySelectorAll('[data-f]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const blob=await (await api(`/api/v1/gold/releases/${id}/download/${b.dataset.f}`)).blob();const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${base}.${b.dataset.f}`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000)}catch(e){message(e.message)}finally{b.disabled=false}})}

if(S.token)loadRuns(true);
</script>
</body>
</html>"""
