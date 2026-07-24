"""Serves the crate-digger feed UI — a single self-contained page (no build step)
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
<title>crate-digger</title>
<style>
  :root {
    --bg:#0f1115; --panel:#171a21; --panel2:#1e222c; --line:#282d38;
    --text:#e7e9ee; --muted:#9aa3b2; --accent:#5eead4; --accent2:#f0abfc;
    --danger:#fb7185;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  a { color:inherit; }
  .wrap { max-width:900px; margin:0 auto; padding:0 20px; }
  header { padding:28px 0 12px; }
  h1 { margin:0; font-size:26px; letter-spacing:-.02em; }
  h1 .dot { color:var(--accent); }
  .sub { color:var(--muted); margin-top:4px; font-size:13px; }
  .stats { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
  .stat { background:var(--panel); border:1px solid var(--line); border-radius:10px;
    padding:8px 12px; font-size:12px; color:var(--muted); }
  .stat b { color:var(--text); font-size:15px; display:block; }
  .controls { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:12px; }
  .seg { display:flex; background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  .seg button { background:none; border:0; color:var(--muted); padding:7px 14px; cursor:pointer; font-size:13px; }
  .seg button.on { background:var(--panel2); color:var(--accent); }
  .spacer { flex:1; }
  .btn { background:var(--accent); color:#06231e; border:0; border-radius:10px;
    padding:8px 14px; font-weight:600; cursor:pointer; font-size:13px; }
  .btn.ghost { background:var(--panel); color:var(--muted); border:1px solid var(--line); }
  .btn:disabled { opacity:.5; cursor:default; }
  .hint { color:var(--muted); font-size:12px; margin:12px 0 4px; }
  .tagbar { display:flex; gap:6px; overflow-x:auto; padding:6px 0 2px; }
  .tagbar::-webkit-scrollbar { height:6px; } .tagbar::-webkit-scrollbar-thumb { background:var(--line); border-radius:3px; }
  .tchip { white-space:nowrap; background:var(--panel); border:1px solid var(--line); color:var(--muted);
    border-radius:999px; padding:4px 11px; font-size:12px; cursor:pointer; }
  .tchip.by { border-color:var(--accent); color:var(--accent); }
  .tchip.out { border-color:var(--danger); color:var(--danger); text-decoration:line-through; }
  .tchip .n { opacity:.6; margin-left:4px; }
  .active { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-top:8px; min-height:0; }
  .fpill { font-size:12px; background:var(--panel2); border:1px solid var(--line); border-radius:999px;
    padding:3px 8px; color:var(--text); cursor:pointer; }
  .fpill b { color:var(--accent); } .fpill.out b { color:var(--danger); }
  main { margin:12px 0 60px; }
  .card { display:flex; gap:14px; align-items:flex-start; background:var(--panel);
    border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin-bottom:10px; }
  .rank { color:var(--muted); font-variant-numeric:tabular-nums; min-width:28px; font-size:13px; padding-top:3px; }
  .score { min-width:52px; text-align:center; }
  .score b { display:block; font-size:18px; color:var(--accent); font-variant-numeric:tabular-nums; }
  .score span { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; }
  .body { flex:1; min-width:0; }
  .title { font-weight:600; }
  .title .type { font-size:10px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--accent2); border:1px solid var(--line); border-radius:6px; padding:1px 5px; margin-left:8px; }
  .band { color:var(--muted); font-size:13px; margin-top:2px; cursor:pointer; }
  .band:hover { color:var(--accent); text-decoration:underline; }
  .meta { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; font-size:12px; color:var(--muted); }
  .chip { background:var(--panel2); border:1px solid var(--line); border-radius:999px; padding:2px 9px; color:var(--text); }
  .chip.tag { color:var(--accent); cursor:pointer; }
  .grow { flex:1; }
  .block { background:none; border:1px solid var(--line); color:var(--muted); border-radius:8px;
    padding:3px 9px; font-size:12px; cursor:pointer; }
  .block:hover { border-color:var(--danger); color:var(--danger); }
  .like { background:none; border:1px solid var(--line); color:var(--muted); border-radius:8px;
    padding:3px 9px; font-size:12px; cursor:pointer; }
  .like:hover { border-color:var(--accent); color:var(--accent); }
  .listen { color:var(--accent); text-decoration:none; font-weight:600; white-space:nowrap; }
  .listen:hover { text-decoration:underline; }
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
  <h1>crate<span class="dot">·</span>digger</h1>
  <div class="sub">Music your collection's supporters own that you don't — one per artist, ranked.</div>
  <div class="stats" id="stats"></div>
</header>
<div class="controls">
  <div class="seg" id="filter">
    <button data-t="" class="on">All</button>
    <button data-t="album">Albums</button>
    <button data-t="track">Tracks</button>
  </div>
  <div class="spacer"></div>
  <button class="btn ghost" id="likedBtn">♥ Liked (0)</button>
  <button class="btn ghost" id="blockedBtn">Blocked (0)</button>
  <button class="btn" id="recompute">↻ Recompute</button>
</div>
<div class="hint">Filter by genre — click once to <b style="color:var(--accent)">include</b>, twice to <b style="color:var(--danger)">exclude</b>:</div>
<div class="tagbar" id="tagbar"></div>
<div class="hint" id="seedHint" style="display:none">Hide recs generated from your own <b>seed genres</b> (click to exclude; recomputes):</div>
<div class="tagbar" id="seedbar"></div>
<div class="active" id="active"></div>
<div class="panel" id="likedPanel" style="display:none"></div>
<div class="panel" id="blockedPanel" style="display:none"></div>
<main>
  <div id="feed"></div>
  <button class="btn more" id="more" style="display:none">Load more</button>
  <div class="empty" id="empty" style="display:none">No recommendations match — clear a filter, or Recompute.</div>
</main>
</div>
<script>
const $=s=>document.querySelector(s);
const feed=$('#feed'), moreBtn=$('#more'), emptyEl=$('#empty');
const LIMIT=50;
let type='', offset=0, loading=false;
const tagState={};          // tag -> 'by' | 'out'
let labelFilter=null;       // {id, name}
const seedExclude=new Set();// seed genres to exclude at recompute time

function esc(s){ return (s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function query(){
  const q=new URLSearchParams(); q.set('limit',LIMIT); q.set('offset',offset);
  if(type) q.set('item_type',type);
  for(const [t,m] of Object.entries(tagState)){ if(m==='by') q.append('tag',t); else if(m==='out') q.append('exclude_tag',t); }
  if(labelFilter) q.set('label_id', labelFilter.id);
  return q;
}

async function loadStats(){
  const s=await (await fetch('/api/stats')).json();
  const cell=(v,l)=>`<div class="stat"><b>${(''+v).replace(/\\B(?=(\\d{3})+(?!\\d))/g,',')}</b>${l}</div>`;
  $('#stats').innerHTML = cell(s.recommendations,'recommendations')+cell(s.neighbours,'taste-neighbours')+
    cell(s.my_owned,'you own')+cell(s.my_wishlist,'wishlist')+cell(s.follows,'follows')+
    cell(s.liked,'liked')+cell(s.requests_used+' / '+s.request_budget,'crawl budget');
}

async function loadFacets(){
  const f=await (await fetch('/api/facets')).json();
  $('#tagbar').innerHTML = f.tags.length
    ? f.tags.map(t=>`<span class="tchip" data-tag="${esc(t.value)}">${esc(t.label)}<span class="n">${t.count}</span></span>`).join('')
    : '<span class="hint">No genre tags on recommendations yet — crawl more album pages to populate them.</span>';
  $('#seedHint').style.display = f.seed_tags.length ? 'block' : 'none';
  $('#seedbar').innerHTML = f.seed_tags.map(t=>
    `<span class="tchip seed" data-seed="${esc(t.value)}">${esc(t.label)}<span class="n">${t.count}</span></span>`).join('');
  renderTagStates();
}
function renderTagStates(){
  document.querySelectorAll('.tchip[data-tag]').forEach(c=>{
    const m=tagState[c.dataset.tag]; c.classList.toggle('by',m==='by'); c.classList.toggle('out',m==='out');
  });
  document.querySelectorAll('.tchip.seed').forEach(c=> c.classList.toggle('out', seedExclude.has(c.dataset.seed)));
}
async function recompute(){
  const q=new URLSearchParams(); seedExclude.forEach(t=>q.append('exclude_seed_tag',t));
  await fetch('/api/recommendations/recompute?'+q,{method:'POST'});
  await loadStats(); await loadFacets(); loadPage(true);
}
function renderActive(){
  const bits=[];
  for(const [t,m] of Object.entries(tagState))
    bits.push(`<span class="fpill ${m==='out'?'out':''}" data-clear-tag="${esc(t)}">${m==='out'?'exclude':'genre'}: <b>${esc(t)}</b> ✕</span>`);
  if(labelFilter) bits.push(`<span class="fpill" data-clear-label="1">label: <b>${esc(labelFilter.name)}</b> ✕</span>`);
  $('#active').innerHTML=bits.join('');
}

function card(r){
  const tags=(r.reasons.matched_tags||[]).map(t=>`<span class="chip tag" data-tag="${esc(t)}">${esc(t)}</span>`).join('');
  const co=r.reasons.co_owners||0;
  return `<div class="card">
    <div class="rank">${r.rank}</div>
    <div class="score"><b>${r.score.toFixed(1)}</b><span>score</span></div>
    <div class="body">
      <div class="title">${esc(r.title)||'—'}<span class="type">${r.item_type}</span></div>
      <div class="band" data-label="${r.band_id||''}" data-name="${esc(r.band_name)}">${esc(r.band_name)||'unknown artist'}</div>
      <div class="meta">
        <span class="chip">${co} neighbour${co===1?'':'s'} own this</span>
        ${tags}
        ${(r.reasons.seed_tags||[]).length?`<span class="chip" title="genres of your albums that surfaced this">via ${esc((r.reasons.seed_tags||[]).slice(0,3).join(', '))}</span>`:''}
        <span class="grow"></span>
        <button class="like" data-like-album="${r.album_id||''}" data-like-track="${r.track_id||''}">♥ like</button>
        ${r.band_id?`<button class="block" data-block="${r.band_id}" data-bname="${esc(r.band_name)}">⊘ block</button>`:''}
        ${r.url?`<a class="listen" href="${esc(r.url)}" target="_blank" rel="noopener">Bandcamp ↗</a>`:''}
      </div>
    </div>
  </div>`;
}

async function loadPage(reset){
  if(loading) return; loading=true; moreBtn.disabled=true;
  if(reset){ offset=0; feed.innerHTML=''; }
  const rows=await (await fetch('/api/recommendations?'+query())).json();
  feed.insertAdjacentHTML('beforeend', rows.map(card).join(''));
  offset+=rows.length;
  emptyEl.style.display=(offset===0)?'block':'none';
  moreBtn.style.display=(rows.length===LIMIT)?'block':'none';
  loading=false; moreBtn.disabled=false;
}
function refresh(){ renderTagStates(); renderActive(); loadPage(true); }

// ── events ──
$('#filter').addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b)return;
  [...e.currentTarget.children].forEach(x=>x.classList.remove('on')); b.classList.add('on'); type=b.dataset.t; loadPage(true); });
$('#tagbar').addEventListener('click',e=>{ const c=e.target.closest('.tchip'); if(!c)return;
  const t=c.dataset.tag, m=tagState[t]; if(!m) tagState[t]='by'; else if(m==='by') tagState[t]='out'; else delete tagState[t]; refresh(); });
$('#seedbar').addEventListener('click',async e=>{ const c=e.target.closest('.tchip.seed'); if(!c)return;
  const t=c.dataset.seed; if(seedExclude.has(t)) seedExclude.delete(t); else seedExclude.add(t);
  c.classList.toggle('out',seedExclude.has(t)); await recompute(); });
$('#active').addEventListener('click',e=>{ const p=e.target.closest('[data-clear-tag]'); const l=e.target.closest('[data-clear-label]');
  if(p){ delete tagState[p.dataset.clearTag]; refresh(); } if(l){ labelFilter=null; refresh(); } });
feed.addEventListener('click',async e=>{
  const tag=e.target.closest('.chip.tag'); if(tag){ tagState[tag.dataset.tag]='by'; refresh(); return; }
  const band=e.target.closest('.band'); if(band && band.dataset.label){ labelFilter={id:band.dataset.label,name:band.dataset.name}; refresh(); return; }
  const blk=e.target.closest('[data-block]'); if(blk){
    blk.disabled=true; await fetch('/api/blacklist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({band_id:+blk.dataset.block})});
    await loadStats(); await loadBlocked(); loadPage(true); return;
  }
  const lk=e.target.closest('[data-like-album],[data-like-track]'); if(lk){
    lk.disabled=true;
    const body=lk.dataset.likeAlbum?{album_id:+lk.dataset.likeAlbum}:{track_id:+lk.dataset.likeTrack};
    await fetch('/api/likes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    lk.closest('.card').remove(); await loadStats(); await loadLiked();
  }
});
moreBtn.addEventListener('click',()=>loadPage(false));
$('#recompute').addEventListener('click',async e=>{ e.target.disabled=true; e.target.textContent='Recomputing…';
  await recompute(); e.target.disabled=false; e.target.textContent='↻ Recompute'; });

// ── blocked panel ──
const panel=$('#blockedPanel'); let panelOpen=false;
async function loadBlocked(){
  const rows=await (await fetch('/api/blacklist')).json();
  $('#blockedBtn').textContent=`Blocked (${rows.length})`;
  panel.innerHTML = rows.length
    ? '<div class="hint">Blocked artists / labels — these never appear in the feed:</div>'+rows.map(b=>
        `<div class="brow"><div class="grow"><b>${esc(b.band_name)||b.band_id}</b>${b.band_url?` <span class="hint">${esc(b.band_url)}</span>`:''}</div>
         <button class="block" data-unblock="${b.band_id}">unblock</button></div>`).join('')
    : '<div class="hint">Nothing blocked yet. Use “⊘ block” on a card.</div>';
}
$('#blockedBtn').addEventListener('click',async()=>{ panelOpen=!panelOpen; panel.style.display=panelOpen?'block':'none'; if(panelOpen) await loadBlocked(); });
panel.addEventListener('click',async e=>{ const u=e.target.closest('[data-unblock]'); if(!u)return;
  u.disabled=true; await fetch('/api/blacklist/'+u.dataset.unblock+'/unblock',{method:'POST'});
  await loadBlocked(); await loadStats(); });

// ── liked panel ──
const lpanel=$('#likedPanel'); let lpanelOpen=false;
async function loadLiked(){
  const rows=await (await fetch('/api/likes')).json();
  $('#likedBtn').textContent=`♥ Liked (${rows.length})`;
  lpanel.innerHTML = rows.length
    ? '<div class="hint">Liked — kept out of the feed (your next crawl reflects the real wishlist/purchase/follow):</div>'+rows.map(r=>
        `<div class="brow"><div class="grow"><b>${esc(r.title)||r.item_type}</b> <span class="hint">${esc(r.band_name)||''}</span></div>
         ${r.url?`<a class="listen" href="${esc(r.url)}" target="_blank" rel="noopener">↗</a>`:''}
         <button class="block" data-unlike-album="${r.album_id||''}" data-unlike-track="${r.track_id||''}">unlike</button></div>`).join('')
    : '<div class="hint">Nothing liked yet. Use “♥ like” on a card once you\\'ve wishlisted/bought/followed it.</div>';
}
$('#likedBtn').addEventListener('click',async()=>{ lpanelOpen=!lpanelOpen; lpanel.style.display=lpanelOpen?'block':'none'; if(lpanelOpen) await loadLiked(); });
lpanel.addEventListener('click',async e=>{ const u=e.target.closest('[data-unlike-album],[data-unlike-track]'); if(!u)return;
  u.disabled=true;
  const body=u.dataset.unlikeAlbum?{album_id:+u.dataset.unlikeAlbum}:{track_id:+u.dataset.unlikeTrack};
  await fetch('/api/likes/unlike',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  await loadLiked(); await loadStats(); });

loadStats(); loadFacets(); loadBlocked(); loadLiked(); loadPage(true);
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _PAGE
