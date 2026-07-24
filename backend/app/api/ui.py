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
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  a { color:inherit; }
  header { padding:28px 20px 16px; max-width:900px; margin:0 auto; }
  h1 { margin:0; font-size:26px; letter-spacing:-.02em; }
  h1 .dot { color:var(--accent); }
  .sub { color:var(--muted); margin-top:4px; font-size:13px; }
  .stats { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
  .stat { background:var(--panel); border:1px solid var(--line); border-radius:10px;
    padding:8px 12px; font-size:12px; color:var(--muted); }
  .stat b { color:var(--text); font-size:15px; display:block; }
  .controls { display:flex; gap:8px; align-items:center; flex-wrap:wrap;
    max-width:900px; margin:8px auto 0; padding:0 20px; }
  .seg { display:flex; background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  .seg button { background:none; border:0; color:var(--muted); padding:7px 14px; cursor:pointer; font-size:13px; }
  .seg button.on { background:var(--panel2); color:var(--accent); }
  .spacer { flex:1; }
  .btn { background:var(--accent); color:#06231e; border:0; border-radius:10px;
    padding:8px 14px; font-weight:600; cursor:pointer; font-size:13px; }
  .btn:disabled { opacity:.5; cursor:default; }
  main { max-width:900px; margin:16px auto 60px; padding:0 20px; }
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
  .band { color:var(--muted); font-size:13px; margin-top:2px; }
  .meta { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; font-size:12px; color:var(--muted); }
  .chip { background:var(--panel2); border:1px solid var(--line); border-radius:999px; padding:2px 9px; color:var(--text); }
  .chip.tag { color:var(--accent); }
  .listen { margin-left:auto; color:var(--accent); text-decoration:none; font-weight:600; white-space:nowrap; }
  .listen:hover { text-decoration:underline; }
  .empty { color:var(--muted); text-align:center; padding:50px 0; }
  .more { display:block; margin:16px auto 0; }
</style>
</head>
<body>
<header>
  <h1>crate<span class="dot">·</span>digger</h1>
  <div class="sub">Music your collection's supporters own that you don't — ranked.</div>
  <div class="stats" id="stats"></div>
</header>
<div class="controls">
  <div class="seg" id="filter">
    <button data-t="" class="on">All</button>
    <button data-t="album">Albums</button>
    <button data-t="track">Tracks</button>
  </div>
  <div class="spacer"></div>
  <button class="btn" id="recompute">↻ Recompute</button>
</div>
<main>
  <div id="feed"></div>
  <button class="btn more" id="more" style="display:none">Load more</button>
  <div class="empty" id="empty" style="display:none">No recommendations yet — seed &amp; crawl, then Recompute.</div>
</main>
<script>
const feed=document.getElementById('feed'), moreBtn=document.getElementById('more'),
      emptyEl=document.getElementById('empty');
let type='', offset=0, loading=false; const LIMIT=50;

function esc(s){ return (s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function loadStats(){
  const s=await (await fetch('/api/stats')).json();
  const cell=(v,l)=>`<div class="stat"><b>${v.toLocaleString()}</b>${l}</div>`;
  document.getElementById('stats').innerHTML =
    cell(s.recommendations,'recommendations')+cell(s.neighbours,'taste-neighbours')+
    cell(s.my_owned,'you own')+cell(s.my_wishlist,'wishlist')+cell(s.follows,'follows')+
    cell(s.requests_used+' / '+s.request_budget,'crawl budget');
}

function card(r){
  const tags=(r.reasons.matched_tags||[]).map(t=>`<span class="chip tag">${esc(t)}</span>`).join('');
  const co=r.reasons.co_owners||0;
  return `<div class="card">
    <div class="rank">${r.rank}</div>
    <div class="score"><b>${r.score.toFixed(1)}</b><span>score</span></div>
    <div class="body">
      <div class="title">${esc(r.title)||'—'}<span class="type">${r.item_type}</span></div>
      <div class="band">${esc(r.band_name)||'unknown artist'}</div>
      <div class="meta">
        <span class="chip">${co} neighbour${co===1?'':'s'} own this</span>
        ${tags}
        ${r.url?`<a class="listen" href="${esc(r.url)}" target="_blank" rel="noopener">Listen on Bandcamp ↗</a>`:''}
      </div>
    </div>
  </div>`;
}

async function loadPage(reset){
  if(loading) return; loading=true; moreBtn.disabled=true;
  if(reset){ offset=0; feed.innerHTML=''; }
  const q=new URLSearchParams({limit:LIMIT, offset}); if(type) q.set('item_type',type);
  const rows=await (await fetch('/api/recommendations?'+q)).json();
  feed.insertAdjacentHTML('beforeend', rows.map(card).join(''));
  offset+=rows.length;
  emptyEl.style.display = (offset===0)?'block':'none';
  moreBtn.style.display = (rows.length===LIMIT)?'block':'none';
  loading=false; moreBtn.disabled=false;
}

document.getElementById('filter').addEventListener('click', e=>{
  const b=e.target.closest('button'); if(!b) return;
  [...e.currentTarget.children].forEach(x=>x.classList.remove('on')); b.classList.add('on');
  type=b.dataset.t; loadPage(true);
});
moreBtn.addEventListener('click',()=>loadPage(false));
document.getElementById('recompute').addEventListener('click', async e=>{
  e.target.disabled=true; e.target.textContent='Recomputing…';
  await fetch('/api/recommendations/recompute',{method:'POST'});
  await loadStats(); await loadPage(true);
  e.target.disabled=false; e.target.textContent='↻ Recompute';
});

loadStats(); loadPage(true);
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _PAGE
