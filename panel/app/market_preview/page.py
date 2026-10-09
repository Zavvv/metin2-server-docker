# =============================================================================
#  /market -- the page (Iwakura's Patch 12, points 1A-1C, 1G, 1K).
#
#  The panel's own frame (admin_panel.BASE: the header with the logo, the
#  server's name and "Mapa na zywo") around a page of its own: the layout of
#  his first screenshot, the colours of his second - the panel's, measured
#  (1B), every one a variable below. Everything inside is scoped under .mk, so
#  the panel's own input and button rules, written for its forms, do not
#  reach it. The script fetches /market/api/offers and draws the list; no
#  value of an offer is ever put into the page as HTML (esc()).
# =============================================================================

CSS = r"""
<style>
.wrap{max-width:1440px}
.mk{--mk-bg:#0E0C09;--mk-rule:#534325;--mk-card:#1C1812;--mk-card-a:#1E1913;--mk-card-b:#181410;
--mk-line:#332B1D;--mk-title:#F0EADD;--mk-text:#A89D84;--mk-dash:#6B6350;--mk-gold:#E9B64B;
--mk-in:#15120D;--mk-sel:#2A2214;--mk-hover:#4E3E1D;--mk-btn2:#292111;
--mk-ok-bg:#16261A;--mk-ok-line:#2F5A37;--mk-ok:#7FD38B;--mk-bad-bg:#2B1414;--mk-bad-line:#5A2A2A;--mk-bad:#E07A6A;
--mk-tag-bg:#241F17;--mk-tag-line:#3A3122;--mk-tag:#C9BFA8;color:var(--mk-title);font-size:14px}
.mk *{box-sizing:border-box}
.mk a{color:var(--mk-gold)}
.mk .mk-back{display:inline-block;margin:0 0 12px;font-size:14px}
.mk h2.mk-h{margin:0 0 4px;font-size:20px;color:var(--mk-title);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.mk .mk-badge-exp{font-size:11px;font-variant:small-caps;letter-spacing:.5px;padding:2px 8px;border-radius:999px;
background:var(--mk-btn2);border:1px solid var(--mk-hover);color:var(--mk-gold);font-weight:600}
.mk .mk-card{background:linear-gradient(180deg,var(--mk-card-a),var(--mk-card-b));border:1px solid var(--mk-line);
border-radius:10px;padding:14px;margin-bottom:12px}
.mk .mk-sec{font-size:12px;font-weight:700;letter-spacing:1px;color:var(--mk-title);padding-bottom:7px;margin:0 0 10px;
border-bottom:1px dashed var(--mk-dash)}
.mk .mk-muted{color:var(--mk-text);font-size:12.5px}
.mk input,.mk select{background:var(--mk-in);color:var(--mk-title);border:1px solid var(--mk-line);border-radius:7px;
padding:7px 9px;font-size:13px;width:100%;margin:0;box-shadow:none;font-family:inherit}
.mk input::placeholder{color:var(--mk-dash)}
.mk input:focus,.mk select:focus{outline:none;border-color:var(--mk-gold);box-shadow:none}
.mk input[type=checkbox]{width:auto;margin:0 6px 0 0;accent-color:var(--mk-gold);vertical-align:-2px}
.mk input.mk-bad,.mk select.mk-bad{border-color:var(--mk-bad)}
.mk .mk-err{color:var(--mk-bad);font-size:11.5px;margin-top:3px;display:none}
.mk .mk-bad+.mk-err,.mk .mk-err.on{display:block}
.mk button{font-family:inherit;margin:0;transform:none}
.mk .mk-btn{background:linear-gradient(180deg,#F6D686,#F0C76A 55%,#EAB951);color:#241C0D;font-weight:700;border:none;
border-radius:8px;padding:8px 14px;font-size:13.5px;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.35);
transition:filter .15s;width:auto;display:inline-block}
.mk .mk-btn:hover{filter:brightness(1.05);transform:none;box-shadow:0 2px 6px rgba(0,0,0,.35)}
.mk .mk-btn2{background:var(--mk-btn2);color:var(--mk-gold);border:1px solid var(--mk-hover);border-radius:8px;
padding:7px 12px;font-size:13px;cursor:pointer;box-shadow:none;font-weight:600;width:auto}
.mk .mk-btn2:hover{filter:brightness(1.12);transform:none;box-shadow:none}
.mk .mk-link{background:none;border:none;padding:0;color:var(--mk-gold);cursor:pointer;font-size:inherit;box-shadow:none;
font-weight:400;text-decoration:underline}
.mk .mk-link:hover{transform:none;box-shadow:none}
.mk-layout{display:grid;grid-template-columns:240px minmax(0,1fr);gap:16px;align-items:start}
.mk-side{position:sticky;top:76px;max-height:calc(100vh - 90px);overflow:auto;padding-right:2px;
scrollbar-width:thin;scrollbar-color:#4E3E1D transparent}
.mk-top{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.mk-search{position:relative;flex:1 1 260px;min-width:200px}
.mk-search input{padding-left:32px;font-size:14px;height:38px}
.mk-search svg{position:absolute;left:10px;top:11px;width:16px;height:16px;fill:none;stroke:var(--mk-dash);stroke-width:2}
.mk-count{font-weight:700;color:var(--mk-title);white-space:nowrap}
.mk-sortbox{flex:0 1 270px}
.mk-sortbox select{height:38px}
.mk-meta{margin-top:6px;font-size:12px;color:var(--mk-text);display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.mk-cats{list-style:none;margin:0;padding:0}
.mk-cats li{margin:0}
.mk-cat{display:flex;justify-content:space-between;gap:8px;padding:6px 8px;border-left:3px solid transparent;
border-radius:0 6px 6px 0;cursor:pointer;color:var(--mk-title);font-size:13.5px;user-select:none}
.mk-cat:hover{background:#221c13}
.mk-cat.on{background:var(--mk-sel);color:var(--mk-gold);border-left-color:var(--mk-gold)}
.mk-cat .n{color:var(--mk-text);font-size:12px;font-variant-numeric:tabular-nums}
.mk-cat.on .n{color:var(--mk-gold)}
.mk-cat.empty{opacity:.45}
.mk-subs{list-style:none;margin:0 0 4px 12px;padding:0;display:none}
.mk-subs.open{display:block}
.mk-subs .mk-cat{font-size:12.5px;padding:4px 8px}
.mk-f{margin-bottom:10px}
.mk-f>label,.mk-f .mk-lab{display:block;font-size:12px;color:var(--mk-text);margin-bottom:4px}
.mk-f .mk-pair{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.mk-f .mk-check{display:block;font-size:12.5px;color:var(--mk-title);margin:4px 0;cursor:pointer}
.mk-f .mk-hint{font-size:11px;color:var(--mk-dash);margin-top:3px}
.mk-bonusrow{display:grid;grid-template-columns:1fr 64px;gap:6px;margin-bottom:6px}
.mk-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.mk-actions .mk-btn{flex:1}
.mk-chips{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 0}
.mk-chip{font-size:12px;padding:3px 8px;border-radius:999px;background:var(--mk-tag-bg);border:1px solid var(--mk-tag-line);color:var(--mk-tag)}
.mk-chip button{margin-left:6px}
.mk-charbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0}
.mk-charbar select{width:auto;min-width:220px}
.mk-list{display:flex;flex-direction:column;gap:8px}
.mk-offer{display:grid;grid-template-columns:22px 50px minmax(0,1fr) auto;gap:12px;align-items:start;
background:linear-gradient(180deg,var(--mk-card-a),var(--mk-card-b));border:1px solid var(--mk-line);border-radius:10px;
padding:10px 12px;transition:border-color .15s}
.mk-offer:hover{border-color:var(--mk-hover)}
.mk-offer>input[type=checkbox]{margin-top:16px}
.mk-offer.closed{opacity:.55;filter:grayscale(.6)}
.mk-icon{width:48px;height:48px;background:#241F17;border:1px solid var(--mk-line);border-radius:6px;display:flex;
align-items:center;justify-content:center;overflow:hidden;cursor:help}
.mk-icon img{max-width:44px;max-height:44px;image-rendering:pixelated}
.mk-icon .ph{font-weight:700;color:var(--mk-dash);font-size:18px}
.mk-name{font-size:15.5px;font-weight:700;color:var(--mk-title);cursor:pointer;word-break:break-word}
.mk-name:hover{text-decoration:underline}
.mk-name .plus{color:var(--mk-gold)}
.mk-name .stack{color:var(--mk-text);font-weight:600;font-size:13px;margin-left:4px}
.mk-tags{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:5px;font-size:12px;min-width:0}
.mk-tag{padding:1px 7px;border-radius:5px;background:var(--mk-tag-bg);border:1px solid var(--mk-tag-line);color:var(--mk-tag);
white-space:nowrap}
.mk-tag.bad{background:var(--mk-bad-bg);border-color:var(--mk-bad-line);color:var(--mk-bad)}
.mk-tag.ok{background:var(--mk-ok-bg);border-color:var(--mk-ok-line);color:var(--mk-ok)}
.mk-seller{display:inline-flex;align-items:center;gap:5px;min-width:0;max-width:100%;color:var(--mk-text)}
.mk-seller img{width:16px;height:16px;flex:none}
.mk-seller .who{color:var(--mk-title);cursor:pointer}
.mk-seller .who:hover{text-decoration:underline}
.mk-seller .shopname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px}
.mk-bon{margin-top:6px}
.mk-bon-list{display:none;margin:6px 0 0;padding:8px 10px;border:1px solid var(--mk-line);border-radius:8px;background:#15120D;
font-size:12.5px}
.mk-bon-list.open{display:block}
.mk-bon-list .l{display:flex;justify-content:space-between;gap:10px;padding:2px 0}
.mk-bon-list .l.max .t{color:var(--mk-gold);font-weight:700}
.mk-bon-list .r{color:var(--mk-dash);font-size:11px;white-space:nowrap}
.mk-bon-list .sub{border-top:1px dashed var(--mk-dash);margin-top:5px;padding-top:5px;color:var(--mk-tag)}
.mk-right{display:flex;flex-direction:column;align-items:flex-end;gap:5px;text-align:right;min-width:150px}
.mk-price{font-size:18px;font-weight:700;color:var(--mk-gold);white-space:nowrap}
.mk-price small{font-size:12px;color:var(--mk-text);font-weight:400;margin-left:3px}
.mk-unit{font-size:12px;color:var(--mk-text);white-space:nowrap}
.mk-deal{font-size:12px;padding:2px 8px;border-radius:5px;background:var(--mk-ok-bg);border:1px solid var(--mk-ok-line);
color:var(--mk-ok);white-space:nowrap}
.mk-deal .q{display:inline-block;margin-left:5px;width:15px;height:15px;line-height:13px;border-radius:50%;
border:1px solid var(--mk-ok);text-align:center;font-size:10px;cursor:help}
.mk-dear{font-size:11.5px;color:var(--mk-dash)}
.mk-pager{display:flex;gap:10px;justify-content:center;align-items:center;margin:14px 0;flex-wrap:wrap}
.mk-pager select{width:auto}
.mk-state{text-align:center;padding:36px 14px;color:var(--mk-text)}
.mk-state b{display:block;color:var(--mk-title);font-size:16px;margin-bottom:10px}
.mk-tip{position:fixed;z-index:60;max-width:330px;background:#120f0a;border:1px solid var(--mk-hover);border-radius:8px;
padding:9px 11px;font-size:12.5px;color:var(--mk-tag);pointer-events:none;display:none;box-shadow:0 10px 26px rgba(0,0,0,.6)}
.mk-tip .nm{color:var(--mk-title);font-weight:700;font-size:14px;margin-bottom:4px}
.mk-tip .nm .plus{color:var(--mk-gold)}
.mk-tip .hr{border-top:1px solid var(--mk-line);margin:5px 0}
.mk-tip .bn{color:#9fd3ff}
.mk-tip .bn.max{color:var(--mk-gold)}
.mk-cmpbar{position:fixed;left:50%;transform:translateX(-50%);bottom:14px;z-index:50;display:none;gap:10px;align-items:center;
background:#1c1812;border:1px solid var(--mk-hover);border-radius:12px;padding:8px 12px;box-shadow:0 10px 30px rgba(0,0,0,.6)}
.mk-cmpbar.on{display:flex}
.mk-modal{position:fixed;inset:0;z-index:70;background:rgba(0,0,0,.66);display:none;align-items:flex-start;justify-content:center;
padding:40px 12px;overflow:auto}
.mk-modal.on{display:flex}
.mk-modal .box{background:linear-gradient(180deg,var(--mk-card-a),var(--mk-card-b));border:1px solid var(--mk-hover);
border-radius:12px;padding:16px;max-width:1100px;width:100%}
.mk-cmp{display:grid;gap:10px}
.mk-cmp .col{border:1px solid var(--mk-line);border-radius:8px;padding:10px;background:#15120D;min-width:0}
.mk-cmp .row{display:flex;justify-content:space-between;gap:8px;padding:3px 0;border-bottom:1px dashed #2a2318;font-size:12.5px}
.mk-cmp .row span:first-child{color:var(--mk-text)}
.mk-chart{margin-bottom:10px}
.mk-chart svg{width:100%;height:150px;display:block}
.mk-toast{position:fixed;right:16px;bottom:16px;z-index:80;max-width:380px;padding:10px 14px;border-radius:10px;
background:#1c1812;border:1px solid var(--mk-hover);color:var(--mk-title);font-size:13.5px;display:none;
box-shadow:0 10px 30px rgba(0,0,0,.6)}
.mk-toast.on{display:block}
.mk-toast.ok{border-color:var(--mk-ok-line);color:var(--mk-ok)}
.mk-toast.bad{border-color:var(--mk-bad-line);color:var(--mk-bad)}
.mk-hist{font-size:12px;color:var(--mk-text)}
.mk-hist div{padding:3px 0;border-bottom:1px dashed #2a2318}
.mk-spin{display:inline-block;width:14px;height:14px;border:2px solid var(--mk-hover);border-top-color:var(--mk-gold);
border-radius:50%;animation:mkspin .8s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes mkspin{to{transform:rotate(360deg)}}
.mk-sidetoggle{display:none}
@media (max-width:900px){
 .mk-layout{grid-template-columns:minmax(0,1fr)}
 .mk-side{position:static;max-height:none;display:none}
 .mk-side.open{display:block}
 .mk-sidetoggle{display:inline-block}
 .mk-offer{grid-template-columns:22px 50px minmax(0,1fr)}
 .mk-right{grid-column:2 / -1;flex-direction:row;flex-wrap:wrap;align-items:center;justify-content:flex-start;text-align:left;min-width:0}
 .mk-seller .shopname{max-width:160px}
 .mk-sortbox{flex:1 1 100%}
}
</style>
"""

BODY = r"""
<div class="mk" id="mk">
<a class="mk-back" href="{{ url_for('dash') }}">{{ T.back }}</a>
<h2 class="mk-h">🏪 {{ T.title }} <span class="mk-badge-exp">{{ T.experimental }}</span></h2>
{% if not enabled %}
<div class="mk-card"><p class="mk-muted">{{ T.not_here }}</p></div>
{% else %}
<div class="mk-card" style="padding:12px 14px">
 <div class="mk-top">
  <button type="button" class="mk-btn2 mk-sidetoggle" id="mk-sidetoggle">☰ {{ T.filters_toggle }}</button>
  <div class="mk-search">
   <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="22" y2="22"/></svg>
   <input id="mk-q" type="search" maxlength="60" autocomplete="off" placeholder="{{ T.search_ph }}" aria-label="{{ T.search_ph }}">
  </div>
  <span class="mk-count" id="mk-count">…</span>
  <div class="mk-sortbox"><select id="mk-sort" aria-label="{{ T.sort }}">
   {% for key in sorts %}<option value="{{ key }}">{{ T['sort_' + key] }}</option>{% endfor %}
  </select></div>
 </div>
 <div class="mk-meta"><span id="mk-when">…</span> · <button type="button" class="mk-link" id="mk-refresh">{{ T.refresh }}</button>
  <span id="mk-chips" class="mk-chips" style="margin:0"></span></div>
</div>
<div class="mk-layout">
 <aside class="mk-side" id="mk-side">
  <div class="mk-card"><div class="mk-sec">{{ T.categories }}</div><ul class="mk-cats" id="mk-cats"></ul></div>
  <div class="mk-card" id="mk-filters"><div class="mk-sec">{{ T.filters }}</div>
   <div class="mk-f"><span class="mk-lab">{{ T.f_price }}</span>
    <div class="mk-pair"><div><input id="mk-pmin" placeholder="{{ T.f_from }}" inputmode="decimal"><div class="mk-err">{{ T.bad_value }}</div></div>
    <div><input id="mk-pmax" placeholder="{{ T.f_to }}" inputmode="decimal"><div class="mk-err">{{ T.bad_value }}</div></div></div>
    <div class="mk-hint">{{ T.f_price_hint }}</div>
    <label class="mk-check"><input type="checkbox" id="mk-unit">{{ T.f_unit }}</label></div>
   <div class="mk-f"><span class="mk-lab">{{ T.f_level }}</span>
    <div class="mk-pair"><div><input id="mk-lmin" placeholder="{{ T.f_level_from }}" inputmode="numeric"><div class="mk-err">{{ T.bad_value }}</div></div>
    <div><input id="mk-lmax" placeholder="{{ T.f_level_to }}" inputmode="numeric"><div class="mk-err">{{ T.bad_value }}</div></div></div></div>
   <div class="mk-f"><span class="mk-lab">{{ T.f_plus }}</span>
    <div class="mk-pair"><select id="mk-rmin" aria-label="{{ T.f_plus }} {{ T.f_from }}"><option value="">{{ T.f_from }}: {{ T.f_any }}</option>
     {% for n in range(0, 20) %}<option value="{{ n }}">+{{ n }}</option>{% endfor %}</select>
    <select id="mk-rmax" aria-label="{{ T.f_plus }} {{ T.f_to }}"><option value="">{{ T.f_to }}: {{ T.f_any }}</option>
     {% for n in range(0, 20) %}<option value="{{ n }}">+{{ n }}</option>{% endfor %}</select></div></div>
   <div class="mk-f"><span class="mk-lab">{{ T.f_class }}</span>
    <select id="mk-cls"><option value="">{{ T.f_class_all }}</option>
     {% for key in class_keys %}<option value="{{ key }}">{{ T.classes[loop.index0] }}</option>{% endfor %}</select>
    <label class="mk-check"><input type="checkbox" id="mk-mine">{{ T.f_mine }}</label></div>
   <div class="mk-f"><span class="mk-lab">{{ T.f_bonus }}</span>
    <div id="mk-bonuses"></div>
    <button type="button" class="mk-link" id="mk-bonus-add">{{ T.f_bonus_add }}</button></div>
   <div class="mk-f"><span class="mk-lab">{{ T.f_nbmin }}</span>
    <select id="mk-nbmin"><option value="">0</option>{% for n in range(1, 6) %}<option value="{{ n }}">{{ n }}</option>{% endfor %}</select>
    <label class="mk-check"><input type="checkbox" id="mk-maxonly">{{ T.f_maxonly }}</label>
    <select id="mk-nmaxmin" aria-label="{{ T.f_nmaxmin }}"><option value="">{{ T.f_nmaxmin }}: 1</option>
     {% for n in range(2, 5) %}<option value="{{ n }}">{{ T.f_nmaxmin }}: {{ n }}</option>{% endfor %}</select></div>
   <div class="mk-f mk-weapon-only"><span class="mk-lab">{{ T.f_avg }}</span>
    <div class="mk-pair"><div><input id="mk-avgmin" placeholder="{{ T.f_from }}" inputmode="numeric"><div class="mk-err">{{ T.bad_value }}</div></div>
    <div><input id="mk-avgmax" placeholder="{{ T.f_to }}" inputmode="numeric"><div class="mk-err">{{ T.bad_value }}</div></div></div></div>
   <div class="mk-f mk-weapon-only"><span class="mk-lab">{{ T.f_skl }}</span>
    <div class="mk-pair"><div><input id="mk-sklmin" placeholder="{{ T.f_from }}" inputmode="numeric"><div class="mk-err">{{ T.bad_value }}</div></div>
    <div><input id="mk-sklmax" placeholder="{{ T.f_to }}" inputmode="numeric"><div class="mk-err">{{ T.bad_value }}</div></div></div></div>
   <div class="mk-f mk-gear-only"><span class="mk-lab">{{ T.f_ks }}</span>
    <select id="mk-ks"><option value="">{{ T.f_ks_any }}</option><option value="has">{{ T.f_ks_has }}</option>
     {% for stone in stones %}<option value="{{ stone.v }}">{{ stone.n }}</option>{% endfor %}</select></div>
   <div class="mk-f"><span class="mk-lab">{{ T.f_emp }}</span>
    <select id="mk-emp"><option value="">{{ T.f_emp_all }}</option>
     {% for name in T.empires %}<option value="{{ loop.index }}">{{ name }}</option>{% endfor %}</select></div>
   <div class="mk-f"><span class="mk-lab">{{ T.f_seller }}</span>
    <select id="mk-seller"><option value="">{{ T.f_seller_all }}</option><option value="bot">{{ T.f_seller_bot }}</option>
     <option value="person">{{ T.f_seller_person }}</option></select>
    <input id="mk-sname" maxlength="60" placeholder="{{ T.f_sname }}" style="margin-top:6px"></div>
   <div class="mk-f"><label class="mk-check"><input type="checkbox" id="mk-deals">{{ T.f_deals }}</label>
    <input id="mk-dmin" inputmode="numeric" placeholder="{{ T.f_dmin }}" aria-label="{{ T.f_dmin }}"><div class="mk-err">{{ T.bad_value }}</div></div>
   <div class="mk-f"><label class="mk-check" title="{{ T.f_hideslip_hint }}"><input type="checkbox" id="mk-hideslip" checked>{{ T.f_hideslip }}</label>
    <label class="mk-check"><input type="checkbox" id="mk-expired">{{ T.f_expired }}</label></div>
   <div class="mk-actions"><button type="button" class="mk-btn" id="mk-apply">{{ T.apply }}</button>
    <button type="button" class="mk-btn2" id="mk-clear">{{ T.clear_filters }}</button></div>
  </div>
  <div class="mk-card"><div class="mk-sec">{{ T.tp_settings }}</div>
   <label class="mk-lab mk-muted" for="mk-cost">{{ T.tp_cost }}</label>
   <div style="display:flex;gap:6px;margin-top:4px"><input id="mk-cost" inputmode="numeric" value="{{ tp_cost }}">
   <button type="button" class="mk-btn2" id="mk-cost-save">{{ T.tp_cost_save }}</button></div>
   <div class="mk-sec" style="margin-top:12px">{{ T.tp_history }}</div><div class="mk-hist" id="mk-hist">…</div>
  </div>
 </aside>
 <section>
  <div class="mk-charbar"><label class="mk-muted" for="mk-me" title="{{ T.character_hint }}">{{ T.character }}:</label>
   <select id="mk-me" title="{{ T.character_hint }}"><option value="">{{ T.character_none }}</option>
    {% for p in persons %}<option value="{{ p.pid }}">{{ p.name }} · {{ T.classes[p.cls] }} · lv {{ p.level }}</option>{% endfor %}
   </select></div>
  <div id="mk-chart" class="mk-card mk-chart" style="display:none"></div>
  <div class="mk-list" id="mk-list"></div>
  <div class="mk-pager" id="mk-pager"></div>
 </section>
</div>
<div class="mk-cmpbar" id="mk-cmpbar"><button type="button" class="mk-btn" id="mk-cmp-open"></button>
 <button type="button" class="mk-btn2" id="mk-cmp-clear">{{ T.compare_clear }}</button></div>
<div class="mk-modal" id="mk-modal" role="dialog" aria-modal="true"><div class="box">
 <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
  <b style="font-size:16px">{{ T.compare_title }}</b><button type="button" class="mk-btn2" id="mk-cmp-close">{{ T.compare_close }}</button></div>
 <div class="mk-cmp" id="mk-cmp"></div></div></div>
<div class="mk-tip" id="mk-tip"></div>
<div class="mk-toast" id="mk-toast" role="status" aria-live="polite"></div>
<script type="application/json" id="mk-data">{{ data|tojson }}</script>
<script>{% raw %}__SCRIPT__{% endraw %}</script>
{% endif %}
</div>
"""

SCRIPT = r"""
(function(){
'use strict';
var D = JSON.parse(document.getElementById('mk-data').textContent);
var T = D.texts, CSRF = D.csrf;
var $ = function(id){ return document.getElementById(id); };
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function fmt(key, args){ var s = T[key] || key; for (var k in (args||{})) s = s.split('{'+k+'}').join(args[k]); return s; }
function num(n){ n = Math.round(Number(n) || 0); return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' '); }
function bonusesWord(n){
  if (n === 1) return T.bonuses_1;
  var t = n % 10, h = n % 100;
  if (D.lang === 'pl' && t >= 2 && t <= 4 && (h < 12 || h > 14)) return fmt('bonuses_few', {n: n});
  return fmt('bonuses_n', {n: n});
}

// ---- state <-> URL --------------------------------------------------------
var FIELDS = ['q','cat','sub','pmin','pmax','unit','lmin','lmax','rmin','rmax','cls','mine','me','nbmin','maxonly',
  'nmaxmin','avgmin','avgmax','sklmin','sklmax','ks','emp','seller','sname','shop','vnum','var','deals','dmin',
  'hideslip','expired','sort','page','per','b1','b1v','b2','b2v','b3','b3v'];
var DEFAULTS = D.defaults;
var state = {};
function readUrl(){
  var p = new URLSearchParams(location.search); state = {};
  FIELDS.forEach(function(k){ var v = p.get(k); state[k] = (v === null ? DEFAULTS[k] : v); });
  try { if (!p.get('me')) { var m = localStorage.getItem('mk_me'); if (m) state.me = m; } } catch(e){}
}
function writeUrl(push){
  var p = new URLSearchParams();
  FIELDS.forEach(function(k){ var v = state[k]; if (v !== undefined && v !== null && String(v) !== String(DEFAULTS[k])) p.set(k, v); });
  var url = location.pathname + (p.toString() ? '?' + p.toString() : '');
  if (push) history.pushState(null, '', url); else history.replaceState(null, '', url);
}

// ---- the form ---------------------------------------------------------------
var TEXT_INPUTS = ['q','pmin','pmax','lmin','lmax','avgmin','avgmax','sklmin','sklmax','sname','dmin'];
var SELECTS = ['sort','rmin','rmax','cls','nbmin','nmaxmin','ks','emp','seller'];
var CHECKS = ['unit','mine','maxonly','deals','hideslip','expired'];
function parsePrice(s){
  s = String(s || '').trim().toLowerCase().replace(/ /g, ' ').replace(/\s*yang$/, '');
  if (!s) return null;
  var m = s.replace(/ /g, '').match(/^(\d+)(?:[.,](\d+))?(k{1,4})$/);
  if (m) { var sc = Math.pow(1000, m[3].length), v = parseInt(m[1], 10) * sc;
    if (m[2]) v += Math.floor(parseInt(m[2], 10) * sc / Math.pow(10, m[2].length)); return v; }
  if (/^\d+$/.test(s)) return parseInt(s, 10);
  if (/^\d{1,3}([ .,_]\d{3})+$/.test(s)) return parseInt(s.replace(/[ .,_]/g, ''), 10);
  return NaN;
}
function validInt(s, lo, hi){ s = String(s || '').trim(); if (!s) return true; if (!/^\d{1,9}$/.test(s)) return false;
  var n = parseInt(s, 10); return n >= lo && n <= hi; }
var RULES = {pmin: function(v){ var p = parsePrice(v); return p === null || !isNaN(p); }, pmax: null,
  lmin: function(v){ return validInt(v, 0, 255); }, lmax: null, avgmin: function(v){ return validInt(v, 0, 200); },
  avgmax: null, sklmin: null, sklmax: null, dmin: function(v){ return validInt(v, 0, 100); }};
RULES.pmax = RULES.pmin; RULES.lmax = RULES.lmin; RULES.avgmax = RULES.sklmin = RULES.sklmax = RULES.avgmin;
function validate(){
  var ok = true;
  Object.keys(RULES).forEach(function(k){
    var el = $('mk-' + k); if (!el) return;
    var good = RULES[k](el.value); el.classList.toggle('mk-bad', !good); if (!good) ok = false;
  });
  return ok;
}
function toForm(){
  TEXT_INPUTS.forEach(function(k){ var el = $('mk-' + k); if (el) el.value = state[k] || ''; });
  SELECTS.forEach(function(k){ var el = $('mk-' + k); if (el) el.value = state[k] || (k === 'sort' ? 'deals' : ''); });
  CHECKS.forEach(function(k){ var el = $('mk-' + k); if (el) el.checked = String(state[k]) === '1'; });
  $('mk-me').value = state.me || '';
  drawBonusRows();
  validate();
}
function fromForm(){
  TEXT_INPUTS.forEach(function(k){ var el = $('mk-' + k); var v = el ? el.value.trim() : '';
    state[k] = (RULES[k] && !RULES[k](v)) ? '' : v; });
  SELECTS.forEach(function(k){ var el = $('mk-' + k); if (el) state[k] = el.value; });
  CHECKS.forEach(function(k){ var el = $('mk-' + k); if (el) state[k] = el.checked ? '1' : '0'; });
  for (var i = 1; i <= 3; i++) {
    var b = $('mk-b' + i), bv = $('mk-b' + i + 'v');
    state['b' + i] = b ? b.value : ''; state['b' + i + 'v'] = (bv && validInt(bv.value, 0, 100000)) ? bv.value.trim() : '';
  }
}
var bonusRows = 1;
function drawBonusRows(){
  var box = $('mk-bonuses'); box.innerHTML = '';
  for (var i = 3; i >= 1; i--) if (state['b' + i]) { bonusRows = Math.max(bonusRows, i); break; }
  for (var i = 1; i <= bonusRows; i++) {
    var row = document.createElement('div'); row.className = 'mk-bonusrow';
    var opts = '<option value="">' + esc(T.f_bonus_none) + '</option>' + D.bonuses.map(function(b){
      return '<option value="' + b.p + '">' + esc(b.t) + '</option>'; }).join('');
    row.innerHTML = '<select id="mk-b' + i + '">' + opts + '</select><input id="mk-b' + i +
      'v" inputmode="numeric" placeholder="' + esc(T.f_bonus_min) + '" aria-label="' + esc(T.f_bonus_min) + '">';
    box.appendChild(row);
    $('mk-b' + i).value = state['b' + i] || ''; $('mk-b' + i + 'v').value = state['b' + i + 'v'] || '';
  }
  $('mk-bonus-add').style.display = bonusRows >= 3 ? 'none' : '';
}
function weaponFilters(){
  var weapons = state.cat === 'weapons', gear = ['weapons','armour','shields_helmets','jewellery','boots',''].indexOf(state.cat) >= 0;
  document.querySelectorAll('.mk-weapon-only').forEach(function(el){ el.style.display = weapons ? '' : 'none'; });
  document.querySelectorAll('.mk-gear-only').forEach(function(el){ el.style.display = gear ? '' : 'none'; });
}

// ---- loading --------------------------------------------------------------
var timer = null, seq = 0, last = null, polling = null;
function schedule(){ clearTimeout(timer); timer = setTimeout(function(){ apply(false); }, 800); }
function apply(push){ if (!validate()) return; fromForm(); state.page = '1'; load(push); }
function query(extra){
  var p = new URLSearchParams();
  FIELDS.forEach(function(k){ var v = state[k]; if (v !== undefined && v !== null && v !== '') p.set(k, v); });
  if (extra) for (var k in extra) p.set(k, extra[k]);
  return p.toString();
}
function load(push, extra){
  writeUrl(push); weaponFilters(); drawChips();
  var my = ++seq;
  $('mk-count').innerHTML = '<span class="mk-spin"></span>';
  fetch('/market/api/offers?' + query(extra), {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
    .then(function(r){
      if (r.status === 429) throw {kind: 'fast'};
      if (r.status === 401) throw {kind: 'login'};
      var ct = r.headers.get('content-type') || '';
      if (!r.ok || ct.indexOf('json') < 0) throw {kind: 'error'};
      return r.json();
    })
    .then(function(data){ if (my !== seq) return; last = data; draw(data);
      if (data.building || !data.generated_at) { clearTimeout(polling); polling = setTimeout(function(){ load(false); }, 2500); } })
    .catch(function(e){ if (my !== seq) return; drawError(e && e.kind); });
}
function drawError(kind){
  var msg = kind === 'fast' ? T.too_fast : kind === 'login' ? T.login : T.load_error;
  $('mk-count').textContent = '';
  $('mk-list').innerHTML = '<div class="mk-card mk-state"><b>' + esc(msg) + '</b><button type="button" class="mk-btn" id="mk-retry">' +
    esc(T.retry) + '</button></div>';
  $('mk-pager').innerHTML = '';
  $('mk-retry').onclick = function(){ load(false); };
  if (kind === 'fast') setTimeout(function(){ load(false); }, 1500);
}

// ---- drawing ----------------------------------------------------------------
function drawCats(counts){
  var ul = $('mk-cats'), html = '';
  var all = counts ? counts.all : 0;
  html += '<li><div class="mk-cat' + (!state.cat ? ' on' : '') + '" data-cat="" data-sub=""><span>' + esc(T.cat_all) +
    '</span><span class="n">' + num(all) + '</span></div></li>';
  D.categories.forEach(function(c){
    var cc = counts && counts.cats[c.key] ? counts.cats[c.key] : {n: 0, subs: {}};
    var on = state.cat === c.key && !state.sub;
    html += '<li><div class="mk-cat' + (on ? ' on' : '') + (cc.n ? '' : ' empty') + '" data-cat="' + c.key + '" data-sub=""><span>' +
      esc(c.name) + (c.subs.length ? ' ▾' : '') + '</span><span class="n">' + num(cc.n) + '</span></div>';
    if (c.subs.length) {
      html += '<ul class="mk-subs' + (state.cat === c.key ? ' open' : '') + '">';
      c.subs.forEach(function(s){
        var n = cc.subs[s.key] || 0;
        html += '<li><div class="mk-cat' + (state.cat === c.key && state.sub === s.key ? ' on' : '') + (n ? '' : ' empty') +
          '" data-cat="' + c.key + '" data-sub="' + s.key + '"><span>' + esc(s.name) + '</span><span class="n">' + num(n) + '</span></div></li>';
      });
      html += '</ul>';
    }
    html += '</li>';
  });
  ul.innerHTML = html;
}
function drawChips(){
  var box = $('mk-chips'), html = '';
  if (state.shop) html += '<span class="mk-chip">' + esc(fmt('only_shop', {name: (last && last.shop ? last.shop.label : '#' + state.shop)})) +
    '<button type="button" class="mk-link" data-chip="shop">' + esc(T.remove) + '</button></span>';
  if (state.vnum) html += '<span class="mk-chip">' + esc(fmt('only_item', {name: (last && last.item ? last.item : '#' + state.vnum)})) +
    '<button type="button" class="mk-link" data-chip="vnum">' + esc(T.remove) + '</button></span>';
  box.innerHTML = html;
}
function myClass(){
  var me = parseInt(state.me || '0', 10); if (!me) return -1;
  for (var i = 0; i < D.persons.length; i++) if (D.persons[i].pid === me) return D.persons[i].cls;
  return -1;
}
function classBadges(o){
  var mine = myClass();
  if (o.cls_all) return mine >= 0 ? '' : '';
  var names = o.classes.map(function(c){ return T.classes[c]; });
  var html = '<span class="mk-tag">' + esc(names.join(', ')) + '</span>';
  if (mine >= 0 && o.classes.indexOf(mine) < 0) html += '<span class="mk-tag bad">' + esc(T.not_for_you) + '</span>';
  return html;
}
function bonusList(o){
  var html = '';
  o.bonuses.forEach(function(b){
    html += '<div class="l' + (b.max ? ' max' : '') + '"><span class="t">' + esc(b.t) + '</span><span class="r">' +
      (b.pve || b.pvp ? esc(fmt('pve_pvp', {a: b.pve || '–', b: b.pvp || '–'})) : '') + '</span></div>';
  });
  var sub = [];
  if (o.avg) sub.push(esc(T.avg) + ' ' + o.avg + '%');
  if (o.skl) sub.push(esc(T.skl) + ' ' + o.skl + '%');
  if (o.stones.length) sub.push(esc(T.stones) + ': ' + o.stones.map(function(s){ return esc(s.n); }).join(', '));
  if (sub.length) html += '<div class="sub">' + sub.join(' · ') + '</div>';
  return html;
}
function offerHtml(o, i){
  var plus = o.plus >= 0 ? ' <span class="plus">+' + o.plus + '</span>' : '';
  var stack = o.cnt > 1 ? '<span class="stack">×' + num(o.cnt) + '</span>' : '';
  var icon = o.icon ? '<img src="' + esc(o.icon) + '" alt="" loading="lazy">' : '<span class="ph">' + esc((o.name || '?').charAt(0)) + '</span>';
  var tags = '';
  if (o.lvl > 0) tags += '<span class="mk-tag">' + esc(fmt('from_level', {n: o.lvl})) + '</span>';
  tags += classBadges(o);
  if (!o.running) tags += '<span class="mk-tag bad">' + esc(T.shop_closed) + '</span>';
  if (o.slip) tags += '<span class="mk-tag bad">' + esc(T.slip) + '</span>';
  var flag = o.emp ? '<img src="/static/empires/' + ['', 'shinsoo', 'chunjo', 'jinno'][o.emp] + '.png" alt="' + esc(T.empires[o.emp - 1]) + '" title="' + esc(T.empires[o.emp - 1]) + '">' : '';
  tags += '<span class="mk-seller">' + flag + '<span class="who" data-shop="' + o.owner + '" title="' + esc(T.seller_title) + '">' +
    esc(o.seller || ('#' + o.owner)) + '</span> · <span class="shopname" title="' + esc(o.shop_name + ' — ' + o.where) + '">' +
    esc(o.shop_name) + '</span></span>';
  var bon = o.bonuses.length || o.avg || o.skl || o.stones.length;
  var bonBtn = bon ? '<div class="mk-bon"><button type="button" class="mk-btn2" data-bon="' + i + '" style="padding:3px 9px;font-size:12px">' +
    esc(o.bonuses.length ? bonusesWord(o.bonuses.length) : T.stones) + ' ▾</button><div class="mk-bon-list" id="mk-bon-' + i + '">' + bonusList(o) + '</div></div>' : '';
  var right = '<div class="mk-price">' + num(o.price) + '<small>' + esc(T.yang) + '</small></div>';
  if (o.cnt > 1) right += '<div class="mk-unit">' + esc(fmt('per_unit', {p: num(o.unit)})) + '</div>';
  if (o.deal !== null && o.deal >= D.deal_badge) {
    right += '<span class="mk-deal" title="' + esc(fmt('ref_price', {p: num(o.ref)})) + '">' + esc(fmt('deal', {n: o.deal})) +
      (o.deal >= D.deal_suspect ? '<span class="q" title="' + esc(T.deal_suspect) + '">?</span>' : '') + '</span>';
  } else if (o.deal !== null && o.deal < 0) {
    right += '<span class="mk-dear" title="' + esc(fmt('ref_price', {p: num(o.ref)})) + '">' + esc(fmt('dearer', {n: -o.deal})) + '</span>';
  }
  if (o.running) right += '<button type="button" class="mk-btn" data-tp="' + i + '" title="' + esc(T.tp_title) + '">' + esc(T.tp) + '</button>';
  return '<div class="mk-offer' + (o.running ? '' : ' closed') + '"><input type="checkbox" data-cmp="' + o.id + '" title="' +
    esc(T.compare_pick) + '"' + (picked[o.id] ? ' checked' : '') + '><div class="mk-icon" data-tip="' + i + '">' + icon +
    '</div><div style="min-width:0"><div class="mk-name" data-item="' + i + '" title="' + esc(T.item_title) + '">' + esc(o.name) +
    plus + stack + '</div><div class="mk-tags">' + tags + '</div>' + bonBtn + '</div><div class="mk-right">' + right + '</div></div>';
}
function draw(data){
  $('mk-when').textContent = data.generated_at ? fmt('data_from', {t: data.generated_text}) : T.building;
  if (data.building && data.generated_at) $('mk-when').innerHTML = '<span class="mk-spin"></span>' + esc(fmt('data_from', {t: data.generated_text}));
  $('mk-count').textContent = fmt('offers_n', {n: num(data.total)});
  Object.keys(data.errors || {}).forEach(function(k){ var el = $('mk-' + k); if (el) el.classList.add('mk-bad'); });
  drawCats(data.counts);
  drawChips();
  drawChart(data.chart);
  var list = $('mk-list');
  if (!data.generated_at) { list.innerHTML = '<div class="mk-card mk-state"><span class="mk-spin"></span>' + esc(T.building) +
      (data.error ? '<br><small>' + esc(data.error) + '</small>' : '') + '</div>'; $('mk-pager').innerHTML = ''; return; }
  if (!data.rows.length) {
    list.innerHTML = '<div class="mk-card mk-state"><b>' + esc(T.empty) + '</b><button type="button" class="mk-btn" id="mk-empty-clear">' +
      esc(T.clear_filters) + '</button></div>';
    $('mk-empty-clear').onclick = clearAll; $('mk-pager').innerHTML = ''; return;
  }
  list.innerHTML = data.rows.map(offerHtml).join('');
  var pg = '<button type="button" class="mk-btn2" data-page="' + (data.page - 1) + '"' + (data.page <= 1 ? ' disabled' : '') + '>' + esc(T.page_prev) +
    '</button><span class="mk-muted">' + esc(fmt('page_of', {a: data.page, b: data.pages})) + '</span><button type="button" class="mk-btn2" data-page="' +
    (data.page + 1) + '"' + (data.page >= data.pages ? ' disabled' : '') + '>' + esc(T.page_next) + '</button><label class="mk-muted">' +
    esc(T.per_page) + ' <select id="mk-per">' + [25, 50, 100].map(function(n){ return '<option' + (n === data.per ? ' selected' : '') + '>' + n + '</option>'; }).join('') +
    '</select></label>';
  $('mk-pager').innerHTML = pg;
  $('mk-per').onchange = function(){ state.per = this.value; state.page = '1'; load(true); };
}
function drawChart(chart){
  var box = $('mk-chart');
  if (!chart) { box.style.display = 'none'; box.innerHTML = ''; return; }
  box.style.display = '';
  var pts = chart.points || [];
  var head = '<div class="mk-sec">' + esc(T.chart_title) + ' — ' + esc(chart.name) + '</div>';
  if (pts.length < 2) { box.innerHTML = head + '<p class="mk-muted">' + esc(T.chart_none) + '</p>'; return; }
  var W = 900, H = 150, L = 64, R = 10, Tm = 8, B = 22;
  var t0 = pts[0][0], t1 = pts[pts.length - 1][0], lo = Infinity, hi = -Infinity;
  pts.forEach(function(p){ lo = Math.min(lo, p[2] || p[1]); hi = Math.max(hi, p[1]); });
  if (hi <= lo) { hi = lo * 1.1 + 1; lo = lo * 0.9; }
  var x = function(t){ return L + (W - L - R) * (t - t0) / Math.max(1, t1 - t0); };
  var y = function(v){ return Tm + (H - Tm - B) * (1 - (v - lo) / (hi - lo)); };
  var line = pts.map(function(p, i){ return (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ' ' + y(p[1]).toFixed(1); }).join(' ');
  var low = pts.map(function(p, i){ return (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ' ' + y(p[2] || p[1]).toFixed(1); }).join(' ');
  var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" aria-label="' + esc(T.chart_title) + '">';
  [lo, (lo + hi) / 2, hi].forEach(function(v){ svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) +
    '" stroke="#332B1D" stroke-dasharray="3 4"/><text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" fill="#A89D84" font-size="11" text-anchor="end">' + num(v) + '</text>'; });
  [t0, t1].forEach(function(t, i){ var d = new Date(t * 1000); svg += '<text x="' + x(t) + '" y="' + (H - 6) + '" fill="#A89D84" font-size="11" text-anchor="' +
    (i ? 'end' : 'start') + '">' + d.toLocaleDateString() + '</text>'; });
  svg += '<path d="' + low + '" fill="none" stroke="#6B6350" stroke-width="1.5"/><path d="' + line + '" fill="none" stroke="#E9B64B" stroke-width="2"/></svg>';
  box.innerHTML = head + svg;
}

// ---- the tooltip --------------------------------------------------------------
var tip = $('mk-tip');
function tipHtml(o){
  var h = '<div class="nm">' + esc(o.name) + (o.plus >= 0 ? ' <span class="plus">+' + o.plus + '</span>' : '') + '</div>';
  if (o.lvl > 0) h += '<div>' + esc(fmt('tt_level', {n: o.lvl})) + '</div>';
  if (!o.cls_all) h += '<div>' + esc(fmt('tt_classes', {c: o.classes.map(function(c){ return T.classes[c]; }).join(', ')})) + '</div>';
  if (o.base.length) h += '<div class="hr"></div>' + o.base.map(function(s){ return '<div>' + esc(s) + '</div>'; }).join('');
  if (o.bonuses.length || o.avg || o.skl) {
    h += '<div class="hr"></div>';
    if (o.avg) h += '<div class="bn">' + esc(T.avg) + ' ' + o.avg + '%</div>';
    if (o.skl) h += '<div class="bn">' + esc(T.skl) + ' ' + o.skl + '%</div>';
    h += o.bonuses.map(function(b){ return '<div class="bn' + (b.max ? ' max' : '') + '">' + esc(b.t) + '</div>'; }).join('');
  }
  if (o.stones.length) h += '<div class="hr"></div>' + o.stones.map(function(s){ return '<div>' + esc(s.n) + '</div>'; }).join('');
  return h;
}
function moveTip(ev){ var w = tip.offsetWidth, hgt = tip.offsetHeight, x = ev.clientX + 16, y = ev.clientY + 14;
  if (x + w > innerWidth - 8) x = ev.clientX - w - 12; if (y + hgt > innerHeight - 8) y = Math.max(8, innerHeight - hgt - 8);
  tip.style.left = x + 'px'; tip.style.top = y + 'px'; }

// ---- comparison ----------------------------------------------------------------
var picked = {};
function drawCmpBar(){
  var n = Object.keys(picked).length;
  $('mk-cmpbar').classList.toggle('on', n >= 1);
  $('mk-cmp-open').textContent = fmt('compare', {n: n});
  $('mk-cmp-open').disabled = n < 2;
}
function openCompare(){
  var items = Object.keys(picked).map(function(k){ return picked[k]; });
  $('mk-cmp').style.gridTemplateColumns = 'repeat(' + items.length + ', minmax(0, 1fr))';
  $('mk-cmp').innerHTML = items.map(function(o){
    var rows = [[T.c_plus, o.plus >= 0 ? '+' + o.plus : '–'], [T.c_level, o.lvl || '–'],
      [T.c_bonuses, o.bonuses.length ? o.bonuses.map(function(b){ return (b.max ? '★ ' : '') + esc(b.t); }).join('<br>') : '–'],
      [T.avg, o.avg ? o.avg + '%' : '–'], [T.skl, o.skl ? o.skl + '%' : '–'],
      [T.stones, o.stones.length ? o.stones.map(function(s){ return esc(s.n); }).join('<br>') : '–'],
      [T.c_price, num(o.price) + ' ' + esc(T.yang) + (o.cnt > 1 ? '<br><small>' + esc(fmt('per_unit', {p: num(o.unit)})) + '</small>' : '')],
      [T.c_deal, o.deal !== null ? o.deal + '%' : '–'], [T.c_seller, esc(o.seller) + ' · ' + esc(o.shop_name)]];
    return '<div class="col"><div class="mk-name" style="cursor:default">' + esc(o.name) + (o.plus >= 0 ? ' <span class="plus">+' + o.plus + '</span>' : '') +
      '</div>' + rows.map(function(r){ return '<div class="row"><span>' + esc(r[0]) + '</span><span style="text-align:right">' +
      (r[0] === T.c_bonuses || r[0] === T.stones || r[0] === T.c_price || r[0] === T.c_seller ? r[1] : esc(r[1])) + '</span></div>'; }).join('') + '</div>';
  }).join('');
  $('mk-modal').classList.add('on');
}

// ---- TP -----------------------------------------------------------------------
var toastTimer = null;
function toast(msg, kind, keep){
  var el = $('mk-toast'); el.className = 'mk-toast on' + (kind ? ' ' + kind : ''); el.innerHTML = msg;
  clearTimeout(toastTimer); if (!keep) toastTimer = setTimeout(function(){ el.className = 'mk-toast'; }, 7000);
}
function post(url, fields){
  var body = new URLSearchParams(); body.set('_csrf', CSRF); for (var k in fields) body.set(k, fields[k]);
  return fetch(url, {method: 'POST', credentials: 'same-origin', body: body, headers: {'Accept': 'application/json'}})
    .then(function(r){ var ct = r.headers.get('content-type') || ''; if (ct.indexOf('json') < 0) throw {kind: 'login'};
      return r.json(); });
}
function teleport(o){
  if (!state.me) { toast(esc(T.tp_need_char), 'bad'); return; }
  toast('<span class="mk-spin"></span>' + esc(T.tp_sending), '', true);
  post('/market/api/tp', {pid: state.me, shop: o.owner}).then(function(r){
    if (!r.ok) { toast(esc(r.message), 'bad'); loadHistory(); return; }
    var started = Date.now();
    var tick = function(){
      // The server withdraws an order nobody answered at fifteen seconds; a
      // page that cannot reach the server stops asking at thirty.
      if (Date.now() - started > 30000) { toast(esc(T.tp_offline), 'bad'); loadHistory(); return; }
      fetch('/market/api/tp/' + r.id, {credentials: 'same-origin'}).then(function(x){ return x.json(); }).then(function(s){
        if (s.final) { toast(esc(s.message), s.status === 'done' ? 'ok' : 'bad'); loadHistory(); return; }
        var left = Math.max(0, 15 - Math.floor((Date.now() - started) / 1000));
        toast('<span class="mk-spin"></span>' + esc(fmt('tp_waiting', {n: left})), '', true);
        setTimeout(tick, 1000);
      }).catch(function(){ setTimeout(tick, 1000); });
    };
    setTimeout(tick, 1000);
  }).catch(function(e){ toast(esc(e && e.kind === 'login' ? T.login : T.load_error), 'bad'); });
}
function loadHistory(){
  fetch('/market/api/tp_history', {credentials: 'same-origin'}).then(function(r){ return r.json(); }).then(function(h){
    $('mk-hist').innerHTML = h.rows && h.rows.length ? h.rows.map(function(r){
      return '<div>' + esc(r.when) + ' · <b>' + esc(r.who) + '</b> → ' + esc(r.shop) + '<br><span class="mk-muted">' + esc(r.result) + '</span></div>';
    }).join('') : esc(T.tp_history_none);
  }).catch(function(){});
}

// ---- events -------------------------------------------------------------------
function clearAll(){ var keepMe = state.me; state = {}; FIELDS.forEach(function(k){ state[k] = DEFAULTS[k]; }); state.me = keepMe;
  bonusRows = 1; toForm(); load(true); }
document.addEventListener('input', function(ev){
  var id = ev.target && ev.target.id || ''; if (id.indexOf('mk-') !== 0 || id === 'mk-cost') return;
  validate(); schedule();
});
document.addEventListener('change', function(ev){
  var id = ev.target && ev.target.id || '';
  if (id === 'mk-me') { state.me = ev.target.value; try { localStorage.setItem('mk_me', state.me); } catch(e){}
    if (last) { draw(last); } writeUrl(false); if (state.mine === '1') { apply(false); } return; }
  if (id === 'mk-sort') { fromForm(); state.page = '1'; load(true); return; }
  if (id.indexOf('mk-') === 0 && id !== 'mk-per' && id !== 'mk-cost' && ev.target.type !== 'text' && ev.target.type !== 'search') schedule();
  if (ev.target.dataset && ev.target.dataset.cmp) {
    var oid = ev.target.dataset.cmp;
    if (ev.target.checked) {
      if (Object.keys(picked).length >= 4) { ev.target.checked = false; toast(esc(T.compare_max), 'bad'); return; }
      for (var i = 0; i < last.rows.length; i++) if (String(last.rows[i].id) === oid) picked[oid] = last.rows[i];
    } else delete picked[oid];
    drawCmpBar();
  }
});
document.addEventListener('click', function(ev){
  var t = ev.target.closest ? ev.target.closest('[data-cat],[data-page],[data-bon],[data-tp],[data-shop],[data-item],[data-chip]') : null;
  if (!t) return;
  if (t.dataset.cat !== undefined && t.classList.contains('mk-cat')) { fromForm(); state.cat = t.dataset.cat; state.sub = t.dataset.sub;
    state.page = '1'; load(true); return; }
  if (t.dataset.page !== undefined) { if (t.disabled) return; state.page = t.dataset.page; load(true); window.scrollTo(0, 0); return; }
  if (t.dataset.bon !== undefined) { var b = $('mk-bon-' + t.dataset.bon); if (b) b.classList.toggle('open'); return; }
  if (t.dataset.tp !== undefined) { teleport(last.rows[+t.dataset.tp]); return; }
  if (t.dataset.shop !== undefined) { fromForm(); state.shop = t.dataset.shop; state.page = '1'; load(true); return; }
  if (t.dataset.item !== undefined) { var o = last.rows[+t.dataset.item]; fromForm(); state.vnum = String(o.vnum);
    state['var'] = String(o['var'] || ''); state.sort = 'price_asc'; $('mk-sort').value = 'price_asc'; state.page = '1'; load(true); return; }
  if (t.dataset.chip !== undefined) { state[t.dataset.chip] = ''; if (t.dataset.chip === 'vnum') state['var'] = ''; state.page = '1'; load(true); }
});
document.addEventListener('mouseover', function(ev){
  var t = ev.target.closest ? ev.target.closest('[data-tip]') : null;
  if (!t || !last) return; tip.innerHTML = tipHtml(last.rows[+t.dataset.tip]); tip.style.display = 'block'; moveTip(ev);
});
document.addEventListener('mousemove', function(ev){ if (tip.style.display === 'block') moveTip(ev); });
document.addEventListener('mouseout', function(ev){ var t = ev.target.closest ? ev.target.closest('[data-tip]') : null; if (t) tip.style.display = 'none'; });
$('mk-apply').onclick = function(){ apply(true); };
$('mk-clear').onclick = clearAll;
$('mk-refresh').onclick = function(){ load(false, {refresh: '1'}); };
$('mk-bonus-add').onclick = function(){ fromForm(); bonusRows = Math.min(3, bonusRows + 1); drawBonusRows(); };
$('mk-sidetoggle').onclick = function(){ $('mk-side').classList.toggle('open'); };
$('mk-cmp-open').onclick = openCompare;
$('mk-cmp-close').onclick = function(){ $('mk-modal').classList.remove('on'); };
$('mk-modal').onclick = function(ev){ if (ev.target === this) this.classList.remove('on'); };
$('mk-cmp-clear').onclick = function(){ picked = {}; document.querySelectorAll('[data-cmp]').forEach(function(c){ c.checked = false; }); drawCmpBar(); };
$('mk-cost-save').onclick = function(){
  post('/market/settings', {tp_cost: $('mk-cost').value}).then(function(r){ toast(esc(r.message), r.ok ? 'ok' : 'bad'); })
    .catch(function(){ toast(esc(T.login), 'bad'); });
};
document.addEventListener('keydown', function(ev){ if (ev.key === 'Escape') $('mk-modal').classList.remove('on'); });
window.addEventListener('popstate', function(){ readUrl(); toForm(); load(false); });
readUrl(); toForm(); load(false); loadHistory(); drawCmpBar();
})();
"""


def body():
    return CSS + BODY.replace("__SCRIPT__", SCRIPT)
