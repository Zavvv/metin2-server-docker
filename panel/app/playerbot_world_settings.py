"""Persistent world controls shared by every game core (Patch 21)."""
import contextlib
import json
import os
import threading
import time
import tempfile
from flask import request, jsonify, render_template_string

DEFAULTS = {
    'MOONLIGHT_TO_INVENTORY': 0, 'ROTATION_ENABLED': 0, 'ROTATION_PAUSED': 0,
    'ROTATION_TARGET': 1500, 'ROTATION_TOLERANCE': 5, 'ROTATION_PEAK': 100,
    'ROTATION_VALLEY': 60, 'ROTATION_WEEKEND': 10, 'ROTATION_SESSION_MIN': 120,
    'ROTATION_SESSION_MAX': 240, 'ROTATION_HOURLY': 15, 'ROTATION_NEW_CAP': 10,
    'ROTATION_RETIRE': 0, 'ROTATION_EXCHANGE': 0, 'ROTATION_PERF_UNTIL': 0,
    'ROTATION_CAP_REFINE': 2, 'ROTATION_CAP_DROP': 2, 'ROTATION_CAP_LEVEL': 5,
    'ROTATION_CAP_BURN': 2, 'ROTATION_CAP_PK': 3, 'ROTATION_CAP_DEATHS': 3,
}
DEFAULTS.update(('ROTATION_POOL_%d' % n, -1) for n in range(9))
LOCK = threading.RLock()


def validate(values):
    for key, value in values.items():
        if key not in DEFAULTS or type(value) is not int:
            raise ValueError('invalid_setting')
        if key in ('MOONLIGHT_TO_INVENTORY', 'ROTATION_ENABLED', 'ROTATION_PAUSED', 'ROTATION_RETIRE'):
            lo, hi = 0, 1
        elif key == 'ROTATION_TARGET':
            lo, hi = 1, 100000
        elif key in ('ROTATION_SESSION_MIN', 'ROTATION_SESSION_MAX'):
            lo, hi = 30, 1440
        elif key in ('ROTATION_EXCHANGE', 'ROTATION_PERF_UNTIL'):
            lo, hi = 0, 2147483647
        else:
            lo, hi = (-1 if key.startswith('ROTATION_POOL_') else 0), 100
        if not lo <= value <= hi:
            raise ValueError('out_of_range:' + key)
    if values['ROTATION_SESSION_MIN'] > values['ROTATION_SESSION_MAX']:
        raise ValueError('session_min_max')
    shares = [values['ROTATION_POOL_%d' % n] for n in range(9)]
    total = sum(max(0, n) for n in shares)
    if total > 100 or (min(shares) >= 0 and total != 100):
        raise ValueError('pool_shares_must_total_100')


def read(path):
    values = dict(DEFAULTS)
    try:
        with open(path, encoding='ascii') as stream:
            for index, line in enumerate(stream):
                if index >= 256 or len(line) > 512:
                    raise ValueError('settings_too_large')
                line = line.split('#', 1)[0].strip()
                if line:
                    key, value = line.split()
                    values[key] = int(value)
    except FileNotFoundError:
        pass
    validate(values)
    return values


@contextlib.contextmanager
def locked(path):
    with LOCK:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path + '.lock', 'a+b') as handle:
            try:
                import fcntl
            except ImportError:  # Windows unit tests; game/panel run on Linux.
                fcntl = None
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def write(path, values):
    validate(values)
    descriptor, temporary = tempfile.mkstemp(prefix='.world-settings-', suffix='.tmp', dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(descriptor, 'w', encoding='ascii', newline='\n') as stream:
            stream.write('# Persistent world settings; read by every core every 60 seconds.\n')
            for key, value in sorted(values.items()):
                stream.write('%s\t%d\n' % (key, value))
            stream.flush()
            # The game and panel have different UIDs. Settings contain no
            # secrets; native readers need read access after atomic replace.
            os.chmod(temporary, 0o644)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if hasattr(os, 'O_DIRECTORY'):
            directory = os.open(os.path.dirname(os.path.abspath(path)), os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


FIELDS = (
 ('ROTATION_ENABLED', 'Włącz rotację', 'Enable rotation', 0, 1),
 ('ROTATION_TARGET', 'Ile botów w grze', 'Online target', 1, 100000),
 ('ROTATION_TOLERANCE', 'Tolerancja ± (%)', 'Tolerance ± (%)', 0, 100),
 ('ROTATION_PEAK', 'Szczyt (%)', 'Peak (%)', 0, 100),
 ('ROTATION_VALLEY', 'Dolina (%)', 'Trough (%)', 0, 100),
 ('ROTATION_WEEKEND', 'Weekend dodatkowo (%)', 'Weekend extra (%)', 0, 100),
 ('ROTATION_HOURLY', 'Ile może rotować na godzinę (%)', 'Hourly turnover (%)', 0, 100),
 ('ROTATION_NEW_CAP', 'Limit poziomów 1–9 (%)', 'Levels 1–9 cap (%)', 0, 100),
 ('ROTATION_RETIRE', 'Kończenie gry (wyprzedaż i trwałe odejście)', 'Retirement (sale and permanent departure)', 0, 1),
)

CONTROLS = '''<section class="card" id="p21-rotation"><h2>{{tr('Rotacja botów','Bot rotation')}}</h2>
<p>{{tr('Zmiany działają do 60 sekund po zapisie, bez restartu. Domyślnie wyłączone.','Changes apply within 60 seconds, without a restart. Disabled by default.')}}</p>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px">
{% for key,pl,en,lo,hi in fields %}<label>{{tr(pl,en)}}<input data-world="{{key}}" type="{{'checkbox' if hi==1 else 'number'}}" min="{{lo}}" max="{{hi}}" value="{{values[key]}}" {{'checked' if hi==1 and values[key] else ''}}></label>{% endfor %}
{% for key,label in [('ROTATION_SESSION_MIN',tr('Długość zmiany min (h)','Minimum session (h)')),('ROTATION_SESSION_MAX',tr('Długość zmiany max (h)','Maximum session (h)'))] %}
<label>{{label}} <output>{{'%g'|format(values[key]/60)}}</output><input type="range" data-world="{{key}}" data-scale="60" min="0.5" max="24" step="0.5" value="{{values[key]/60}}" oninput="this.previousElementSibling.value=this.value"></label>{% endfor %}
{% for n in range(9) %}<label>{{tr('Pula','Pool')}} {{('1–9' if n==0 else '%d–%d' % (n*10, n*10+9)) if n<8 else '80+'}} (%)
<output>{{values['ROTATION_POOL_' ~ n]}}</output><input type="range" data-world="ROTATION_POOL_{{n}}" min="-1" max="100" value="{{values['ROTATION_POOL_' ~ n]}}" oninput="this.previousElementSibling.value=this.value"></label>{% endfor %}</div>
<p>{{tr('Udział −1 = według populacji. Stałe udziały nie mogą przekroczyć 100%.','Share −1 = population share. Fixed shares cannot exceed 100%.')}}</p>
<button data-world-action="save">{{tr('Zapisz','Save')}}</button>
<button data-world-action="pause">{{tr('Wznów rotację','Resume rotation') if values.ROTATION_PAUSED else tr('Wstrzymaj rotację','Pause rotation')}}</button>
<button data-world-action="exchange">{{tr('Wymień teraz 10%','Exchange 10% now')}}</button>
<a class="btn" href="/rotation">{{tr('Rotacja — wykres i historia','Rotation — chart and history')}}</a><p id="p21-result" role="status"></p></section>'''

SCRIPT = r'''<script>(function(){var root=document.getElementById('p21-rotation');if(!root)return;
root.addEventListener('click',function(e){var a=e.target.dataset.worldAction;if(!a)return;
var vals={};if(a==='save')root.querySelectorAll('[data-world]').forEach(function(i){vals[i.dataset.world]=i.type==='checkbox'?(i.checked?1:0):Math.round(Number(i.value)*Number(i.dataset.scale||1));});
var f=new FormData();f.append('_csrf',__CSRF__);f.append('action',a);f.append('values',JSON.stringify(vals));
fetch('/world-settings',{method:'POST',body:f,credentials:'same-origin'}).then(function(r){return r.json();}).then(function(j){
document.getElementById('p21-result').textContent=j.ok?__SAVED__:j.error;if(j.ok&&a==='pause')location.reload();
}).catch(function(){document.getElementById('p21-result').textContent=__FAILED__;});});})();</script>'''


def resting_ids(mod, live, now=None):
    """Union the native log, persisted realism and selected rotation pool."""
    now = int(time.time()) if now is None else now
    found = set()
    with mod.db() as con, con.cursor() as cur:
        cur.execute('SELECT pid FROM log.playerbot_session WHERE rest_until>NOW() '
                    'AND logout_reason IN (%s,8) GROUP BY pid', (getattr(mod, 'SESSION_LOGOUT_REST', 1),))
        found.update(int(r['pid']) for r in cur.fetchall())
        settings = read(os.path.join(mod.AI_SPOOL, 'playerbot_world_settings.tsv'))
        if settings['ROTATION_ENABLED']:
            cur.execute('SELECT r.pid FROM common.playerbot_rotation r JOIN common.playerbot_rotation_core c ON c.core=r.core '
                        'WHERE r.selected=1 AND r.retired=0 AND c.seen_at>NOW()-INTERVAL 150 SECOND')
            found.update(int(r['pid']) for r in cur.fetchall())
        if mod.read_ai_weights().get('SESSION_REALISM', 0):
            for _channel, _core, folder in mod._ix_core_dirs():
                try:
                    with open(os.path.join(folder, 'playerbot_realism_state.tsv'), encoding='ascii') as stream:
                        if stream.readline().strip() != '#PB11R1':
                            continue
                        for line in stream:
                            fields = line.strip().split('\t')
                            if len(fields) == 7 and all(f.isdecimal() for f in fields):
                                pid, _kind, phase, _flags, _end, until, _next = map(int, fields)
                                if phase in (3, 4, 5) and until > now:
                                    found.add(pid)
                except (OSError, UnicodeError):
                    continue
        cur.execute("SELECT dwPID AS pid FROM player.quest WHERE szName='playerbot' AND szState='retired' AND lValue=1")
        found.difference_update(int(r['pid']) for r in cur.fetchall())
    return found.difference(map(int, live))


def register(mod):
    app = mod.app
    path = os.path.join(mod.AI_SPOOL, 'playerbot_world_settings.tsv')
    tr = lambda pl, en: pl if mod.lang() == 'pl' else en

    @app.route('/world-settings', methods=['POST'])
    @mod.login_required
    def p21_settings():
        try:
            changes = json.loads(request.form.get('values', '{}'))
            if not isinstance(changes, dict) or len(changes) > len(DEFAULTS):
                raise ValueError('invalid_settings')
            if any(k in ('ROTATION_PERF_UNTIL', 'ROTATION_EXCHANGE') for k in changes):
                raise ValueError('reserved_setting')
            with locked(path):
                old = read(path)
                values = dict(old)
                action = request.form.get('action', 'save')
                if action == 'pause':
                    changes = {'ROTATION_PAUSED': 1 - old['ROTATION_PAUSED']}
                elif action == 'exchange':
                    changes = {'ROTATION_EXCHANGE': int(time.time())}
                elif action != 'save':
                    raise ValueError('invalid_action')
                values.update(changes)
                validate(values)
                with mod.db() as con, con.cursor() as cur:
                    cur.execute('CREATE TABLE IF NOT EXISTS player.web_m2p_world_setting_history ('
                                'id BIGINT AUTO_INCREMENT PRIMARY KEY,at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,'
                                'who VARCHAR(80),k VARCHAR(64),old_value INT,new_value INT) ENGINE=InnoDB')
                    for key in changes:
                        if old[key] != values[key]:
                            cur.execute('INSERT INTO player.web_m2p_world_setting_history(who,k,old_value,new_value) VALUES(%s,%s,%s,%s)',
                                        (request.remote_addr or '', key, old[key], values[key]))
                    # File replacement is the commit point for the native reader.
                    write(path, values)
                    con.commit()
            return jsonify(ok=True)
        except (ValueError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.route('/world-settings/pin/<int:pid>', methods=['POST'])
    @mod.login_required
    def p21_pin(pid):
        value = request.form.get('value')
        if value not in ('0', '1'):
            return jsonify(ok=False, error='invalid_pin'), 400
        with mod.db() as con, con.cursor() as cur:
            cur.execute(mod.bot_sql('SELECT <<BOT_P_2>> AS bot FROM player.player p WHERE p.id=%s'), (pid,))
            row = cur.fetchone()
            if not row or not row.get('bot'):
                return jsonify(ok=False, error='not_bot'), 400
            cur.execute('INSERT INTO common.playerbot_rotation(pid,pin) VALUES(%s,%s) ON DUPLICATE KEY UPDATE pin=VALUES(pin)', (pid, int(value)))
            con.commit()
        return jsonify(ok=True)

    @app.route('/rotation')
    @mod.login_required
    def p21_rotation_page():
        return render_template_string(mod.BASE.replace('__BODY__', '''<h2>{{title}}</h2>
<p>{{hint}}</p><canvas id="rotation-chart" height="360" style="width:100%"></canvas>
<div id="rotation-events"></div><script src="/rotation/chart.js"></script>'''),
            title=tr('Rotacja botów', 'Bot rotation'), hint=tr('7 dni: kolory — pule poziomów, linia — cel online.',
            '7 days: colours — level pools, line — online target.'))

    @app.route('/rotation/data')
    @mod.login_required
    def p21_rotation_data():
        end = int(time.time()) // 3600 * 3600 + 3600
        start = end - 168 * 3600
        points = [[start + i * 3600, [0] * 9, 0] for i in range(168)]
        with mod.db() as con, con.cursor() as cur:
            cur.execute('SELECT s.pid,UNIX_TIMESTAMP(s.login_at) AS a,UNIX_TIMESTAMP(COALESCE(s.logout_at,s.seen_at)) AS b,p.level '
                        'FROM log.playerbot_session s JOIN player.player p ON p.id=s.pid '
                        'WHERE s.seen_at>=FROM_UNIXTIME(%s) AND s.login_at<FROM_UNIXTIME(%s)', (start, end))
            sessions = cur.fetchall()
            cur.execute("SELECT pid,UNIX_TIMESTAMP(at) AS a,level FROM log.playerbot_rotation_event WHERE kind='login' AND at>=FROM_UNIXTIME(%s)", (start - 86400,))
            levels = {(int(r['pid']), int(r['a'])): int(r['level']) for r in cur.fetchall()}
            # Exact interval union avoids double counting a channel handoff.
            occupancy = [dict() for _ in points]
            for row in sessions:
                pid, a, b = int(row['pid']), int(row['a']), int(row['b'])
                level = levels.get((pid, a), int(row['level']))
                pool = 0 if level < 10 else min(8, level // 10)
                for i, (at, mix, target) in enumerate(points):
                    if a <= at < b:
                        occupancy[i][pid] = pool
            for point, people in zip(points, occupancy):
                for pool in people.values():
                    point[1][pool] += 1
            cur.execute('SELECT UNIX_TIMESTAMP(at) AS a,SUM(target) AS target FROM log.playerbot_rotation_sample '
                        'WHERE at>=FROM_UNIXTIME(%s) GROUP BY at ORDER BY at', (start,))
            samples = cur.fetchall()
            pos = 0
            target = 0
            for point in points:
                while pos < len(samples) and int(samples[pos]['a']) <= point[0]:
                    target = int(samples[pos]['target']); pos += 1
                point[2] = target
            cur.execute('SELECT e.pid,p.name,e.kind,e.reason,e.at,e.target FROM log.playerbot_rotation_event e '
                        'LEFT JOIN player.player p ON p.id=e.pid ORDER BY e.id DESC LIMIT 50')
            events = [{**r, 'at': str(r['at'])} for r in cur.fetchall()]
        kinds = {'login': ('Wejście', 'Login'), 'logout': ('Wyjście', 'Logout'), 'sale': ('Wyprzedaż', 'Clearance sale'),
                 'retired': ('Zakończył grę', 'Retired'), 'performance': ('Wydajność', 'Performance'), 'postpone': ('Odroczenie', 'Postponed')}
        reasons = {'rotation': ('Rotacja', 'Rotation'), 'session': ('Koniec zmiany', 'Session ended'),
                   'exchange': ('Wymień teraz', 'Manual exchange'), 'target': ('Cel online', 'Online target'),
                   'pin': ('Zawsze w grze', 'Always online'), 'role': ('Rola specjalna', 'Active role'),
                   'sale': ('Trwająca wyprzedaż', 'Sale in progress'), 'start': ('Start serwera', 'Server start'),
                   'priority': ('Miejsce dla bota z pierwszeństwem', 'Room for a priority bot'),
                   'red_30min': ('Obciążenie — niższy cel przez 30 min', 'Load — reduced target for 30 min'),
                   'busy_15min': ('Zajęty przez 15 min — wybrany zostanie inny bot', 'Busy for 15 min — select another bot'),
                   'retirement': ('Kończenie gry', 'Retirement'), 'sold': ('Towar sprzedany', 'Stock sold'), '48h': ('Koniec 48 h wyprzedaży', '48-hour sale ended')}
        for event in events:
            event['kind_text'] = tr(*kinds[event['kind']]) if event['kind'] in kinds else event['kind']
            event['reason_text'] = tr(*reasons[event['reason']]) if event['reason'] in reasons else event['reason']
        return jsonify(ok=True, points=points, events=events,
                       words=[tr('Kiedy', 'When'), tr('Postać', 'Character'), tr('Zdarzenie', 'Event'), tr('Powód', 'Reason'), tr('Cel online', 'Online target')])

    @app.route('/rotation/chart.js')
    @mod.login_required
    def p21_rotation_chart():
        return app.response_class(CHART_JS, mimetype='application/javascript')

    @app.after_request
    def p21_controls(response):
        if request.method == 'GET' and response.status_code == 200 and request.endpoint in ('api_bot_card_actions', 'api_bot_rankings'):
            try:
                data = response.get_json(silent=True) or {}
                with mod.db() as con, con.cursor() as cur:
                    if request.endpoint == 'api_bot_card_actions' and data.get('bot'):
                        cur.execute('SELECT pin,retired FROM common.playerbot_rotation WHERE pid=%s', (request.view_args['pid'],))
                        data['rotation'] = cur.fetchone() or {'pin': 0, 'retired': 0}
                    elif data.get('rankings'):
                        cur.execute("SELECT dwPID AS pid FROM player.quest WHERE szName='playerbot' AND szState='retired' AND lValue=1")
                        retired = {int(r['pid']) for r in cur.fetchall()}
                        for row in data['rankings']:
                            row['retired'] = int(row['id']) in retired
                    response.set_data(json.dumps(data, ensure_ascii=True))
            except Exception:
                app.logger.exception('world settings: status unavailable')
            return response
        if request.method != 'GET' or response.status_code != 200 or 'text/html' not in response.content_type:
            return response
        if request.endpoint not in ('ai_weights', 'events', 'player'):
            return response
        try:
            values = read(path)
            csrf = json.dumps(mod.csrf_token())
            if request.endpoint == 'ai_weights':
                extra = render_template_string(CONTROLS, tr=tr, fields=FIELDS, values=values)
                extra += SCRIPT.replace('__CSRF__', csrf).replace('__SAVED__', json.dumps(tr('Zapisano.', 'Saved.'))).replace('__FAILED__', json.dumps(tr('Błąd zapisu.', 'Save failed.')))
            elif request.endpoint == 'events':
                label = tr('Szkatułki prosto do ekwipunku (boty i gracze)', 'Moonlight Chests directly to inventory (bots and players)')
                help_text = tr('Szkatułka trafia do torby właściciela dropu. Pełna torba — szkatułka spada na ziemię.',
                               'The chest goes to the native drop owner. Full bag — the chest falls to the ground.')
                extra = render_template_string('''<section class="card" id="p21-moonlight"><h3>{{label}}</h3><p>{{help}}</p>
<label><input id="p21-moon" type="checkbox" {{'checked' if enabled else ''}}> {{label}}</label><span id="p21-moon-result"></span></section>''', label=label, help=help_text, enabled=values['MOONLIGHT_TO_INVENTORY'])
                extra += '''<script>document.getElementById('p21-moon').onchange=function(){var f=new FormData();f.append('_csrf',%s);f.append('values',JSON.stringify({MOONLIGHT_TO_INVENTORY:this.checked?1:0}));fetch('/world-settings',{method:'POST',body:f,credentials:'same-origin'}).then(function(r){if(!r.ok)throw Error();document.getElementById('p21-moon-result').textContent=%s;}).catch(function(){location.reload();});};</script>''' % (csrf, json.dumps(tr(' Zapisano.', ' Saved.')))
                extra += "<script>(function(){var box=document.getElementById('moonlight-drop-status'),control=document.getElementById('p21-moonlight');if(box&&control){control.className='';box.appendChild(control);}})();</script>"
            else:
                pid = int(request.view_args['pid'])
                with mod.db() as con, con.cursor() as cur:
                    cur.execute(mod.bot_sql('SELECT <<BOT_P_2>> AS bot FROM player.player p WHERE p.id=%s'), (pid,))
                    bot = cur.fetchone()
                    if not bot or not bot.get('bot'):
                        return response
                    cur.execute('SELECT pin,retired FROM common.playerbot_rotation WHERE pid=%s', (pid,))
                    row = cur.fetchone() or {}
                extra = render_template_string('''<label id="p21-pin-label"><input id="p21-pin" type="checkbox" {{'checked' if pin else ''}}> {{label}}</label>{% if retired %}<p>{{retired_label}}</p>{% endif %}''', pin=row.get('pin'), label=tr('Zawsze w grze', 'Always online'), retired=row.get('retired'), retired_label=tr('Zakończył grę', 'Retired'))
                extra += '''<script>(function(){var p=document.getElementById('p21-pin-label'),h=document.querySelector('.bot-card-heading');if(h)h.appendChild(p);document.getElementById('p21-pin').onchange=function(){var f=new FormData();f.append('_csrf',%s);f.append('value',this.checked?'1':'0');fetch('/world-settings/pin/%d',{method:'POST',body:f,credentials:'same-origin'}).then(function(r){if(!r.ok)location.reload();});};})();</script>''' % (csrf, pid)
            response.set_data(response.get_data(as_text=True).replace('</body>', extra + '</body>', 1))
        except Exception:
            app.logger.exception('world settings: controls unavailable')
        return response

    def performance_red():
        now = int(time.time())
        with locked(path):
            values = read(path)
            if values['ROTATION_ENABLED'] and values['ROTATION_PERF_UNTIL'] <= now:
                values['ROTATION_PERF_UNTIL'] = now + 1800
                write(path, values)
    return performance_red


CHART_JS = r'''(function(){fetch('/rotation/data',{credentials:'same-origin'}).then(function(r){return r.json();}).then(function(j){
var c=document.getElementById('rotation-chart'),ctx=c.getContext('2d'),p=j.points,dpr=window.devicePixelRatio||1,w=c.clientWidth,h=360;c.width=w*dpr;c.height=h*dpr;ctx.scale(dpr,dpr);
var colours=['#b9b1a2','#88ae76','#5aad9b','#598ec0','#7b79b1','#b479b0','#cc8e67','#b6b65a','#db6666'];
var max=1;p.forEach(function(v){max=Math.max(max,v[1].reduce(function(a,b){return a+b;},0),v[2]);});
function x(i){return i*(w-50)/Math.max(1,p.length-1)+40;}function y(n){return h-65-n*(h-90)/max;}
for(var k=8;k>=0;k--){ctx.beginPath();p.forEach(function(v,i){var a=0;for(var n=0;n<=k;n++)a+=v[1][n];i?ctx.lineTo(x(i),y(a)):ctx.moveTo(x(i),y(a));});ctx.lineTo(x(p.length-1),y(0));ctx.lineTo(x(0),y(0));ctx.fillStyle=colours[k];ctx.fill();}
ctx.beginPath();p.forEach(function(v,i){i?ctx.lineTo(x(i),y(v[2])):ctx.moveTo(x(i),y(v[2]));});ctx.strokeStyle='#ffcf38';ctx.lineWidth=3;ctx.stroke();
ctx.fillStyle='#999';ctx.font='12px sans-serif';ctx.fillText(String(max),0,25);ctx.fillText('0',15,h-65);
[0,Math.floor(p.length/2),p.length-1].forEach(function(i){var label=new Date(p[i][0]*1000).toLocaleDateString();ctx.fillText(label,Math.min(x(i),w-85),h-35);});
ctx.fillStyle='#ffcf38';ctx.fillText(j.words[4],Math.max(40,w-130),15);
colours.forEach(function(v,k){ctx.fillStyle=v;ctx.fillText(k===8?'80+':(k?10*k:1)+'–'+(k*10+9),x(0)+k*(w-50)/9,h-8);});
var box=document.getElementById('rotation-events'),table=document.createElement('table'),head=table.createTHead().insertRow();j.words.forEach(function(word){var th=document.createElement('th');th.textContent=word;head.appendChild(th);});j.events.forEach(function(e){var row=table.insertRow();[e.at,e.name||e.pid,e.kind_text,e.reason_text,e.target||'—'].forEach(function(v){row.insertCell().textContent=v;});});box.appendChild(table);
c.onmousemove=function(e){var i=Math.max(0,Math.min(p.length-1,Math.round((e.offsetX-40)*(p.length-1)/(w-50))));c.title=new Date(p[i][0]*1000).toLocaleString()+' · '+p[i][1].reduce(function(a,b){return a+b;},0)+' / '+p[i][2];};
}).catch(function(){document.getElementById('rotation-events').textContent='Statistics unavailable / Statystyki niedostępne';});})();'''
