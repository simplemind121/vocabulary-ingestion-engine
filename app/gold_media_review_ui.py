GOLD_MEDIA_REVIEW_UI_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gold Source Media 复核</title>
<style>
:root{--line:#d9dde3;--ink:#1b1f24;--mute:#667085;--ok:#137333;--warn:#b54708;--accent:#1f5fbf;--bg:#f6f7f9}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,-apple-system,"PingFang SC",sans-serif;color:var(--ink);background:var(--bg)}
header{padding:12px 16px;background:#fff;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0}header a{color:var(--accent)}
main{display:grid;grid-template-columns:230px minmax(0,1fr) minmax(320px,440px);gap:12px;padding:12px;align-items:start}
@media(max-width:1000px){main{grid-template-columns:1fr}}
section{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px}
.page{display:flex;justify-content:space-between;gap:8px;padding:7px 8px;border-radius:6px;cursor:pointer}
.page:hover,.page.active{background:#eaf1fb}.done{color:var(--ok)}.todo{color:var(--warn)}small{color:var(--mute)}
.stage{position:relative;display:inline-block;max-width:100%}.stage img{max-width:100%;display:block;border:1px solid var(--line)}
.box{position:absolute;border:2px solid #d92d20;background:rgba(217,45,32,.08);color:#d92d20;font-weight:700;padding:0 4px}
.item{border:1px solid var(--line);border-radius:8px;padding:10px;margin-bottom:10px}
.item img{max-width:160px;max-height:160px;border:1px solid var(--line);display:block;margin:6px 0}
label{display:block;margin:4px 0}select,input[type=text],textarea{width:100%;padding:6px;border:1px solid var(--line);border-radius:6px;font:inherit}
button{padding:8px 12px;border-radius:6px;border:1px solid var(--line);background:#fff;font:inherit;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}button.warn{color:var(--warn)}
#message{min-height:20px;margin:8px 0}#message.error{color:#b42318}.warnings{color:var(--warn)}
</style></head><body>
<header><h1>Gold Sample v1 · Source Media 增量复核</h1><span id="progress"></span><a href="/">返回文字 Gold 复核</a></header>
<main><section><div id="pageList"></div></section>
<section id="viewer"><small>选择左侧页面</small></section>
<section id="panel"><small>选择左侧页面</small></section></main>
<script>
const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={pages:[],current:null};
async function api(path,options={}){const headers={...(options.headers||{})};if(options.body)headers['Content-Type']='application/json';const r=await fetch(path,{...options,headers});if(!r.ok){let b={};try{b=await r.json()}catch{}throw new Error(b.detail||`请求失败 (${r.status})`)}return r.json()}
function message(text,kind=''){const el=$('message');if(el){el.textContent=text;el.className=kind}}
async function loadState(){const data=await api('/api/media/state');state.pages=data.pages;$('progress').textContent=`${data.human_verified_count} / ${data.pages.length} 页已签核 · 共 ${data.media_total} 张原书图片`;
$('pageList').innerHTML=data.pages.map(p=>`<div class="page ${state.current?.page_number===p.page_number?'active':''}" data-page="${p.page_number}"><span>第 ${p.page_number} 页 <small>${p.media_count} 图${p.missing_media_reported?' · 已报漏图':''}</small></span><span class="${p.review_status==='HUMAN_VERIFIED'?'done':'todo'}">${p.review_status==='HUMAN_VERIFIED'?'已签核':'待核验'}</span></div>`).join('');
$('pageList').querySelectorAll('.page').forEach(el=>el.onclick=()=>selectPage(Number(el.dataset.page)))}
async function selectPage(n){state.current=await api(`/api/media/pages/${n}`);render();await loadState()}
function render(){const p=state.current,done=p.review_status==='HUMAN_VERIFIED';
$('viewer').innerHTML=`<div class="stage"><img src="${p.image_url}" alt="第 ${p.page_number} 页原始页面">${p.media.map(m=>`<div class="box" style="left:${m.bbox.x1*100}%;top:${m.bbox.y1*100}%;width:${(m.bbox.x2-m.bbox.x1)*100}%;height:${(m.bbox.y2-m.bbox.y1)*100}%">${m.media_order}</div>`).join('')}</div>`;
const options=p.page_lemmas.map(l=>`<option value="${esc(l)}">${esc(l)}</option>`).join('');
const items=p.media.map(m=>{const machine=m.media_role==='ENTRY_ILLUSTRATION'?`词条插画 → <strong>${esc(m.lemma)}</strong>`:m.media_role==='NON_VOCABULARY'?'非词汇内容（不绑定词条）':'机器无法确定归属';
const warnings=(m.machine?.warnings||[]).length?`<div class="warnings">警告：${esc(m.machine.warnings.join('，'))}</div>`:'';
return `<div class="item" data-order="${m.media_order}"><strong>图 ${m.media_order}</strong> <small>${m.width}×${m.height} · SHA256 ${esc(m.sha256.slice(0,12))}… · 置信度 ${m.machine?.confidence??'—'}</small><img src="${m.content_url}" alt="抽取的图 ${m.media_order}"><div>机器结论：${machine}</div>${warnings}
${done?`<div class="done">人工结论：${esc(m.human_decision)}</div>`:`<label><input type="radio" name="d${m.media_order}" value="APPROVE" ${m.media_role==='UNRESOLVED'?'disabled':''}> APPROVE（机器结论正确）</label>
<label><input type="radio" name="d${m.media_order}" value="CORRECT_ASSOCIATION"> 改为属于词条：<select data-lemma><option value="">选择本页词条</option>${options}</select><input type="text" data-lemma-text placeholder="或输入其他页的词条（跨页）"></label>
<label><input type="radio" name="d${m.media_order}" value="NOT_VOCABULARY_MEDIA"> 不是词汇图片（装饰/二维码/封面）</label>`}</div>`}).join('')||'<p>机器在本页未检测到任何原书图片。请对照原页确认本页确实没有图片。</p>';
$('panel').innerHTML=`<h2 style="margin-top:0;font-size:15px">第 ${p.page_number} 页 · ${p.media_count} 张图</h2>${items}${done?`<p class="done">已由 ${esc(p.reviewer_id)} 签核。</p>`:`
<label><input type="checkbox" data-check="compared_with_original_page"> 我已对照左侧原始页面</label>
<label><input type="checkbox" data-check="no_source_media_missing"> 本页没有漏检的原书图片</label>
<label><input type="checkbox" data-check="every_association_checked"> 每张图的归属都已确认${p.media_count?'':'（本页 0 张）'}</label>
<label>复核人<input type="text" id="reviewer" value="${esc(sessionStorage.getItem('goldReviewer')||'')}" placeholder="真实姓名或工号"></label>
<label>备注<textarea id="notes" rows="2"></textarea></label>
<div style="display:flex;gap:8px;flex-wrap:wrap"><button class="primary" id="verify">签核本页图片</button><button id="approveAll">全部选 APPROVE</button><button class="warn" id="missing">本页有漏检图片</button></div>`}<div id="message"></div>`;
if(done)return;$('approveAll').onclick=()=>document.querySelectorAll('input[value=APPROVE]:not(:disabled)').forEach(i=>i.checked=true);$('verify').onclick=verify;$('missing').onclick=missing}
async function verify(){const p=state.current,reviewer=$('reviewer').value.trim();if(!reviewer){message('请填写真实复核人。','error');return}
const checks=[...document.querySelectorAll('[data-check]:checked')].map(i=>i.dataset.check);const decisions=[];
for(const el of document.querySelectorAll('.item')){const order=Number(el.dataset.order);const picked=el.querySelector('input[type=radio]:checked');if(!picked){message(`请为图 ${order} 选择结论。`,'error');return}
decisions.push({media_order:order,decision:picked.value,lemma:el.querySelector('[data-lemma-text]').value.trim()||el.querySelector('[data-lemma]').value})}
try{await api(`/api/media/pages/${p.page_number}/verify`,{method:'POST',body:JSON.stringify({reviewer_id:reviewer,checks,decisions,notes:$('notes').value})});sessionStorage.setItem('goldReviewer',reviewer);await loadState();const next=state.pages.find(x=>x.review_status!=='HUMAN_VERIFIED');await selectPage(next?.page_number??p.page_number)}catch(e){message(e.message,'error')}}
async function missing(){const p=state.current,reviewer=$('reviewer').value.trim(),notes=$('notes').value.trim();if(!reviewer||!notes){message('报告漏图需要复核人，并在备注中说明漏了哪张图。','error');return}
try{await api(`/api/media/pages/${p.page_number}/missing`,{method:'POST',body:JSON.stringify({reviewer_id:reviewer,notes})});message('已记录漏图，本页保持 DRAFT。');await loadState()}catch(e){message(e.message,'error')}}
loadState().then(()=>{const next=state.pages.find(x=>x.review_status!=='HUMAN_VERIFIED')||state.pages[0];if(next)selectPage(next.page_number)}).catch(e=>{$('panel').textContent=e.message});
</script></body></html>"""
