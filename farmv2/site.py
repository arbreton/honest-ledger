"""Static dashboard renderer. Data is embedded (no fetch) so the first paint never fails; data.json is also published."""
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Farm Ledger</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--mut:#5d6674;--line:#e3e7ed;--acc:#0b6bcb;--good:#12805c;--bad:#c23a31;--warn:#a86400;--chip:#eef1f5}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0e1116;--card:#171b22;--ink:#e8ebf0;--mut:#98a2b3;--line:#272d38;--acc:#5aa5ff;--good:#3ac28f;--bad:#ff7b72;--warn:#e3a43b;--chip:#202632;color-scheme:dark}}
:root[data-theme=dark]{--bg:#0e1116;--card:#171b22;--ink:#e8ebf0;--mut:#98a2b3;--line:#272d38;--acc:#5aa5ff;--good:#3ac28f;--bad:#ff7b72;--warn:#e3a43b;--chip:#202632;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:28px 0 10px}.sub{color:var(--mut);font-size:13px}
header{display:flex;gap:12px;justify-content:space-between;align-items:flex-start;flex-wrap:wrap}
.pills{display:flex;gap:6px;flex-wrap:wrap}.pill{background:var(--chip);border-radius:99px;padding:3px 10px;font-size:12px;display:inline-flex;gap:6px;align-items:center}
.dot{width:8px;height:8px;border-radius:50%;background:var(--mut)}.ok .dot{background:var(--good)}.bad .dot{background:var(--bad)}.warn .dot{background:var(--warn)}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.k{color:var(--mut);font-size:12px}.v{font-size:22px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}.s{font-size:12px;color:var(--mut);margin-top:2px}
.pos{color:var(--good)}.neg{color:var(--bad)}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:12px;color:var(--mut);font-weight:550}td.r,th.r{text-align:right}.scroll{overflow-x:auto}
.bar{height:10px;border-radius:6px;background:var(--chip);position:relative;overflow:hidden}.bar i{position:absolute;left:0;top:0;bottom:0;background:var(--acc);border-radius:6px}
.alloc{display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--chip)}.alloc i{display:block;height:100%}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-top:6px}.legend b{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.two{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
svg{width:100%;height:auto;display:block}.axis{stroke:var(--line)}.lbl{fill:var(--mut);font-size:11px}
input[type=range]{width:100%}.row{display:flex;gap:16px;flex-wrap:wrap;align-items:center}.row label{flex:1;min-width:200px;font-size:13px}
.tag{font-size:11px;padding:1px 7px;border-radius:99px;background:var(--chip);color:var(--mut)}.tag.bad{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}.tag.good{background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good)}
ul.clean{margin:0;padding-left:18px}ul.clean li{margin:3px 0}
footer{margin-top:30px;color:var(--mut);font-size:12px}
</style></head><body><div class="wrap">
<header><div><h1>Farm Ledger <span class="tag" id="stage"></span></h1><div class="sub" id="sub"></div></div><div class="pills" id="pills"></div></header>

<h2>Where you stand</h2><div class="grid" id="kpis"></div>

<h2>Progress to the goal</h2><div class="box"><div class="row" style="justify-content:space-between"><div id="goaltxt"></div><div class="sub">log scale · gates at $1k (S1), $10k (S2), $50k (S3)</div></div>
<div style="margin-top:10px" id="goalbar"></div></div>

<h2>Equity curve</h2><div class="box"><div id="chart"></div><div class="legend"><span><b style="background:var(--acc)"></b>Portfolio (NAV)</span><span><b style="background:var(--mut)"></b>Just holding the ETH you put in</span><span><b style="background:var(--warn)"></b>Money you put in</span></div>
<div class="sub" style="margin-top:6px" id="attrib"></div></div>

<div class="two"><div><h2>Holdings</h2><div class="box"><div class="alloc" id="alloc"></div><div class="legend" id="alloclegend"></div><div class="scroll" style="margin-top:8px"><table id="hold"></table></div></div></div>
<div><h2>Strategy scorecard</h2><div class="box scroll"><table id="strat"></table><div class="sub" style="margin-top:8px">Each strategy must beat its benchmark after gas to stay live. Three months of evidence before any promotion.</div></div></div></div>

<h2>What the system considered, and why it did (or didn't) act</h2><div class="box scroll"><table id="cons"></table><div class="sub" style="margin-top:8px" id="pipeline"></div></div>
<div class="two"><div><h2>Yield candidates (not approved)</h2><div class="box scroll"><table id="cand"></table><div class="sub" style="margin-top:8px">Base USDC, no impermanent-loss risk, TVL over $20M, from DeFiLlama. Advertised rates can differ from what a vault really pays: the system measures share prices on-chain before trusting any of them. New protocols need your approval.</div></div></div>
<div><h2>Forecasts</h2><div class="box scroll"><table id="fc"></table><div class="sub" style="margin-top:8px" id="brier"></div></div></div></div>
<h2>Research lab: strategies tested on paper only</h2><div class="box" id="lab"></div>
<h2>Opportunity pipeline (grants, bounties, paid work)</h2><div class="box" id="opps"></div>
<h2>Every transaction, with what it cost</h2><div class="box scroll"><table id="txs"></table></div>

<h2>Path to $100,000</h2><div class="box"><div class="row"><label>Monthly contribution: <b id="cv"></b><input id="c" type="range" min="0" max="2000" step="50" value="500"></label>
<label>Net return per year: <b id="av"></b><input id="a" type="range" min="0" max="40" step="1" value="15"></label></div>
<div style="margin:10px 0 4px;font-size:18px" id="years"></div><div class="sub">Arithmetic, not a forecast. Net return after gas and losses is unproven; USDC lending on Base has recently been in the 4–5% range.</div>
<div class="scroll" style="margin-top:10px"><table id="plan"></table></div></div>

<h2>Safety &amp; service levels</h2><div class="box"><ul class="clean" id="slo"></ul></div>

<h2>What v1 taught us (retired)</h2><div class="box"><ul class="clean" id="v1"></ul></div>

<footer><div id="foot"></div><div style="margin-top:6px">Design docs: PRD · SRS · NFR · ADD · HLD · LLD · TDD · RFC · SLOs · 14 ADRs. This page describes a personal experiment, not financial or tax advice. Everything shown is derived from on-chain data and an append-only ledger.</div></footer>
</div>
<script id="d" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('d').textContent);
const $=id=>document.getElementById(id);
const usd=(x,n=2)=>(x<0?'−':'')+'$'+Math.abs(x).toLocaleString('en-US',{minimumFractionDigits:n,maximumFractionDigits:n});
const sgn=(x,n=2)=>(x>0?'+':x<0?'−':'')+'$'+Math.abs(x).toFixed(n);
const cls=x=>x>0.005?'pos':x<-0.005?'neg':'';
const ago=ts=>{const m=Math.max(0,(Date.now()-new Date(ts))/60000);return m<90?Math.round(m)+' min ago':(m/60).toFixed(1)+' h ago'};
$('stage').textContent=D.stage;
$('sub').textContent='Base · wallet '+D.wallet_short+' · block '+D.block.toLocaleString()+' · ETH '+usd(D.eth_usd)+' ('+D.price_source+')';
const S=D.slo, halted=!!S.halted, auditOk=S.audit&&S.audit.ok, canOk=S.canaries&&S.canaries.every(c=>c[3]);
const pill=(t,k)=>`<span class="pill ${k}"><span class="dot"></span>${t}</span>`;
$('pills').innerHTML=[
 pill(halted?'HALTED':'Running',halted?'bad':'ok'),
 pill('Ledger = chain'+(S.last_ok_ts?' · '+ago(S.last_ok_ts):''),S.recon_ok_pct===100?'ok':'bad'),
 pill(S.audit?(auditOk?'Auditor: clear':'Auditor: ALERT'):'Auditor: pending',S.audit?(auditOk?'ok':'bad'):'warn'),
 pill(S.canaries?(canOk?'Canaries '+(S.canaries.length-1)+'/'+(S.canaries.length-1)+' blocked':'CANARY FAILED'):'Canaries pending',S.canaries?(canOk?'ok':'bad'):'warn'),
 pill('v1 bot: stopped','warn')].join('');
const kp=(k,v,s,c='')=>`<div class="card"><div class="k">${k}</div><div class="v ${c}">${v}</div><div class="s">${s}</div></div>`;
const lpFees=D.lp.reduce((a,x)=>a+x.fees_usd,0);
$('kpis').innerHTML=[
 kp('Portfolio value',usd(D.nav_usd),D.nav_eth.toFixed(5)+' ETH-equivalent'),
 kp('You put in',usd(D.contributions_usd),D.contributions.length+' funding event'+(D.contributions.length==1?'':'s')),
 kp('Profit / loss',sgn(D.pnl_usd),((D.pnl_usd/D.contributions_usd)*100).toFixed(1)+'% on money in',cls(D.pnl_usd)),
 kp('vs. just holding ETH',sgn(D.vs_hold_usd),'strategy effect after all costs',cls(D.vs_hold_usd)),
 kp('Gas paid',usd(D.gas_total_usd),usd(D.gas_overpaid_usd)+' of it avoidable',D.gas_overpaid_usd>0.5?'neg':''),
 kp('LP fees earned',usd(lpFees),'uncollected, read from the pool')].join('');
// goal bar (log)
const L=v=>Math.log10(Math.max(v,1)),pct=Math.min(100,100*L(D.nav_usd)/L(D.goal_usd));
$('goaltxt').innerHTML='<b>'+usd(D.nav_usd)+'</b> of <b>$100,000</b> — '+Math.round(D.goal_usd/D.nav_usd).toLocaleString()+'× to go';
$('goalbar').innerHTML='<div class="bar"><i style="width:'+pct+'%"></i></div><div style="position:relative;height:16px">'+[1000,10000,50000].map(g=>`<span class="lbl" style="position:absolute;left:${100*L(g)/L(D.goal_usd)}%;transform:translateX(-50%)">${usd(g,0)}</span>`).join('')+'</div>';
// chart
(function(){const s=D.series;if(s.length<2)return;const W=900,H=240,m={l:46,r:12,t:10,b:24};
 const t0=new Date(s[0].ts).getTime(),t1=Math.max(new Date(s[s.length-1].ts).getTime(),Date.now());
 const vals=s.flatMap(p=>[p.nav,p.hold,p.contrib]).concat([D.nav_usd,D.hold_value_usd]);let lo=Math.min(...vals.filter(v=>v>0)),hi=Math.max(...vals);const pad=(hi-lo)*.15||1;lo=Math.max(0,lo-pad);hi+=pad;
 const X=t=>m.l+(W-m.l-m.r)*(t-t0)/(t1-t0||1),Y=v=>H-m.b-(H-m.t-m.b)*(v-lo)/(hi-lo);
 const pts=k=>s.map(p=>X(new Date(p.ts))+','+Y(p[k])).join(' ')+' '+X(Date.now())+','+Y(k=='nav'?D.nav_usd:k=='hold'?D.hold_value_usd:D.contributions_usd);
 let g='';for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4;g+=`<line class="axis" x1="${m.l}" x2="${W-m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="lbl" x="${m.l-6}" y="${Y(v)+4}" text-anchor="end">$${v.toFixed(0)}</text>`}
 const ds=[0,.5,1].map(f=>{const t=t0+(t1-t0)*f;return `<text class="lbl" x="${X(t)}" y="${H-6}" text-anchor="${f==0?'start':f==1?'end':'middle'}">${new Date(t).toLocaleDateString('en-US',{month:'short',day:'numeric'})}</text>`}).join('');
 $('chart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Portfolio value versus holding ETH">${g}${ds}<polyline fill="none" stroke="var(--warn)" stroke-width="1.5" points="${pts('contrib')}"/><polyline fill="none" stroke="var(--mut)" stroke-width="2" stroke-dasharray="5 4" points="${pts('hold')}"/><polyline fill="none" stroke="var(--acc)" stroke-width="2.5" points="${pts('nav')}"/>${s.map(p=>`<circle cx="${X(new Date(p.ts))}" cy="${Y(p.nav)}" r="3" fill="var(--acc)"><title>${new Date(p.ts).toLocaleString()} · ${usd(p.nav)}</title></circle>`).join('')}</svg>`;
 $('attrib').innerHTML='Of the '+sgn(D.pnl_usd)+' total: <b class="'+cls(D.price_effect_usd)+'">'+sgn(D.price_effect_usd)+'</b> is ETH changing price (not the system\'s doing) and <b class="'+cls(D.strategy_effect_usd)+'">'+sgn(D.strategy_effect_usd)+'</b> is what the strategies and gas did relative to simply holding.';})();
// holdings
const BC={core:'var(--acc)',farm:'var(--good)',options:'var(--warn)'};
$('alloc').innerHTML=Object.entries(D.buckets).map(([k,v])=>`<i style="width:${100*v/D.nav_usd}%;background:${BC[k]||'var(--mut)'}"></i>`).join('');
$('alloclegend').innerHTML=Object.entries(D.buckets).map(([k,v])=>`<span><b style="background:${BC[k]||'var(--mut)'}"></b>${k} ${(100*v/D.nav_usd).toFixed(0)}%</span>`).join('');
$('hold').innerHTML='<tr><th>Asset</th><th>Amount</th><th class="r">Value</th></tr>'+D.holdings.map(h=>`<tr><td>${h.name}</td><td>${h.qty}</td><td class="r">${usd(h.usd)}</td></tr>`).join('');
// strategies
const lp=D.lp_perf,vp=D.vault_perf,rows=[];
rows.push(['core-hold','Hold ETH / USDC','—','buy &amp; hold','<span class="tag">benchmark</span>']);
if(vp)rows.push(['usdc-park','Morpho USDC vault',usd(vp.now,4),(vp.apy_onchain==null?'yield n/a':(vp.apy_onchain*100).toFixed(1)+'%/yr on-chain share price (7d)')+(vp.apy_llama?' · aggregator '+(vp.apy_llama*100).toFixed(1)+'%':''),'<span class="tag good">live</span>']);
if(lp)rows.push(['cl-lp','Aerodrome WETH/USDC LP',sgn(lp.alpha_vs_hold)+' vs holding',usd(lp.fees_usd)+' fees · '+lp.days.toFixed(0)+'d',`<span class="tag ${lp.alpha_vs_hold>0?'good':'bad'}">${lp.alpha_vs_hold>0?'beating hold':'trailing hold'} · gauge dead</span>`]);
const ln=D.lp[0];if(ln)rows.push(['range',ln.in_range?'In range':'OUT OF RANGE',ln.margin_ticks+' ticks from edge',ln.margin_ticks<300?'<b class="neg">near edge</b>':'ok','<span class="tag">monitor</span>']);
rows.push(['airdrop-options','Dolomite supply','gas only','capped option, E1 evidence','<span class="tag">option</span>']);
$('strat').innerHTML='<tr><th>Strategy</th><th>What</th><th>Net result</th><th>Note</th><th>Status</th></tr>'+rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td><td>${r[4]}</td></tr>`).join('');
// txs
$('txs').innerHTML='<tr><th>#</th><th>Date</th><th>Action</th><th>Contract</th><th>Result</th><th class="r">Fee</th><th class="r">Gas price</th><th class="r">× network</th></tr>'+D.txs.slice().reverse().map(t=>`<tr><td>${t.nonce}</td><td>${t.ts.slice(0,16).replace('T',' ')}</td><td>${t.what}</td><td>${t.target}</td><td>${t.status=='ok'?'ok':'<span class="tag bad">reverted</span>'}</td><td class="r">${usd(t.fee_usd,4)}</td><td class="r">${t.gwei} gwei</td><td class="r">${t.ratio==null?'':(t.ratio>20?'<span class="tag bad">'+t.ratio+'×</span>':t.ratio+'×')}</td></tr>`).join('');
// plan calc
const yrs=(p0,c,a)=>{const r=Math.pow(1+a,1/12)-1;let v=p0,m=0;while(v<D.goal_usd&&m<1200){v=v*(1+r)+c;m++}return m>=1200?null:m/12};
function calc(){const c=+$('c').value,a=+$('a').value/100;$('cv').textContent=usd(c,0)+'/mo';$('av').textContent=(a*100).toFixed(0)+'%';const y=yrs(D.nav_usd,c,a);
 $('years').innerHTML=y==null?'Not within 100 years.':'About <b>'+y.toFixed(1)+' years</b> to reach $100,000';}
$('c').oninput=$('a').oninput=calc;calc();
const AP=[.05,.15,.25],CS=[0,250,500,1000,2000];
$('plan').innerHTML='<tr><th>Monthly</th>'+AP.map(a=>`<th class="r">${a*100}% / yr</th>`).join('')+'</tr>'+CS.map(c=>`<tr><td>${usd(c,0)}</td>${AP.map(a=>{const y=yrs(D.nav_usd,c,a);return `<td class="r">${y==null?'100+':y.toFixed(1)+' yrs'}</td>`}).join('')}</tr>`).join('');
// SLO
const li=(ok,t)=>`<li>${ok===true?'✅':ok===false?'⛔':'⏳'} ${t}</li>`;
$('slo').innerHTML=[
 li(S.recon_ok_pct===100,'Ledger reconciles to the chain exactly: '+(S.recon_ok_pct==null?'n/a':S.recon_ok_pct.toFixed(0)+'% of '+S.recon_n+' checks')+(S.last_ok_ts?' · last '+ago(S.last_ok_ts):'')),
 li(S.hash_chain_ok,'Append-only event log verified: '+S.events+' events, hash chain intact'),
 li(S.audit?S.audit.ok:null,S.audit?'Independent auditor (separate code, own RPC): '+S.audit.findings.map(f=>f[0]+(f[1]?' ✓':' ✗')).join(' · '):'Independent auditor: pending first run'),
 li(S.canaries?canOk:null,S.canaries?'Risk Gate canaries: '+(S.canaries.length-1)+'/'+(S.canaries.length-1)+' attack scenarios blocked (plus a healthy control that must pass), including v1\'s 8-gwei transaction':'Canaries pending'),
 li(!halted,halted?'HALTED: '+(S.halted.why||''):'Kill switch clear'),
 li(D.pipeline.signer==='unlocked'?true:null,'Signer: '+D.pipeline.signer+(D.pipeline.signer==='unlocked'?' (can sign only allowlisted calls against a valid receipt, within its own limits)':' — nothing can be signed until the operator unlocks it')+' · '+D.pipeline.sent_txs+' transactions sent by v2'),
 li(D.pipeline.allowlist_ok?true:null,D.pipeline.allowlist_ok?'Signer allowlist is operator-approved and includes LP management (remove/collect/burn/mint, one swap router; every call must return value to the wallet).':'Signer allowlist for LP management is written but NOT yet approved by the operator: the LP strategy will not act until it is.'),
 li(true,'Standing approvals (bounded, expiring): '+(D.pipeline.standing.length?D.pipeline.standing.map(a=>a.action+' up to $'+a.max_notional_usd+' until '+a.expires).join(' · '):'none')),
 li(true,'v1 bot stopped by operator on 2026-11-08; its 22 transactions are declared as legacy history.')].join('');
$('v1').innerHTML=['<b>Auditor never disagreed:</b> 2,646 of 2,646 verdicts were "PASS", because its checks could not fail.',
 '<b>Discovery was six hardcoded items</b> re-scored 392 times; dashboard NAV and ETH balance were stale.',
 '<b>One transaction paid 8 gwei when the network charged 0.005</b> (1,600×): '+usd((D.txs.find(t=>t.ratio>1000)||{fee_usd:0}).fee_usd)+' to move about $1.',
 '<b>Paper strategies lost:</b> quest points 1 win in 16 (−$7.60), prediction-market momentum −$3.84 over 48 paper trades.',
 '<b>What worked:</b> fork-simulating before sending, multi-RPC checks, hard-zero scam rules, and honest kill rules. All kept in v2.'].map(x=>'<li>'+x+'</li>').join('');
$('cons').innerHTML='<tr><th>When (UTC)</th><th>Strategy</th><th>Situation</th><th>Decision</th></tr>'+D.pipeline.considered.map(c=>`<tr><td>${c.ts.slice(5).replace('T',' ')}</td><td>${c.strategy}</td><td>${c.summary}</td><td style="white-space:normal;min-width:240px">${c.reason}</td></tr>`).join('');
$('pipeline').textContent=D.pipeline.intents.length?'Recent intents: '+D.pipeline.intents.map(i=>i.strategy+' → '+i.state).join(' · '):'No intents have reached the money path yet. At this size, "do nothing" is usually the correct answer.';
$('cand').innerHTML='<tr><th>Protocol</th><th>Pool</th><th class="r">TVL</th><th class="r">Base APY</th><th class="r">30d avg</th></tr>'+D.pipeline.candidates.map(c=>`<tr><td>${c.project}</td><td>${c.symbol}</td><td class="r">$${(c.tvl_usd/1e6).toFixed(0)}M</td><td class="r">${(c.apy_base||0).toFixed(2)}%</td><td class="r">${c.apy_mean_30d==null?'–':c.apy_mean_30d.toFixed(2)+'%'}</td></tr>`).join('');
$('fc').innerHTML='<tr><th>Question</th><th class="r">Prob.</th><th>Evidence</th><th>Due</th></tr>'+(D.pipeline.forecasts.length?D.pipeline.forecasts.map(f=>`<tr><td style="white-space:normal;min-width:200px">${f.question}</td><td class="r">${(f.probability*100).toFixed(0)}%</td><td>${f.evidence_class}</td><td>${f.resolve_by}</td></tr>`).join(''):'<tr><td colspan=4>none open</td></tr>');
$('brier').textContent=D.pipeline.resolved?('Calibration (Brier, lower is better): '+D.pipeline.brier.toFixed(3)+' over '+D.pipeline.resolved+' resolved'):'No forecasts resolved yet; calibration starts after the first ones come due.';
(function(){const Lb=D.lab,el=$('lab');if(!Lb){el.innerHTML='<div class="sub">Lab has not produced a report yet.</div>';return}
 const pc=(x,n=0)=>x==null?'–':(x*100).toFixed(n)+'%',bm=Lb.benchmark||{};
 let h='<p style="margin:0 0 8px">'+Lb.verdict+'</p>';
 if(Lb.paper&&Lb.paper.length){const t0=Math.min(...Lb.paper.map(c=>new Date(c.registered_at).getTime())),day=Math.floor((Date.now()-t0)/864e5),due=new Date(t0+30*864e5).toISOString().slice(0,10);h+='<div class="pill '+(day>=30?'ok':'warn')+'" style="margin-bottom:8px"><span class="dot"></span>Forward test: day '+Math.max(0,day)+' of 30 · day-30 sanity review '+(day>=30?'is due now (see docs/reviews)':'on '+due)+' · real decisions need 90-180 days</div>'}
 if(bm.select)h+='<div class="sub" style="margin-bottom:8px">ETH buy &amp; hold by window — 2023-24: ×'+bm.select.total.toFixed(2)+' (max drop '+pc(bm.select.maxdd)+') · 2025: ×'+bm.valid.total.toFixed(2)+' ('+pc(bm.valid.maxdd)+') · 2026 so far: ×'+bm.holdout.total.toFixed(2)+' ('+pc(bm.holdout.maxdd)+').</div>';
 h+='<div class="sub"><b>Forward paper trading</b> (strategies were registered up front; only bars after registration count)</div><div class="scroll"><table><tr><th>Strategy</th><th>Risk</th><th class="r">Exposure now</th><th class="r">Days</th><th class="r">Return</th><th class="r">Hold ETH</th><th class="r">Worst drop</th><th>Status</th></tr>'+
   Lb.paper.map(c=>`<tr><td>${c.name}</td><td>${c.risk=='HIGH'?'<span class="tag bad">HIGH</span>':c.risk}</td><td class="r">${c.exposure_now>0?'+':''}${c.exposure_now.toFixed(2)}</td><td class="r">${c.days.toFixed(1)}</td><td class="r">${pc(c.ret,1)}</td><td class="r">${pc(c.bh_ret,1)}</td><td class="r">${pc(c.maxdd,1)}</td><td>${c.status}</td></tr>`).join('')+'</table></div>';
 const rows=(Lb.survivors.length?Lb.survivors:Lb.best_failed);
 h+='<div class="sub" style="margin-top:12px"><b>'+(Lb.survivors.length?'Strategies that passed every gate':'Closest candidates (none passed all gates)')+'</b></div><div class="scroll"><table><tr><th>Strategy</th><th>Type</th><th class="r">Sharpe 23-24</th><th class="r">Sharpe 2025</th><th class="r">Deflated Sharpe</th><th>Failed gates</th></tr>'+
   rows.map(v=>`<tr><td>${v.name}</td><td>${v.tag}</td><td class="r">${v.select.sharpe==null?'–':v.select.sharpe.toFixed(2)}</td><td class="r">${v.valid.sharpe==null?'–':v.valid.sharpe.toFixed(2)}</td><td class="r">${v.dsr.toFixed(2)}</td><td style="white-space:normal;min-width:180px">${Object.entries(v.gates).filter(([k,x])=>!x).map(([k])=>k).join(', ')||'none'}</td></tr>`).join('')+'</table></div>';
 if(Lb.families){h+='<div class="sub" style="margin-top:12px"><b>Every idea tested</b> (Sharpe of the best config per window; "beat" = strategies that beat buy &amp; hold in 2023-24 / 2025 / 2026)</div><div class="scroll"><table><tr><th>Idea</th><th class="r">Configs</th><th class="r">Best 23-24</th><th class="r">Best 2025</th><th class="r">Best 2026</th><th class="r">Beat B&amp;H</th><th class="r">Passed all gates</th></tr>'+Lb.families.map(f=>`<tr><td>${f.family}</td><td class="r">${f.n}</td><td class="r">${f.best_select==null?'–':f.best_select.toFixed(2)}</td><td class="r">${f.best_valid==null?'–':f.best_valid.toFixed(2)}</td><td class="r">${f.best_holdout==null?'–':f.best_holdout.toFixed(2)}</td><td class="r">${f.beat.join(' / ')}</td><td class="r">${f.passed}</td></tr>`).join('')+'</table></div>'}
 if(Lb.seasonality){const a=Lb.seasonality.asia,w=Lb.seasonality.weekly;h+='<div class="sub" style="margin-top:12px"><b>Time patterns:</b> ETH is down on '+pc(a.pct_days_negative)+' of days in the Asia-open window (00-02 UTC, p='+a.p.toFixed(2)+', sign flips between years); '+pc(w.pct_up_weeks)+' of '+w.weeks+' weeks are up and last week predicts this week only weakly (rank corr '+w.week_to_next_week_rank_corr.toFixed(2)+'). After correcting for testing 24 hours and 7 weekdays, <b>none</b> is statistically significant. Busiest hours (volume): '+Lb.seasonality.busy_hours.map(x=>x[0]+':00 UTC').join(', ')+' (matters for LP fees, not direction).</div>'}
 if(Lb.cycles){const c=Lb.cycles.now;h+='<div class="sub" style="margin-top:12px"><b>Cycle position:</b> ETH is '+pc(-c.drawdown_from_ath)+' below its all-time high ($'+Math.round(c.ath).toLocaleString()+', '+c.ath_date+'), Mayer multiple '+c.mayer.toFixed(2)+'. Retaking the high needs ×'+c.x_to_reclaim_ath.toFixed(1)+'. An 8× from here is $'+Math.round(c.price_for_8x).toLocaleString()+', which is '+c.eight_x_vs_ath.toFixed(1)+'× the old high; the last cycle\'s high only matched the one before it, so cycle multiples have been compressing, not growing.</div>'}
 if(Lb.newpools&&Lb.newpools.summary&&Lb.newpools.summary['24h']){const n=Lb.newpools,s24=n.summary['24h'],s1=n.summary['1h'];h+='<div class="sub" style="margin-top:12px"><b>Micro-cap study</b> (new Aerodrome pools, last '+n.days+' days): of '+n.created+' pools created only '+n.priced_pairs+' could be priced. Buying 10 min after creation, net of a '+(n.round_trip_cost*100).toFixed(0)+'% round-trip cost: 1h median '+pc(s1.median_net,1)+', 24h median '+pc(s24.median_net,1)+', '+pc(s24.pct_positive)+' positive, worst '+pc(s24.worst)+' (a rug). Tiny sample and an upper bound (honeypots are undetectable here): no evidence of an edge.</div>'}
 h+='<ul class="clean" style="margin-top:10px">'+Lb.rules.map(r=>'<li>'+r+'</li>').join('')+'</ul><div class="sub" style="margin-top:6px">Sweep: '+(Lb.sweep_generated||'pending').replace('T',' ').slice(0,16)+' UTC · '+(Lb.liquidations==null?'':Lb.liquidations+' leveraged configs were liquidated in the backtest · ')+'nothing here trades real money.</div>';
 el.innerHTML=h;})();
(function(){const O=D.opps,el=$('opps');if(!O){el.innerHTML='<div class="sub">Pipeline has not run yet.</div>';return}
 const cn=O.counts||{};let h='<div class="sub" style="margin-bottom:8px">A bot scans public listings every '+O.interval_h+' h, ranks them by expected dollars per hour (reward x chance, given how many people already entered), and drafts a reviewable packet. <b>It never submits anything or contacts anyone</b>: a human sends each application. Last scan: '+(O.last_run?O.last_run.replace('T',' ').slice(0,16)+' UTC':'pending')+'.</div>';
 h+='<div class="sub">'+Object.entries(cn).map(([k,v])=>k.toLowerCase()+' '+v).join(' · ')+(O.leads?' · '+O.leads+' leads':'')+'</div><div class="scroll"><table><tr><th>Opportunity</th><th>Type</th><th class="r">Reward</th><th class="r">Entries</th><th>Deadline</th><th class="r">Expected $/h</th><th>Status</th></tr>'+
  O.top.map(o=>`<tr><td style="white-space:normal;min-width:220px">${o.title}</td><td>${o.kind}</td><td class="r">${usd(o.reward_usd,0)}</td><td class="r">${o.competition==null?'–':o.competition}</td><td>${o.deadline||'rolling'}</td><td class="r">${o.score.toFixed(2)}</td><td>${o.status.toLowerCase()}</td></tr>`).join('')+'</table></div><div class="sub" style="margin-top:6px">Expected value is a crude estimate. Security bounties are long shots for a first-timer and are scored that way.</div>';
 el.innerHTML=h;})();
$('foot').textContent='Updated '+D.generated_at.replace('T',' ').replace('+00:00',' UTC')+' · data block '+D.block.toLocaleString()+' · farmv2 0.1.0';
</script></body></html>'''

def render(data: dict, out_dir=ROOT / "site"):
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, separators=(",", ":"), default=str).replace("</", "<\\/")
    (out / "index.html").write_text(TEMPLATE.replace("__DATA__", blob))
    (out / "data.json").write_text(json.dumps(data, indent=1, default=str))
    return out
