"""Serves the crate-digger feed UI - a self-contained SPA (no build step) that
talks to the /api JSON endpoints on the same origin. Two views: a scan list
(landing) and a scan's ranked feed (drill-in). Blocked/liked are shared globally.
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
  :root{
    --bg:#0b0d12; --panel:#141924; --panel2:#1a2030; --panel3:#212838;
    --line:#293142; --line2:#38425a;
    --text:#eef1f7; --muted:#9aa4b6; --faint:#6a7488;
    --accent:#5eead4; --accent-ink:#04241d; --accent2:#c4b5fd;
    --orange:#ffb168; --danger:#fb7185;
  }
  *{ box-sizing:border-box; }
  body{ margin:0; color:var(--text);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:
      radial-gradient(1100px 520px at 10% -10%, rgba(94,234,212,.10), transparent 60%),
      radial-gradient(900px 520px at 100% -4%, rgba(196,181,253,.09), transparent 55%),
      var(--bg); }
  a{ color:inherit; }
  .wrap{ max-width:760px; margin:0 auto; padding:0 20px; }
  header{ padding:32px 0 6px; }
  h1{ margin:0; font-size:32px; font-weight:800; letter-spacing:-.025em; line-height:1.05; }
  h1 .hl{ background:linear-gradient(95deg,var(--accent),var(--accent2));
    -webkit-background-clip:text; background-clip:text; color:transparent; }
  .sub{ margin-top:9px; font-size:16px; font-weight:500; color:var(--orange); opacity:.95; }

  .btn{ background:linear-gradient(180deg,var(--accent),#37d3bd); color:var(--accent-ink); border:0;
    border-radius:11px; padding:10px 16px; font-weight:700; cursor:pointer; font-size:13.5px; }
  .btn.ghost{ background:var(--panel); color:var(--muted); border:1px solid var(--line); font-weight:600; }
  .btn.ghost.on{ background:var(--panel2); color:var(--accent); border-color:var(--accent); }
  .btn:disabled{ opacity:.5; cursor:default; }

  /* ── scan list ── */
  .scanhead{ display:flex; align-items:center; justify-content:space-between; margin-top:30px; margin-bottom:14px; }
  .vh{ margin:0; font-size:13px; text-transform:uppercase; letter-spacing:.13em; color:var(--faint); font-weight:700; }
  .cards{ display:flex; flex-direction:column; gap:12px; }
  .scan{ position:relative; display:flex; gap:14px; align-items:flex-start; overflow:hidden; cursor:pointer;
    background:linear-gradient(180deg,rgba(255,255,255,.02),transparent 40%),var(--panel);
    border:1px solid var(--line); border-radius:16px; padding:16px 18px;
    transition:border-color .16s, transform .16s, box-shadow .16s; }
  .scan:hover{ border-color:var(--line2); transform:translateY(-1px); box-shadow:0 16px 36px -20px rgba(0,0,0,.75); }
  .scan::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--faint); }
  .scan.done::before{ background:linear-gradient(var(--accent),#2dd4bf); }
  .scan.running::before{ background:linear-gradient(var(--orange),#f59e42); }
  .scan.queued::before{ background:var(--line2); }
  .scan.error::before{ background:var(--danger); }
  .scan .ico{ flex:none; width:42px; height:42px; border-radius:12px; display:grid; place-items:center;
    background:var(--panel2); border:1px solid var(--line); font-size:19px; }
  .scan.done .ico{ color:var(--accent); } .scan.running .ico{ color:var(--orange); }
  .scan.error .ico{ color:var(--danger); } .scan.queued .ico{ color:var(--muted); }
  .scan .b{ flex:1; min-width:0; }
  .scan .r1{ display:flex; align-items:center; gap:10px; }
  .scan .nm{ font-weight:700; font-size:16px; letter-spacing:-.01em; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .scan .star{ color:var(--accent2); font-size:12px; flex:none; }
  .scan .meta{ color:var(--muted); font-size:13px; margin-top:5px; }
  .scan .meta b{ color:var(--text); font-variant-numeric:tabular-nums; }
  .scan .meta .sep{ color:var(--faint); }
  .scan .meta .errtext{ color:var(--danger); }
  .badge{ margin-left:auto; flex:none; display:inline-flex; align-items:center; gap:6px; font-size:10px; font-weight:700;
    text-transform:uppercase; letter-spacing:.07em; border-radius:999px; padding:3px 10px;
    border:1px solid var(--line); color:var(--muted); background:var(--panel2); }
  .badge .dot{ width:6px; height:6px; border-radius:50%; background:currentColor; }
  .badge.done{ color:var(--accent); border-color:rgba(94,234,212,.35); }
  .badge.running{ color:var(--orange); border-color:rgba(255,177,104,.4); }
  .badge.error{ color:var(--danger); border-color:rgba(251,113,133,.4); }
  .badge.running .dot{ animation:pulse 1.1s ease-in-out infinite; }
  @keyframes pulse{ 50%{ opacity:.25; } }
  .newcard{ border:1px dashed var(--line2); background:transparent; color:var(--muted); border-radius:16px;
    padding:15px 18px; text-align:center; cursor:pointer; font-weight:600; font-size:14px; }
  .newcard:hover{ color:var(--accent); border-color:var(--accent); }

  /* ── new-scan form ── */
  .form{ background:linear-gradient(180deg,rgba(255,255,255,.02),transparent 40%),var(--panel);
    border:1px solid var(--line); border-radius:16px; padding:18px 20px; margin-bottom:12px;
    box-shadow:0 18px 40px -22px rgba(0,0,0,.75); }
  .form .fhint{ color:var(--muted); font-size:12.5px; margin-bottom:14px; }
  .lbl{ display:block; font-size:11px; text-transform:uppercase; letter-spacing:.1em; color:var(--faint); margin:0 0 6px; font-weight:700; }
  .ti{ width:100%; background:var(--panel2); border:1px solid var(--line); color:var(--text);
    border-radius:10px; padding:11px 13px; font-size:14px; outline:none; transition:border-color .15s; }
  .ti:focus{ border-color:var(--accent); } .ti::placeholder{ color:var(--faint); }
  .seedadd{ display:flex; gap:8px; margin-top:14px; } .seedadd .ti{ flex:1; }
  .seedlist{ margin:12px 0 4px; display:flex; flex-direction:column; gap:7px; }
  .seed{ display:flex; align-items:center; gap:10px; background:var(--panel2); border:1px solid var(--line);
    border-radius:10px; padding:8px 12px; font-size:13px; }
  .seed .stag{ font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--accent);
    border:1px solid rgba(94,234,212,.3); border-radius:6px; padding:1px 6px; flex:none; }
  .seed .u{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); }
  .seed .rm{ cursor:pointer; color:var(--faint); padding:0 4px; font-size:16px; }
  .seed .rm:hover{ color:var(--danger); }
  .err{ color:var(--danger); font-size:13px; margin:6px 0 0; min-height:1px; }
  .ffoot{ display:flex; justify-content:space-between; gap:8px; margin-top:16px; padding-top:14px; border-top:1px solid var(--line); }

  /* ── feed nav + banner ── */
  .feednav{ display:flex; align-items:center; gap:12px; margin-top:22px; }
  .back{ background:var(--panel2); border:1px solid var(--line); color:var(--muted); border-radius:10px;
    padding:8px 13px; font-size:13px; cursor:pointer; }
  .back:hover{ color:var(--text); border-color:var(--line2); }
  .scantitle{ font-size:21px; font-weight:800; letter-spacing:-.02em; }
  .scantitle .ktag{ font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.07em; color:var(--accent);
    border:1px solid rgba(94,234,212,.3); border-radius:999px; padding:2px 9px; margin-left:8px; vertical-align:middle; }
  .banner{ margin-top:14px; border-radius:12px; padding:12px 16px; font-size:14px;
    background:var(--panel); border:1px solid var(--line); color:var(--muted); }
  .banner.running{ border-color:rgba(255,177,104,.4); color:var(--orange); }
  .banner.error{ border-color:rgba(251,113,133,.4); color:var(--danger); }

  /* ── feed controls ── */
  .controls{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:18px; }
  .seg{ display:flex; background:var(--panel); border:1px solid var(--line); border-radius:11px; overflow:hidden; }
  .seg button{ background:none; border:0; color:var(--muted); padding:9px 17px; cursor:pointer; font-size:13.5px; }
  .seg button.on{ background:var(--panel2); color:var(--accent); }
  .ddpanel.compact{ width:210px; }
  .ddrow .tick{ width:14px; flex:none; color:transparent; font-size:11px; }
  .ddrow.sel .tick{ color:var(--accent); }
  .spacer{ flex:1; }
  .hint{ color:var(--muted); font-size:12px; margin:12px 0 4px; }
  .genrebar{ display:flex; align-items:center; gap:10px; margin-top:10px; flex-wrap:wrap; }
  .dd{ position:relative; }
  .ddpanel{ position:absolute; z-index:30; top:calc(100% + 6px); left:0; width:300px;
    background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:8px;
    box-shadow:0 10px 30px rgba(0,0,0,.45); }
  .ddsearch{ width:100%; background:var(--panel2); border:1px solid var(--line); color:var(--text);
    border-radius:8px; padding:8px 10px; font-size:13px; outline:none; }
  .ddsearch:focus{ border-color:var(--accent); }
  .ddlist{ max-height:300px; overflow-y:auto; margin-top:8px; }
  .ddlist::-webkit-scrollbar{ width:8px; } .ddlist::-webkit-scrollbar-thumb{ background:var(--line); border-radius:4px; }
  .ddrow{ display:flex; align-items:center; gap:9px; padding:6px 8px; border-radius:8px; cursor:pointer; font-size:13px; }
  .ddrow:hover{ background:var(--panel2); }
  .ddrow.sel{ color:var(--accent); }
  .ddrow .box{ width:15px; height:15px; flex:none; border:1px solid var(--line); border-radius:4px;
    display:inline-flex; align-items:center; justify-content:center; font-size:10px; color:transparent; }
  .ddrow.sel .box{ background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
  .ddrow .nm{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .ddrow .cnt{ color:var(--muted); font-variant-numeric:tabular-nums; }
  .ddempty{ color:var(--muted); font-size:12px; padding:10px 8px; }
  .ddfoot{ display:flex; justify-content:space-between; gap:8px; margin-top:8px; padding-top:8px; border-top:1px solid var(--line); }
  .ddfoot .btn{ padding:7px 14px; }
  .active{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-top:8px; min-height:0; }
  .fpill{ font-size:12px; background:var(--panel2); border:1px solid var(--line); border-radius:999px;
    padding:3px 4px 3px 9px; color:var(--text); display:inline-flex; align-items:center; gap:6px; }
  .fpill .tog{ cursor:pointer; } .fpill b{ color:var(--accent); } .fpill.out b{ color:var(--danger); }
  .fpill.out .tog{ color:var(--danger); }
  .fpill .rm{ cursor:pointer; padding:0 5px; border-radius:999px; color:var(--muted); }
  .fpill .rm:hover{ background:var(--line); color:var(--text); }

  /* ── feed cards ── */
  main{ margin:8px 0 60px; }
  .card{ position:relative; display:flex; gap:15px; align-items:flex-start; overflow:hidden;
    background:linear-gradient(180deg,rgba(255,255,255,.02),transparent 40%),var(--panel);
    border:1px solid var(--line); border-radius:15px; padding:15px 16px 15px 19px; margin-bottom:11px;
    transition:border-color .16s, transform .16s, box-shadow .16s; }
  .card:hover{ border-color:var(--line2); transform:translateY(-1px); box-shadow:0 16px 34px -22px rgba(0,0,0,.7); }
  .card::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:3px;
    background:linear-gradient(var(--accent),#2dd4bf); opacity:.28; transition:opacity .16s; }
  .card:hover::before{ opacity:.9; }
  @keyframes evaporate-like{
    0%{ opacity:1; filter:blur(0); transform:translateY(0) scale(1); max-height:400px; }
    15%{ box-shadow:0 0 0 2px var(--accent); }
    60%{ opacity:.28; filter:blur(4px); transform:translateY(-14px) scale(1.015); }
    100%{ opacity:0; filter:blur(11px); transform:translateY(-30px) scale(1.03);
      max-height:0; margin-bottom:0; padding-top:0; padding-bottom:0; border-width:0; } }
  @keyframes evaporate-block{
    0%{ opacity:1; filter:blur(0); transform:translateY(0) scale(1); max-height:400px; }
    15%{ box-shadow:0 0 0 2px var(--danger); }
    60%{ opacity:.28; filter:blur(4px); transform:translateY(-14px) scale(1.015); }
    100%{ opacity:0; filter:blur(11px); transform:translateY(-30px) scale(1.03);
      max-height:0; margin-bottom:0; padding-top:0; padding-bottom:0; border-width:0; } }
  .card.liking{ animation:evaporate-like 0.8s ease-out forwards; pointer-events:none; }
  .card.blocking{ animation:evaporate-block 0.8s ease-out forwards; pointer-events:none; }
  .score{ flex:none; width:60px; height:60px; border-radius:14px; background:var(--panel2); border:1px solid var(--line);
    display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; }
  .score b{ font-size:22px; font-weight:800; color:var(--accent); font-variant-numeric:tabular-nums; line-height:1; }
  .score span{ font-size:9px; text-transform:uppercase; letter-spacing:.09em; color:var(--faint); }
  .body{ flex:1; min-width:0; }
  .title{ font-weight:700; font-size:15.5px; }
  .title .type{ font-size:9.5px; text-transform:uppercase; letter-spacing:.08em; color:var(--accent2);
    border:1px solid var(--line); border-radius:6px; padding:1px 6px; margin-left:8px; }
  .band{ color:var(--muted); font-size:13px; margin-top:3px; cursor:pointer; }
  .band:hover{ color:var(--accent); text-decoration:underline; }
  .band .handle{ color:var(--accent2); opacity:.9; }
  .band .handle::before{ content:"·"; margin:0 6px; color:var(--faint); }
  .meta{ margin-top:9px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; font-size:12px; color:var(--muted); }
  .chip{ background:var(--panel2); border:1px solid var(--line); border-radius:999px; padding:2px 10px; color:var(--text); }
  .chip.tag{ color:var(--accent); cursor:pointer; }
  .chip.signal{ color:var(--accent); border-color:rgba(94,234,212,.32); background:rgba(94,234,212,.07); font-weight:600; }
  .actions{ margin-top:13px; display:flex; gap:8px; align-items:center; justify-content:flex-end; }
  .act{ background:none; border:1px solid var(--line); color:var(--muted); border-radius:9px;
    padding:6px 13px; font-size:13px; font-weight:500; cursor:pointer; line-height:1; }
  .like:hover{ border-color:var(--accent); color:var(--accent); }
  .block:hover{ border-color:var(--danger); color:var(--danger); }
  .listen{ color:var(--accent); text-decoration:none; font-weight:700; white-space:nowrap;
    border:1px solid var(--accent); border-radius:9px; padding:6px 13px; font-size:13px; line-height:1; }
  .listen:hover{ background:var(--accent); color:var(--accent-ink); }
  .count{ color:var(--muted); font-size:13px; margin:16px 0 12px; } .count b{ color:var(--text); font-size:16px; }
  .empty{ color:var(--muted); text-align:center; padding:50px 0; }
  .more{ display:block; margin:16px auto 0; }
  .panel{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin-top:12px; }
  .brow{ display:flex; align-items:center; gap:10px; padding:6px 0; border-bottom:1px solid var(--line); }
  .brow:last-child{ border-bottom:0; }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Bandcamp <span class="hl">suggestions</span></h1>
  <div class="sub">Discovery runs seeded by albums you love - one recommendation per artist, ranked.</div>
</header>

<!-- ══ Scan list view ══ -->
<div id="scansView">
  <div class="scanhead">
    <h2 class="vh">Your scans</h2>
    <button class="btn" id="newScanBtn">＋ New scan</button>
  </div>
  <div class="form" id="scanForm" style="display:none">
    <div class="fhint">Name it, then paste Bandcamp <b>album or track</b> URLs to seed discovery — any mix. Your Mac runs the crawl; recommendations come from those albums'/tracks' supporters.</div>
    <label class="lbl">Scan name</label>
    <input class="ti" id="scanName" placeholder="e.g. Deep forest psy dig" autocomplete="off"/>
    <div class="seedadd">
      <input class="ti" id="seedUrl" placeholder="Paste a Bandcamp album or track URL, then Add" autocomplete="off"/>
      <button class="btn ghost" id="addSeed">Add</button>
    </div>
    <div class="seedlist" id="seedList"></div>
    <div class="err" id="scanErr"></div>
    <div class="ffoot">
      <button class="btn ghost" id="cancelScan">Cancel</button>
      <button class="btn" id="createScan">Create &amp; queue</button>
    </div>
  </div>
  <div class="cards" id="scanCards"></div>
  <div class="empty" id="scansEmpty" style="display:none">No scans yet - create one from a few album URLs.</div>
</div>

<!-- ══ Feed view (one scan) ══ -->
<div id="feedView" style="display:none">
  <div class="feednav">
    <button class="back" id="backScans">← Scans</button>
    <span class="scantitle" id="scanTitle"></span>
  </div>
  <div class="banner" id="scanBanner" style="display:none"></div>
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
    <div class="dd" id="likeDd">
      <button class="btn ghost" id="likeBtn">＋ Tag contains</button>
      <div class="ddpanel compact" id="likePanel" style="display:none">
        <input class="ddsearch" id="likeInput" placeholder="e.g. psy — press Enter to add" autocomplete="off"/>
        <div class="ddfoot"><span class="hint">Matches any tag containing this text. Toggle a pill below to include/exclude.</span></div>
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
</div>
<script>
const $=s=>document.querySelector(s);
const feed=$('#feed'), moreBtn=$('#more'), emptyEl=$('#empty');
const LIMIT=50;
const POLL_MS=4000;         // scan status poll interval
let type='', sort='score', offset=0, loading=false;
let scanId=null;            // the scan whose feed is open (null = scan list)
let pollTimer=null;         // status polling handle
const tagState={};          // committed tag filters: tag -> 'by' | 'out'
const tagLikeState={};      // committed substring tag filters: text -> 'by' | 'out'
let pendingTags=new Set();  // genre-dropdown working set; committed on Save
let labelFilter=null;       // {id, name}
let facetTags=[];           // [{value,label,count}] genres present in current recs

function esc(s){ return (s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function bcHandle(url){ try{ const m=new URL(url).hostname.match(/^([^.]+)\\.bandcamp\\.com$/i); return (m&&m[1]!=='www')?m[1]:''; }catch(e){ return ''; } }
function ago(iso){ if(!iso) return ''; const s=(Date.now()-new Date(iso).getTime())/1000;
  if(s<60) return 'just now'; if(s<3600) return Math.floor(s/60)+'m ago';
  if(s<86400) return Math.floor(s/3600)+'h ago'; return Math.floor(s/86400)+'d ago'; }

// ══ scan list ══
async function showScans(){
  scanId=null; clearTimeout(pollTimer);
  $('#feedView').style.display='none'; $('#scansView').style.display='block'; $('#scanForm').style.display='none';
  const scans=await (await fetch('/api/scans')).json();
  if(scanId!==null) return;   // user opened a scan mid-fetch - don't yank them back
  $('#scansEmpty').style.display = scans.length ? 'none' : 'block';
  $('#scanCards').innerHTML = scans.map(scanCard).join('') +
    '<div class="newcard" id="newCard">＋  New scan from album/track URLs</div>';
  const active=scans.some(s=>s.status==='queued'||s.status==='running');
  if(active) pollTimer=setTimeout(showScans, POLL_MS);   // live-refresh while work runs
}
function scanCard(s){
  const st=esc(s.status), coll=s.kind==='collection';
  const meta = coll
    ? `<b>${s.rec_count.toLocaleString()}</b> recs <span class="sep">·</span> seeded by your collection`
    : (s.status==='error'
        ? `<span class="errtext">${esc(s.error||'failed')}</span>`
        : s.status==='queued' ? `waiting for your Mac worker <span class="sep">·</span> <b>${s.seed_count}</b> seed${s.seed_count===1?'':'s'}`
        : s.status==='running' ? `crawling seeds on your PC… <span class="sep">·</span> <b>${s.seed_count}</b> seed${s.seed_count===1?'':'s'}`
        : `<b>${s.rec_count.toLocaleString()}</b> recs <span class="sep">·</span> <b>${s.seed_count}</b> seed${s.seed_count===1?'':'s'}${s.stats&&s.stats.credits?` <span class="sep">·</span> ${s.stats.credits} credits`:''}${s.last_run_at?` <span class="sep">·</span> ${ago(s.last_run_at)}`:''}`);
  return `<div class="scan ${st}" data-scan="${s.id}" data-name="${esc(s.name)}" data-kind="${esc(s.kind)}" data-status="${st}">
    <div class="ico">${coll?'◎':'🎯'}</div>
    <div class="b">
      <div class="r1"><span class="nm">${esc(s.name)}</span>${coll?'<span class="star">★</span>':''}
        <span class="badge ${st}"><span class="dot"></span>${st}</span></div>
      <div class="meta">${meta}</div>
    </div></div>`;
}

// ══ new-scan form ══
let seeds=[];
function seedKind(u){ return u.toLowerCase().includes('/track/') ? 'track' : 'album'; }
function renderSeeds(){ $('#seedList').innerHTML=seeds.map((u,i)=>
  `<div class="seed"><span class="stag">${seedKind(u)}</span><span class="u">${esc(u)}</span><span class="rm" data-seed="${i}">×</span></div>`).join(''); }
function openForm(){ seeds=[]; renderSeeds(); $('#scanName').value=''; $('#seedUrl').value=''; $('#scanErr').textContent='';
  $('#scanForm').style.display='block'; $('#scanName').focus(); }
$('#newScanBtn').addEventListener('click',openForm);
$('#scanCards').addEventListener('click',e=>{
  if(e.target.closest('#newCard')){ openForm(); return; }
  const c=e.target.closest('.scan'); if(c) openScan(+c.dataset.scan, c.dataset.name, c.dataset.kind, c.dataset.status);
});
$('#cancelScan').addEventListener('click',()=>{ $('#scanForm').style.display='none'; });
function addSeed(){ const u=$('#seedUrl').value.trim(); if(u){ seeds.push(u); $('#seedUrl').value=''; renderSeeds(); $('#seedUrl').focus(); } }
$('#addSeed').addEventListener('click',addSeed);
$('#seedUrl').addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); addSeed(); } });
$('#seedList').addEventListener('click',e=>{ const r=e.target.closest('[data-seed]'); if(r){ seeds.splice(+r.dataset.seed,1); renderSeeds(); } });
$('#createScan').addEventListener('click',async e=>{
  const btn=e.currentTarget; if(btn.disabled) return; btn.disabled=true;   // guard double-submit
  const name=$('#scanName').value.trim(); $('#scanErr').textContent='';
  try{
    const r=await fetch('/api/scans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,seeds})});
    if(r.ok){ $('#scanForm').style.display='none'; showScans(); }
    else{ let d={}; try{ d=await r.json(); }catch{} $('#scanErr').textContent = d.detail || 'Could not create scan'; }
  } finally { btn.disabled=false; }
});

// ══ open a scan's feed ══
function resetFilters(){ type=''; sort='score'; offset=0; labelFilter=null;
  for(const k in tagState) delete tagState[k];
  for(const k in tagLikeState) delete tagLikeState[k];
  $('#filter').querySelectorAll('button').forEach((b,i)=>b.classList.toggle('on',i===0));
  renderSortLabel(); updateGenreBtn(); updateLikeBtn(); renderActive(); }
function showBanner(status, err){
  const el=$('#scanBanner');
  if(status==='done'){ el.style.display='none'; return; }
  el.style.display='block'; el.className='banner '+status;
  el.textContent = status==='queued' ? '⏳ Queued - start your Mac worker (arq) to run this scan.'
    : status==='running' ? '⏳ Running - crawling seeds on your PC…'
    : status==='error' ? ('⚠ Scan failed: '+(err||'')) : '';
}
async function openScan(id, name, kind, status){
  scanId=id; clearTimeout(pollTimer);
  $('#scansView').style.display='none'; $('#feedView').style.display='block';
  $('#scanTitle').innerHTML = esc(name)+(kind==='custom'?' <span class="ktag">custom</span>':' <span class="ktag">collection</span>');
  resetFilters(); feed.innerHTML=''; $('#count').innerHTML='';
  loadBlocked(); loadLiked();
  if(status!=='done'){ showBanner(status); pollTimer=setTimeout(()=>pollScan(id), POLL_MS); return; }
  showBanner('done'); loadFacets(); loadPage(true);
}
async function pollScan(id){
  const s=await (await fetch('/api/scans/'+id)).json();
  if(scanId!==id) return;                          // navigated away
  if(s.status==='done'){ showBanner('done'); loadFacets(); loadPage(true); }
  else if(s.status==='error'){ showBanner('error', s.error); }
  else{ showBanner(s.status); pollTimer=setTimeout(()=>pollScan(id), POLL_MS); }
}
$('#backScans').addEventListener('click',showScans);

// ══ feed (scoped to scanId) ══
function filterParams(){
  const q=new URLSearchParams();
  if(scanId!=null) q.set('scan_id',scanId);
  if(type) q.set('item_type',type);
  for(const [t,m] of Object.entries(tagState)){ if(m==='by') q.append('tag',t); else if(m==='out') q.append('exclude_tag',t); }
  for(const [t,m] of Object.entries(tagLikeState)){ if(m==='by') q.append('tag_contains',t); else if(m==='out') q.append('exclude_tag_contains',t); }
  if(labelFilter) q.set('label_id', labelFilter.id);
  return q;
}
function query(){ const q=filterParams(); q.set('sort',sort); q.set('limit',LIMIT); q.set('offset',offset); return q; }
async function updateCount(){
  const n=(await (await fetch('/api/recommendations/count?'+filterParams())).json()).count;
  const kind = type ? (type==='album'?'albums':'tracks') : 'results';
  const extra = filterParams().toString().replace(/(^|&)scan_id=[^&]*/,'').replace(/^&/,'');
  $('#count').innerHTML = `<b>${n.toLocaleString()}</b> ${kind}${extra?' match your filters':''}`;
}
async function loadFacets(){
  const f=await (await fetch('/api/facets'+(scanId!=null?'?scan_id='+scanId:''))).json();
  facetTags = f.tags;
  renderGenreList($('#genreSearch').value||''); updateGenreBtn();
}
function updateGenreBtn(){ const n=Object.keys(tagState).length; $('#genreBtn').textContent = n ? `Genres (${n}) ▾` : '＋ Genre filter'; }
function updateLikeBtn(){ const n=Object.keys(tagLikeState).length; $('#likeBtn').textContent = n ? `Contains (${n}) ▾` : '＋ Tag contains'; }
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
function openGenre(){ pendingTags = new Set(Object.keys(tagState));
  $('#genreSearch').value=''; renderGenreList(''); updateSaveBtn(); $('#genrePanel').style.display='block'; $('#genreSearch').focus(); }
function updateSaveBtn(){ const n=pendingTags.size; $('#genreSave').textContent = n?`Save (${n})`:'Save'; }
function saveGenres(){
  for(const t of Object.keys(tagState)) if(!pendingTags.has(t)) delete tagState[t];
  for(const t of pendingTags) if(tagState[t]===undefined) tagState[t]='by';
  $('#genrePanel').style.display='none'; refresh();
}
function renderActive(){
  const bits=[];
  for(const [t,m] of Object.entries(tagState))
    bits.push(`<span class="fpill ${m==='out'?'out':''}"><span class="tog" data-tog="${esc(t)}" title="click to switch include / exclude">${m==='out'?'⊘ exclude':'✓ include'}: <b>${esc(t)}</b></span><span class="rm" data-rmtag="${esc(t)}" title="remove">×</span></span>`);
  for(const [t,m] of Object.entries(tagLikeState))
    bits.push(`<span class="fpill ${m==='out'?'out':''}"><span class="tog" data-togl="${esc(t)}" title="click to switch include / exclude">${m==='out'?'⊘ exclude':'✓ include'}: <b>~${esc(t)}</b></span><span class="rm" data-rmtagl="${esc(t)}" title="remove">×</span></span>`);
  if(labelFilter) bits.push(`<span class="fpill"><span class="tog">label: <b>${esc(labelFilter.name)}</b></span><span class="rm" data-clear-label="1" title="remove">×</span></span>`);
  $('#active').innerHTML=bits.join('');
}
function card(r){
  const tags=(r.reasons.matched_tags||[]).map(t=>`<span class="chip tag" data-tag="${esc(t)}">${esc(t)}</span>`).join('');
  const co=r.reasons.co_owners||0; const hnd=bcHandle(r.url);
  return `<div class="card">
    <div class="score"><b>${r.score.toFixed(1)}</b><span>score</span></div>
    <div class="body">
      <div class="title">${esc(r.title)||'-'}<span class="type">${r.item_type}</span></div>
      <div class="band" data-label="${r.band_id||''}" data-name="${esc(r.band_name)}">${esc(r.band_name)||'unknown artist'}${hnd?`<span class="handle">${esc(hnd)}</span>`:''}</div>
      <div class="meta">
        <span class="chip signal">◈ ${co} neighbour${co===1?'':'s'} own this</span>
        ${tags}
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
function refresh(){ renderGenreList($('#genreSearch').value||''); updateGenreBtn(); updateLikeBtn(); renderActive(); loadPage(true); }

// ── feed events ──
$('#filter').addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b)return;
  [...e.currentTarget.children].forEach(x=>x.classList.remove('on')); b.classList.add('on'); type=b.dataset.t; loadPage(true); });
const SORTS={score:'Top score',neighbours:'Most owners',affinity:'Genre match'};
function renderSortLabel(){ $('#sortBtn').textContent='Sort · '+SORTS[sort]+' ▾';
  document.querySelectorAll('#sortPanel .ddrow').forEach(r=>r.classList.toggle('sel',r.dataset.sort===sort)); }
$('#sortBtn').addEventListener('click',e=>{ e.stopPropagation(); const p=$('#sortPanel');
  p.style.display=p.style.display==='none'?'block':'none'; });
$('#sortPanel').addEventListener('click',e=>{ const r=e.target.closest('.ddrow'); if(!r)return;
  sort=r.dataset.sort; renderSortLabel(); $('#sortPanel').style.display='none'; loadPage(true); });
$('#genreBtn').addEventListener('click',e=>{ e.stopPropagation(); const p=$('#genrePanel');
  if(p.style.display==='none') openGenre(); else p.style.display='none'; });
$('#genreSearch').addEventListener('input',e=>renderGenreList(e.target.value));
$('#genreList').addEventListener('click',e=>{ const r=e.target.closest('.ddrow'); if(!r)return;
  const t=r.dataset.tag; if(pendingTags.has(t)) pendingTags.delete(t); else pendingTags.add(t);
  r.classList.toggle('sel',pendingTags.has(t)); updateSaveBtn(); });
$('#genreSave').addEventListener('click',e=>{ e.stopPropagation(); saveGenres(); });
$('#genreClear').addEventListener('click',e=>{ e.stopPropagation();
  pendingTags.clear(); renderGenreList($('#genreSearch').value||''); updateSaveBtn(); });
$('#likeBtn').addEventListener('click',e=>{ e.stopPropagation(); const p=$('#likePanel');
  if(p.style.display==='none'){ p.style.display='block'; $('#likeInput').value=''; $('#likeInput').focus(); } else p.style.display='none'; });
$('#likeInput').addEventListener('keydown',e=>{ if(e.key!=='Enter') return; e.preventDefault();
  const v=e.target.value.trim().toLowerCase();
  if(v && tagLikeState[v]===undefined){ tagLikeState[v]='by'; e.target.value=''; refresh(); } });
document.addEventListener('click',e=>{
  if(!e.target.closest('#genreDd')) $('#genrePanel').style.display='none';
  if(!e.target.closest('#sortDd')) $('#sortPanel').style.display='none';
  if(!e.target.closest('#likeDd')) $('#likePanel').style.display='none';
});
$('#active').addEventListener('click',e=>{
  const rm=e.target.closest('[data-rmtag]'); const rml=e.target.closest('[data-rmtagl]');
  const cl=e.target.closest('[data-clear-label]'); const tog=e.target.closest('[data-tog]'); const togl=e.target.closest('[data-togl]');
  if(rm){ delete tagState[rm.dataset.rmtag]; refresh(); return; }
  if(rml){ delete tagLikeState[rml.dataset.rmtagl]; refresh(); return; }
  if(cl){ labelFilter=null; refresh(); return; }
  if(tog){ const t=tog.dataset.tog; if(t){ tagState[t]= tagState[t]==='out'?'by':'out'; refresh(); } return; }
  if(togl){ const t=togl.dataset.togl; if(t){ tagLikeState[t]= tagLikeState[t]==='out'?'by':'out'; refresh(); } }});
feed.addEventListener('click',async e=>{
  const tag=e.target.closest('.chip.tag'); if(tag){ tagState[tag.dataset.tag]='by'; refresh(); return; }
  const band=e.target.closest('.band'); if(band && band.dataset.label){ labelFilter={id:band.dataset.label,name:band.dataset.name}; refresh(); return; }
  const blk=e.target.closest('[data-block]'); if(blk){
    blk.disabled=true; const c=blk.closest('.card');
    let ok=false;
    try{ ok=(await fetch('/api/blacklist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({band_id:+blk.dataset.block})})).ok; }catch{}
    if(!ok){ blk.disabled=false; return; }
    c.classList.add('blocking');
    setTimeout(()=>{ c.remove(); updateCount(); }, 800);
    try{ await loadFacets(); await loadBlocked(); }catch{}
    return;
  }
  const lk=e.target.closest('[data-like-album],[data-like-track]'); if(lk){
    lk.disabled=true; const c=lk.closest('.card');
    const body=lk.dataset.likeAlbum?{album_id:+lk.dataset.likeAlbum}:{track_id:+lk.dataset.likeTrack};
    let ok=false;
    try{ ok=(await fetch('/api/likes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).ok; }catch{}
    if(!ok){ lk.disabled=false; return; }
    c.classList.add('liking');
    setTimeout(()=>{ c.remove(); updateCount(); }, 800);
    try{ await loadFacets(); await loadLiked(); }catch{}
  }
});
moreBtn.addEventListener('click',()=>loadPage(false));

// ── blocked panel (shared across scans) ──
const panel=$('#blockedPanel'); let panelOpen=false;
async function loadBlocked(){
  const rows=await (await fetch('/api/blacklist')).json();
  $('#blockedBtn').textContent=`Blocked (${rows.length})`;
  panel.innerHTML = rows.length
    ? '<div class="hint">Blocked artists / labels - never appear in any scan:</div>'+rows.map(b=>
        `<div class="brow"><div class="grow"><b>${esc(b.band_name)||b.band_id}</b>${b.band_url?` <span class="hint">${esc(b.band_url)}</span>`:''}</div>
         <button class="act" data-unblock="${b.band_id}">unblock</button></div>`).join('')
    : '<div class="hint">Nothing blocked yet. Use "⊘ block" on a card.</div>';
}
$('#blockedBtn').addEventListener('click',async()=>{ panelOpen=!panelOpen; panel.style.display=panelOpen?'block':'none';
  $('#blockedBtn').classList.toggle('on',panelOpen); if(panelOpen) await loadBlocked(); });
panel.addEventListener('click',async e=>{ const u=e.target.closest('[data-unblock]'); if(!u)return;
  u.disabled=true; await fetch('/api/blacklist/'+u.dataset.unblock+'/unblock',{method:'POST'});
  await loadBlocked(); });

// ── liked panel (shared across scans) ──
const lpanel=$('#likedPanel'); let lpanelOpen=false;
async function loadLiked(){
  const rows=await (await fetch('/api/likes')).json();
  $('#likedBtn').textContent=`♥ Liked (${rows.length})`;
  lpanel.innerHTML = rows.length
    ? '<div class="hint">Liked - kept out of every scan (your next collection crawl reflects the real wishlist/purchase/follow):</div>'+rows.map(r=>
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

renderSortLabel(); showScans();
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _PAGE
