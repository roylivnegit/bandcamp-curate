"""Serves the crate-digger feed UI - a single self-contained page (no build step)
that talks to the /api JSON endpoints on the same origin.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Bandcamp suggestions</title>
<style>
  :root {
    --bg:#0f1115; --panel:#171a21; --panel2:#1e222c; --line:#282d38;
    --text:#e7e9ee; --muted:#9aa3b2; --accent:#5eead4; --accent2:#f0abfc;
    --danger:#fb7185; --orange:#ff9e64;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  a { color:inherit; }
  .wrap { max-width:900px; margin:0 auto; padding:0 20px; }
  header { padding:30px 0 14px; }
  h1 { margin:0; font-size:34px; font-weight:800; letter-spacing:-.025em; line-height:1.05; }
  h1 .hl { background:linear-gradient(95deg,var(--accent),var(--accent2));
    -webkit-background-clip:text; background-clip:text; color:transparent; }
  .sub { margin-top:9px; font-size:17px; font-weight:500; letter-spacing:.005em;
    color:var(--orange); opacity:.92; }
  .controls { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:20px; }
  .seg { display:flex; background:var(--panel); border:1px solid var(--line); border-radius:11px; overflow:hidden; }
  .seg button { background:none; border:0; color:var(--muted); padding:10px 20px; cursor:pointer; font-size:14px; }
  .seg button.on { background:var(--panel2); color:var(--accent); }
  .ddpanel.compact { width:210px; }
  .ddrow .tick { width:14px; flex:none; color:transparent; font-size:11px; }
  .ddrow.sel .tick { color:var(--accent); }
  .spacer { flex:1; }
  .btn { background:var(--accent); color:#06231e; border:0; border-radius:11px;
    padding:10px 17px; font-weight:600; cursor:pointer; font-size:14px; }
  .btn.ghost { background:var(--panel); color:var(--muted); border:1px solid var(--line); }
  /* active toggle state for the Liked / Blocked panel buttons */
  .btn.ghost.on { background:var(--panel2); color:var(--accent); border-color:var(--accent); }
  .btn:disabled { opacity:.5; cursor:default; }
  .hint { color:var(--muted); font-size:12px; margin:12px 0 4px; }
  /* genre dropdown (searchable, count-ordered) */
  .genrebar { display:flex; align-items:center; gap:10px; margin-top:10px; flex-wrap:wrap; }
  .dd { position:relative; }
  .ddpanel { position:absolute; z-index:30; top:calc(100% + 6px); left:0; width:300px;
    background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:8px;
    box-shadow:0 10px 30px rgba(0,0,0,.45); }
  .ddsearch { width:100%; background:var(--panel2); border:1px solid var(--line); color:var(--text);
    border-radius:8px; padding:8px 10px; font-size:13px; outline:none; }
  .ddsearch:focus { border-color:var(--accent); }
  .ddlist { max-height:300px; overflow-y:auto; margin-top:8px; }
  .ddlist::-webkit-scrollbar { width:8px; } .ddlist::-webkit-scrollbar-thumb { background:var(--line); border-radius:4px; }
  .ddrow { display:flex; align-items:center; gap:9px; padding:6px 8px; border-radius:8px; cursor:pointer; font-size:13px; }
  .ddrow:hover { background:var(--panel2); }
  .ddrow.sel { color:var(--accent); }
  .ddrow .box { width:15px; height:15px; flex:none; border:1px solid var(--line); border-radius:4px;
    display:inline-flex; align-items:center; justify-content:center; font-size:10px; color:transparent; }
  .ddrow.sel .box { background:var(--accent); border-color:var(--accent); color:#06231e; }
  .ddrow .nm { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .ddrow .cnt { color:var(--muted); font-variant-numeric:tabular-nums; }
  .ddempty { color:var(--muted); font-size:12px; padding:10px 8px; }
  .ddfoot { display:flex; justify-content:space-between; gap:8px; margin-top:8px;
    padding-top:8px; border-top:1px solid var(--line); }
  .ddfoot .btn { padding:7px 14px; }
  .active { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-top:8px; min-height:0; }
  .fpill { font-size:12px; background:var(--panel2); border:1px solid var(--line); border-radius:999px;
    padding:3px 4px 3px 9px; color:var(--text); display:inline-flex; align-items:center; gap:6px; }
  .fpill .tog { cursor:pointer; } .fpill b { color:var(--accent); } .fpill.out b { color:var(--danger); }
  .fpill.out .tog { color:var(--danger); }
  .fpill .rm { cursor:pointer; padding:0 5px; border-radius:999px; color:var(--muted); }
  .fpill .rm:hover { background:var(--line); color:var(--text); }
  main { margin:12px 0 60px; }
  .card { display:flex; gap:14px; align-items:flex-start; background:var(--panel);
    border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin-bottom:10px; overflow:hidden; }
  /* evaporate: fade out while drifting up + blurring, then collapse the gap.
     Same motion for like/block; only the flash colour differs (teal / red). 0.8s. */
  @keyframes evaporate-like {
    0%   { opacity:1; filter:blur(0); transform:translateY(0) scale(1); }
    15%  { box-shadow:0 0 0 2px var(--accent); }
    60%  { opacity:.28; filter:blur(4px); transform:translateY(-14px) scale(1.015); }
    100% { opacity:0; filter:blur(11px); transform:translateY(-30px) scale(1.03);
           max-height:0; margin-bottom:0; padding-top:0; padding-bottom:0; border-width:0; }
  }
  @keyframes evaporate-block {
    0%   { opacity:1; filter:blur(0); transform:translateY(0) scale(1); }
    15%  { box-shadow:0 0 0 2px var(--danger); }
    60%  { opacity:.28; filter:blur(4px); transform:translateY(-14px) scale(1.015); }
    100% { opacity:0; filter:blur(11px); transform:translateY(-30px) scale(1.03);
           max-height:0; margin-bottom:0; padding-top:0; padding-bottom:0; border-width:0; }
  }
  .card.liking  { animation:evaporate-like 1.3s ease forwards; pointer-events:none; }
  .card.blocking{ animation:evaporate-block 1.3s ease forwards; pointer-events:none; }
  .score { min-width:52px; text-align:center; }
  .score b { display:block; font-size:18px; color:var(--accent); font-variant-numeric:tabular-nums; }
  .score span { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; }
  .body { flex:1; min-width:0; }
  .title { font-weight:600; }
  .title .type { font-size:10px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--accent2); border:1px solid var(--line); border-radius:6px; padding:1px 5px; margin-left:8px; }
  .band { color:var(--muted); font-size:13px; margin-top:2px; cursor:pointer; }
  .band:hover { color:var(--accent); text-decoration:underline; }
  .band .handle { color:var(--accent2); opacity:.85; }
  .band .handle::before { content:"·"; margin:0 5px; color:var(--muted); }
  .meta { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; font-size:12px; color:var(--muted); }
  .chip { background:var(--panel2); border:1px solid var(--line); border-radius:999px; padding:2px 9px; color:var(--text); }
  .chip.tag { color:var(--accent); cursor:pointer; }
  /* Actions live in their own row so they never wrap with the chips - fixed spot. */
  .actions { margin-top:12px; display:flex; gap:8px; align-items:center; justify-content:flex-end; }
  .act { background:none; border:1px solid var(--line); color:var(--muted); border-radius:9px;
    padding:6px 13px; font-size:13px; font-weight:500; cursor:pointer; line-height:1; }
  .like:hover { border-color:var(--accent); color:var(--accent); }
  .block:hover { border-color:var(--danger); color:var(--danger); }
  .listen { color:var(--accent); text-decoration:none; font-weight:600; white-space:nowrap;
    border:1px solid var(--accent); border-radius:9px; padding:6px 13px; font-size:13px; line-height:1; }
  .listen:hover { background:var(--accent); color:#06231e; }
  .count { color:var(--muted); font-size:13px; margin:6px 0 10px; }
  .count b { color:var(--text); font-size:16px; }
  .empty { color:var(--muted); text-align:center; padding:50px 0; }
  .more { display:block; margin:16px auto 0; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin-top:12px; }
  .brow { display:flex; align-items:center; gap:10px; padding:6px 0; border-bottom:1px solid var(--line); }
  .brow:last-child { border-bottom:0; }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Bandcamp <span class="hl">suggestions</span></h1>
  <div class="sub">Music your collection's supporters own that you don't - one per artist, ranked.</div>
</header>
<div class="controls">
  <div class="seg" id="filter">
    <button data-t="" class="on">All</button>
    <button data-t="album">Albums</button>
    <button data-t="track">Tracks</button>
  </div>
  <div class="dd" id="sortDd">
    <button class="btn ghost" id="sortBtn">Sort · Top score ▾</button>
    <div class="ddpanel compact" id="sortPanel" style="display:none">
      <div class="ddrow sel" data-sort="score"><span class="tick">✓</span><span class="nm">Top score</span></div>
      <div class="ddrow" data-sort="neighbours"><span class="tick">✓</span><span class="nm">Most owners</span></div>
      <div class="ddrow" data-sort="affinity"><span class="tick">✓</span><span class="nm">Genre match</span></div>
    </div>
  </div>
  <div class="spacer"></div>
  <button class="btn ghost" id="likedBtn">♥ Liked (0)</button>
  <button class="btn ghost" id="blockedBtn">Blocked (0)</button>
</div>
<div class="genrebar">
  <div class="dd" id="genreDd">
    <button class="btn ghost" id="genreBtn">＋ Genre filter</button>
    <div class="ddpanel" id="genrePanel" style="display:none">
      <input class="ddsearch" id="genreSearch" placeholder="Search genres…" autocomplete="off"/>
      <div class="ddlist" id="genreList"></div>
      <div class="ddfoot">
        <button class="btn ghost" id="genreClear">Clear</button>
        <button class="btn" id="genreSave">Save</button>
      </div>
    </div>
  </div>
</div>
<div class="active" id="active"></div>
<div class="panel" id="likedPanel" style="display:none"></div>
<div class="panel" id="blockedPanel" style="display:none"></div>
<main>
  <div class="count" id="count"></div>
  <div id="feed"></div>
  <button class="btn more" id="more" style="display:none">Load more</button>
  <div class="empty" id="empty" style="display:none">No recommendations match - clear a filter.</div>
</main>
</div>
<script>
const $=s=>document.querySelector(s);
const feed=$('#feed'), moreBtn=$('#more'), emptyEl=$('#empty');
const LIMIT=50;
let type='', sort='score', offset=0, loading=false;
const tagState={};          // committed tag filters: tag -> 'by' | 'out'
let pendingTags=new Set();  // genre-dropdown working set; committed to tagState on Save
let labelFilter=null;       // {id, name}
let facetTags=[];           // [{value,label,count}] genres present in current recs

function esc(s){ return (s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
// The bandcamp page handle from a release URL (e.g. digitalshamansrecordsofficial.bandcamp.com → the label/page).
function bcHandle(url){ try{ const m=new URL(url).hostname.match(/^([^.]+)\\.bandcamp\\.com$/i); return (m&&m[1]!=='www')?m[1]:''; }catch(e){ return ''; } }

function filterParams(){
  const q=new URLSearchParams();
  if(type) q.set('item_type',type);
  for(const [t,m] of Object.entries(tagState)){ if(m==='by') q.append('tag',t); else if(m==='out') q.append('exclude_tag',t); }
  if(labelFilter) q.set('label_id', labelFilter.id);
  return q;
}
function query(){ const q=filterParams(); q.set('sort',sort); q.set('limit',LIMIT); q.set('offset',offset); return q; }
async function updateCount(){
  const n=(await (await fetch('/api/recommendations/count?'+filterParams())).json()).count;
  const kind = type ? (type==='album'?'albums':'tracks') : 'results';
  const filtered = filterParams().toString().length>0;
  $('#count').innerHTML = `<b>${n.toLocaleString()}</b> ${kind}${filtered?' match your filters':''}`;
}

async function loadFacets(){
  const f=await (await fetch('/api/facets')).json();
  facetTags = f.tags;                       // ordered by count desc from the API
  renderGenreList($('#genreSearch').value||'');
  updateGenreBtn();
}
function updateGenreBtn(){
  const n=Object.keys(tagState).length;
  $('#genreBtn').textContent = n ? `Genres (${n}) ▾` : '＋ Genre filter';
}
function renderGenreList(q){
  q=(q||'').trim().toLowerCase();
  const rows = facetTags.filter(t=>t.label.toLowerCase().includes(q));
  const list=$('#genreList');
  if(!facetTags.length){ list.innerHTML='<div class="ddempty">No genre tags yet - crawl more album pages.</div>'; return; }
  list.innerHTML = rows.length
    ? rows.map(t=>{const sel=pendingTags.has(t.value);
        return `<div class="ddrow ${sel?'sel':''}" data-tag="${esc(t.value)}">
          <span class="box">✓</span><span class="nm">${esc(t.label)}</span><span class="cnt">${t.count.toLocaleString()}</span></div>`;}).join('')
    : '<div class="ddempty">No genres match "'+esc(q)+'".</div>';
}
// open the dropdown: seed the working set from the committed filters
function openGenre(){
  pendingTags = new Set(Object.keys(tagState));
  $('#genreSearch').value=''; renderGenreList(''); updateSaveBtn();
  $('#genrePanel').style.display='block'; $('#genreSearch').focus();
}
function updateSaveBtn(){ const n=pendingTags.size; $('#genreSave').textContent = n?`Save (${n})`:'Save'; }
// commit the working set: new tags become includes; deselected ones drop; existing include/exclude kept
function saveGenres(){
  for(const t of Object.keys(tagState)) if(!pendingTags.has(t)) delete tagState[t];
  for(const t of pendingTags) if(tagState[t]===undefined) tagState[t]='by';
  $('#genrePanel').style.display='none'; refresh();
}
function renderActive(){
  const bits=[];
  for(const [t,m] of Object.entries(tagState))
    bits.push(`<span class="fpill ${m==='out'?'out':''}"><span class="tog" data-tog="${esc(t)}" title="click to switch include / exclude">${m==='out'?'⊘ exclude':'✓ include'}: <b>${esc(t)}</b></span><span class="rm" data-rmtag="${esc(t)}" title="remove">×</span></span>`);
  if(labelFilter) bits.push(`<span class="fpill"><span class="tog">label: <b>${esc(labelFilter.name)}</b></span><span class="rm" data-clear-label="1" title="remove">×</span></span>`);
  $('#active').innerHTML=bits.join('');
}

function card(r){
  const tags=(r.reasons.matched_tags||[]).map(t=>`<span class="chip tag" data-tag="${esc(t)}">${esc(t)}</span>`).join('');
  const co=r.reasons.co_owners||0;
  const hnd=bcHandle(r.url);
  return `<div class="card">
    <div class="score"><b>${r.score.toFixed(1)}</b><span>score</span></div>
    <div class="body">
      <div class="title">${esc(r.title)||'-'}<span class="type">${r.item_type}</span></div>
      <div class="band" data-label="${r.band_id||''}" data-name="${esc(r.band_name)}">${esc(r.band_name)||'unknown artist'}${hnd?`<span class="handle">${esc(hnd)}</span>`:''}</div>
      <div class="meta">
        <span class="chip">${co} neighbour${co===1?'':'s'} own this</span>
        ${tags}
        ${(r.reasons.seed_tags||[]).length?`<span class="chip" title="genres of your albums that surfaced this">via ${esc((r.reasons.seed_tags||[]).slice(0,3).join(', '))}</span>`:''}
      </div>
      <div class="actions">
        <button class="act like" data-like-album="${r.album_id||''}" data-like-track="${r.track_id||''}">♥ like</button>
        ${r.band_id?`<button class="act block" data-block="${r.band_id}" data-bname="${esc(r.band_name)}">⊘ block</button>`:''}
        ${r.url?`<a class="listen" href="${esc(r.url)}" target="_blank" rel="noopener">Bandcamp ↗</a>`:''}
      </div>
    </div>
  </div>`;
}

async function loadPage(reset){
  if(loading) return; loading=true; moreBtn.disabled=true;
  if(reset){ offset=0; feed.innerHTML=''; updateCount(); }
  const rows=await (await fetch('/api/recommendations?'+query())).json();
  feed.insertAdjacentHTML('beforeend', rows.map(card).join(''));
  offset+=rows.length;
  emptyEl.style.display=(offset===0)?'block':'none';
  moreBtn.style.display=(rows.length===LIMIT)?'block':'none';
  loading=false; moreBtn.disabled=false;
}
function refresh(){ renderGenreList($('#genreSearch').value||''); updateGenreBtn(); renderActive(); loadPage(true); }

// ── events ──
$('#filter').addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b)return;
  [...e.currentTarget.children].forEach(x=>x.classList.remove('on')); b.classList.add('on'); type=b.dataset.t; loadPage(true); });
// sort dropdown (custom, single-select)
const SORTS={score:'Top score',neighbours:'Most owners',affinity:'Genre match'};
function renderSortLabel(){ $('#sortBtn').textContent='Sort · '+SORTS[sort]+' ▾';
  document.querySelectorAll('#sortPanel .ddrow').forEach(r=>r.classList.toggle('sel',r.dataset.sort===sort)); }
$('#sortBtn').addEventListener('click',e=>{ e.stopPropagation(); const p=$('#sortPanel');
  p.style.display=p.style.display==='none'?'block':'none'; });
$('#sortPanel').addEventListener('click',e=>{ const r=e.target.closest('.ddrow'); if(!r)return;
  sort=r.dataset.sort; renderSortLabel(); $('#sortPanel').style.display='none'; loadPage(true); });
// genre dropdown: searchable, count-ordered, multi-select (AND)
$('#genreBtn').addEventListener('click',e=>{ e.stopPropagation(); const p=$('#genrePanel');
  if(p.style.display==='none') openGenre(); else p.style.display='none'; });
$('#genreSearch').addEventListener('input',e=>renderGenreList(e.target.value));
// toggle selection in the working set only - no feed reload until Save
$('#genreList').addEventListener('click',e=>{ const r=e.target.closest('.ddrow'); if(!r)return;
  const t=r.dataset.tag; if(pendingTags.has(t)) pendingTags.delete(t); else pendingTags.add(t);
  r.classList.toggle('sel',pendingTags.has(t)); updateSaveBtn(); });
$('#genreSave').addEventListener('click',e=>{ e.stopPropagation(); saveGenres(); });
$('#genreClear').addEventListener('click',e=>{ e.stopPropagation();
  pendingTags.clear(); renderGenreList($('#genreSearch').value||''); updateSaveBtn(); });
document.addEventListener('click',e=>{
  if(!e.target.closest('#genreDd')) $('#genrePanel').style.display='none';
  if(!e.target.closest('#sortDd')) $('#sortPanel').style.display='none';
});
$('#active').addEventListener('click',e=>{
  const rm=e.target.closest('[data-rmtag]'); const cl=e.target.closest('[data-clear-label]'); const tog=e.target.closest('[data-tog]');
  if(rm){ delete tagState[rm.dataset.rmtag]; refresh(); return; }
  if(cl){ labelFilter=null; refresh(); return; }
  if(tog){ const t=tog.dataset.tog; if(t){ tagState[t]= tagState[t]==='out'?'by':'out'; refresh(); } }});
feed.addEventListener('click',async e=>{
  const tag=e.target.closest('.chip.tag'); if(tag){ tagState[tag.dataset.tag]='by'; refresh(); return; }
  const band=e.target.closest('.band'); if(band && band.dataset.label){ labelFilter={id:band.dataset.label,name:band.dataset.name}; refresh(); return; }
  const blk=e.target.closest('[data-block]'); if(blk){
    blk.disabled=true; const c=blk.closest('.card');
    try{
      const resp=await fetch('/api/blacklist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({band_id:+blk.dataset.block})});
      if(!resp.ok) throw new Error('block '+resp.status);
      c.classList.add('blocking');   // implode + red flash - only after the server confirms
      setTimeout(()=>{ c.remove(); updateCount(); }, 1300);
      await loadFacets(); await loadBlocked();
    }catch(err){ blk.disabled=false; console.error('block failed:', err); }
    return;
  }
  const lk=e.target.closest('[data-like-album],[data-like-track]'); if(lk){
    lk.disabled=true; const c=lk.closest('.card');
    const body=lk.dataset.likeAlbum?{album_id:+lk.dataset.likeAlbum}:{track_id:+lk.dataset.likeTrack};
    try{
      const resp=await fetch('/api/likes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!resp.ok) throw new Error('like '+resp.status);
      c.classList.add('liking');     // swipe-right + teal flash - only after the server confirms
      setTimeout(()=>{ c.remove(); updateCount(); }, 1300);
      await loadFacets(); await loadLiked();
    }catch(err){ lk.disabled=false; console.error('like failed:', err); }
  }
});
moreBtn.addEventListener('click',()=>loadPage(false));

// ── blocked panel ──
const panel=$('#blockedPanel'); let panelOpen=false;
async function loadBlocked(){
  const rows=await (await fetch('/api/blacklist')).json();
  $('#blockedBtn').textContent=`Blocked (${rows.length})`;
  panel.innerHTML = rows.length
    ? '<div class="hint">Blocked artists / labels - these never appear in the feed:</div>'+rows.map(b=>
        `<div class="brow"><div class="grow"><b>${esc(b.band_name)||b.band_id}</b>${b.band_url?` <span class="hint">${esc(b.band_url)}</span>`:''}</div>
         <button class="act" data-unblock="${b.band_id}">unblock</button></div>`).join('')
    : '<div class="hint">Nothing blocked yet. Use "⊘ block" on a card.</div>';
}
$('#blockedBtn').addEventListener('click',async()=>{ panelOpen=!panelOpen; panel.style.display=panelOpen?'block':'none';
  $('#blockedBtn').classList.toggle('on',panelOpen); if(panelOpen) await loadBlocked(); });
panel.addEventListener('click',async e=>{ const u=e.target.closest('[data-unblock]'); if(!u)return;
  u.disabled=true; await fetch('/api/blacklist/'+u.dataset.unblock+'/unblock',{method:'POST'});
  await loadBlocked(); });

// ── liked panel ──
const lpanel=$('#likedPanel'); let lpanelOpen=false;
async function loadLiked(){
  const rows=await (await fetch('/api/likes')).json();
  $('#likedBtn').textContent=`♥ Liked (${rows.length})`;
  lpanel.innerHTML = rows.length
    ? '<div class="hint">Liked - kept out of the feed (your next crawl reflects the real wishlist/purchase/follow):</div>'+rows.map(r=>
        `<div class="brow"><div class="grow"><b>${esc(r.title)||r.item_type}</b> <span class="hint">${esc(r.band_name)||''}</span></div>
         ${r.url?`<a class="listen" href="${esc(r.url)}" target="_blank" rel="noopener">↗</a>`:''}
         <button class="act" data-unlike-album="${r.album_id||''}" data-unlike-track="${r.track_id||''}">unlike</button></div>`).join('')
    : '<div class="hint">Nothing liked yet. Use "♥ like" on a card once you\\'ve wishlisted/bought/followed it.</div>';
}
$('#likedBtn').addEventListener('click',async()=>{ lpanelOpen=!lpanelOpen; lpanel.style.display=lpanelOpen?'block':'none';
  $('#likedBtn').classList.toggle('on',lpanelOpen); if(lpanelOpen) await loadLiked(); });
lpanel.addEventListener('click',async e=>{ const u=e.target.closest('[data-unlike-album],[data-unlike-track]'); if(!u)return;
  u.disabled=true;
  const body=u.dataset.unlikeAlbum?{album_id:+u.dataset.unlikeAlbum}:{track_id:+u.dataset.unlikeTrack};
  await fetch('/api/likes/unlike',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  await loadLiked(); });

renderSortLabel(); loadFacets(); loadBlocked(); loadLiked(); loadPage(true);
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _PAGE
