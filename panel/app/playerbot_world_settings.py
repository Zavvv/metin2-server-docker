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


# The bots' nickname pool by the world's language (Tieru, 21 October: "nicki
# pod dane jezyki maja byc inne"). playerbot_names.sql writes which pool the
# world deals (common.playerbot_name_world) and which pools the release carries
# (common.playerbot_name_pools); the panel only asks for another one, and the
# migrator moves the world at its next start. A text is pl/en/de/tr, as every
# text of this panel.
NAME_LANGUAGE_NAMES = {'pl': 'Polski', 'tr': 'Türkçe', 'en': 'English', 'de': 'Deutsch', 'fr': 'Français',
                       'pt': 'Português', 'ro': 'Română', 'es': 'Español', 'it': 'Italiano'}
NAME_TEXTS = {
    'title': ('Nicki botów według języka', 'Bot nicknames by language', 'Bot-Namen nach Sprache',
              'Dile göre bot takma adları'),
    'deals': ('Ten świat rozdaje botom nicki z puli:', 'This world names its bots from the pool:',
              'Diese Welt benennt ihre Bots aus dem Pool:', 'Bu dünya botlarına şu havuzdan ad veriyor:'),
    'asked': ('Język gry przy tworzeniu świata:', 'Game language when the world was made:',
              'Spielsprache bei der Erstellung der Welt:', 'Dünya oluşturulurken oyun dili:'),
    'count': ('Boty według puli nicków:', 'Bots by nickname pool:', 'Bots nach Namenspool:',
              'Ad havuzuna göre botlar:'),
    'keep': ('Zmiana języka klienta nie zmienia nicków. Poniższa zamiana nadaje nowe nicki z wybranej puli '
             'przy następnym starcie serwera wszystkim botom, które noszą nick z innej puli. Nicki nadane ręcznie '
             'i nicki Towarzyszy zostają; postacie, przedmioty i poziomy się nie zmieniają.',
             'Changing the client\'s language changes no nickname. The switch below gives every bot that wears a '
             'nickname of another pool a new one from the chosen pool at the next server start. Names given by '
             'hand and companions\' names stay; characters, items and levels do not change.',
             'Eine andere Clientsprache ändert keinen Namen. Der Wechsel unten gibt beim nächsten Serverstart jedem '
             'Bot mit einem Namen aus einem anderen Pool einen neuen aus dem gewählten Pool. Von Hand vergebene '
             'Namen und die Namen der Begleiter bleiben; Charaktere, Gegenstände und Stufen ändern sich nicht.',
             'İstemci dilini değiştirmek hiçbir adı değiştirmez. Aşağıdaki değişiklik, sunucunun bir sonraki '
             'başlangıcında başka bir havuzdan ad taşıyan her bota seçilen havuzdan yeni bir ad verir. Elle verilen '
             'adlar ve yoldaşların adları kalır; karakterler, eşyalar ve seviyeler değişmez.'),
    'button': ('Zmień nicki botów przy następnym starcie', 'Rename the bots at the next start',
               'Bots beim nächsten Start umbenennen', 'Botları bir sonraki başlangıçta yeniden adlandır'),
    'confirm': ('Przy następnym starcie serwera boty dostaną nicki z wybranej puli. Kontynuować?',
                'At the next server start the bots get nicknames from the chosen pool. Continue?',
                'Beim nächsten Serverstart bekommen die Bots Namen aus dem gewählten Pool. Fortfahren?',
                'Sunucunun bir sonraki başlangıcında botlar seçilen havuzdan ad alacak. Devam edilsin mi?'),
    'pending': ('Zaplanowano zmianę na pulę:', 'Scheduled switch to the pool:', 'Geplanter Wechsel zum Pool:',
                'Planlanan havuz değişikliği:'),
    'restart': ('zadziała przy następnym starcie serwera.', 'it takes effect at the next server start.',
                'wirkt beim nächsten Serverstart.', 'sunucunun bir sonraki başlangıcında geçerli olur.'),
    'cancel': ('Anuluj zmianę', 'Cancel the switch', 'Wechsel abbrechen', 'Değişikliği iptal et'),
    'unknown': ('Ten świat nie ma jeszcze zapisanego języka nicków - zapisze go następny start serwera.',
                'This world has no nickname language recorded yet - the next server start records it.',
                'Diese Welt hat noch keine Namenssprache gespeichert - der nächste Serverstart speichert sie.',
                'Bu dünyanın henüz kayıtlı bir ad dili yok - sunucunun bir sonraki başlangıcı kaydedecek.'),
    'saved': ('Zapisano.', 'Saved.', 'Gespeichert.', 'Kaydedildi.'),
    'failed': ('Błąd zapisu.', 'Save failed.', 'Speichern fehlgeschlagen.', 'Kaydedilemedi.'),
    'same': ('Świat już rozdaje tę pulę.', 'The world already deals this pool.',
             'Die Welt verwendet diesen Pool bereits.', 'Dünya zaten bu havuzu kullanıyor.'),
}


def name_text(mod, key):
    pl, en, de, tr = NAME_TEXTS[key]
    return {'pl': pl, 'de': de, 'tr': tr}.get(mod.lang(), en)


def name_language_label(code):
    return '%s (%s)' % (NAME_LANGUAGE_NAMES.get(code, code), code)


def name_language_state(mod):
    """What the world deals, what was asked for, the pools on offer and the
    bots by pool; None while the migrator has not written the tables yet."""
    with mod.db() as con, con.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema='common' "
                    "AND table_name IN ('playerbot_name_world','playerbot_name_pools')")
        if int(cur.fetchone()['n']) < 2:
            return None
        cur.execute('SELECT language, asked, requested FROM common.playerbot_name_world WHERE singleton=1')
        world = cur.fetchone()
        cur.execute('SELECT language, names FROM common.playerbot_name_pools ORDER BY language')
        pools = [r['language'] for r in cur.fetchall()]
        cur.execute("SELECT IF(name_language='', 'pl', name_language) AS language, COUNT(*) AS n "
                    "FROM common.playerbot_name_history WHERE pool_version<>'sidekick' GROUP BY 1 ORDER BY 1")
        counts = [(r['language'], int(r['n'])) for r in cur.fetchall()]
    if not world:
        return None
    return {'language': world['language'], 'asked': world['asked'], 'requested': world['requested'],
            'pools': pools, 'counts': counts}


NAME_CARD = '''<section class="card" id="pb-name-language"><h2>{{t('title')}}</h2>
{% if not state %}<p>{{t('unknown')}}</p>{% else %}
<p>{{t('deals')}} <b>{{label(state.language)}}</b>{% if state.asked %} &middot; {{t('asked')}} {{label(state.asked)}}{% endif %}</p>
{% if state.counts %}<p>{{t('count')}} {% for code, n in state.counts %}{{label(code)}}: {{n}}{% if not loop.last %}, {% endif %}{% endfor %}</p>{% endif %}
<p>{{t('keep')}}</p>
{% if state.requested %}<p><b>{{t('pending')}} {{label(state.requested)}}</b> - {{t('restart')}}
<button data-names-action="cancel">{{t('cancel')}}</button></p>{% endif %}
<label><select id="pb-name-language-pick">{% for code in state.pools %}<option value="{{code}}" {{'selected' if code == (state.requested or state.language) else ''}}>{{label(code)}}</option>{% endfor %}</select></label>
<button data-names-action="request">{{t('button')}}</button>{% endif %}
<p id="pb-name-language-result" role="status"></p></section>'''

NAME_SCRIPT = r'''<script>(function(){var root=document.getElementById('pb-name-language');if(!root)return;
root.addEventListener('click',function(e){var a=e.target.dataset.namesAction;if(!a)return;
if(a==='request'&&!window.confirm(__CONFIRM__))return;var f=new FormData();f.append('_csrf',__CSRF__);f.append('action',a);
var pick=document.getElementById('pb-name-language-pick');f.append('language',pick?pick.value:'');
fetch('/world-settings/bot-names',{method:'POST',body:f,credentials:'same-origin'}).then(function(r){return r.json();}).then(function(j){
document.getElementById('pb-name-language-result').textContent=j.ok?(j.message||__SAVED__):(j.message||j.error);if(j.ok&&!j.message)location.reload();
}).catch(function(){document.getElementById('pb-name-language-result').textContent=__FAILED__;});});})();</script>'''


def name_language_card(mod):
    state = name_language_state(mod)
    html = render_template_string(NAME_CARD, t=lambda key: name_text(mod, key), label=name_language_label,
                                  state=state)
    return html + (NAME_SCRIPT.replace('__CSRF__', json.dumps(mod.csrf_token()))
                   .replace('__CONFIRM__', json.dumps(name_text(mod, 'confirm')))
                   .replace('__SAVED__', json.dumps(name_text(mod, 'saved')))
                   .replace('__FAILED__', json.dumps(name_text(mod, 'failed'))))


def request_name_language(mod, action, language):
    """Ask for another pool, or take the request back. The migrator carries it
    out at the next start (playerbot_names.sql), only with names on."""
    with mod.db() as con, con.cursor() as cur:
        if action == 'cancel':
            cur.execute("UPDATE common.playerbot_name_world SET requested='' WHERE singleton=1")
            con.commit()
            return None
        if action != 'request' or not isinstance(language, str) or len(language) != 2 or \
                not language.isascii() or not language.isalpha():
            raise ValueError('invalid_language')
        language = language.lower()
        cur.execute('SELECT 1 FROM common.playerbot_name_pools WHERE language=%s', (language,))
        if not cur.fetchone():
            raise ValueError('no_pool')
        cur.execute('SELECT language FROM common.playerbot_name_world WHERE singleton=1')
        world = cur.fetchone()
        if not world:
            raise ValueError('no_world_language')
        requested = '' if world['language'] == language else language
        cur.execute('UPDATE common.playerbot_name_world SET requested=%s WHERE singleton=1', (requested,))
        con.commit()
        return None if requested else 'same'


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


# "Why are there this many bots in the game?" (issue #150, 22 October): a
# world of 2941 bots showed 96 in the game and 2845 resting, and nobody - the
# players, the advanced panel, an AI asked about it - could say why. One
# explanation, the same numbers the planner reads, under "Bots in the game"
# and on the AI page. The curve is the core's own (playerbot_rotation_rules.h:
# DayPercent, Target), so the preview says what the planner will aim at.
def day_percent(hour, values):
    hour = max(0.0, hour) % 24.0
    peak, valley = values['ROTATION_PEAK'], values['ROTATION_VALLEY']
    if hour < 4:
        return peak + (valley - peak) * hour / 4
    if hour <= 8:
        return valley
    if hour < 19:
        return valley + (peak - valley) * (hour - 8) / 11
    return peak


def rotation_target(values, when, capacity):
    """The planner's online target at a moment (local time, as the cores)."""
    clock = time.localtime(when)
    weekend = clock.tm_wday >= 5
    percent = day_percent(clock.tm_hour + clock.tm_min / 60.0, values)
    if weekend:
        percent *= (100 + values['ROTATION_WEEKEND']) / 100.0
    return min(capacity, int(max(0.0, values['ROTATION_TARGET'] * percent / 100.0))), percent, weekend


EXPLAIN_TEXTS = {
    'rotation': ('Rotacja botów jest włączona. Cel teraz: {now} botów w grze ({target} × {pct}% o tej porze dnia{weekend}), za godzinę: {next}. Tolerancja: ±{tol}.',
                 'Bot rotation is on. Target now: {now} bots in the game ({target} × {pct}% at this time of day{weekend}), in an hour: {next}. Tolerance: ±{tol}.',
                 'Die Bot-Rotation ist an. Ziel jetzt: {now} Bots im Spiel ({target} × {pct}% zu dieser Tageszeit{weekend}), in einer Stunde: {next}. Toleranz: ±{tol}.',
                 'Bot rotasyonu açık. Şu anki hedef: oyunda {now} bot ({target} × günün bu saatinde %{pct}{weekend}), bir saat sonra: {next}. Tolerans: ±{tol}.'),
    'weekend': (', weekend +{w}%', ', weekend +{w}%', ', Wochenende +{w}%', ', hafta sonu +%{w}'),
    'state': ('W grze: {online}. Logują się: {returning}. Odpoczywa: {resting}{soon}. Gotowe i czekające na wolne miejsce: {waiting}.',
              'In the game: {online}. Logging in: {returning}. Resting: {resting}{soon}. Ready and waiting for a free place: {waiting}.',
              'Im Spiel: {online}. Melden sich an: {returning}. Ruhen: {resting}{soon}. Bereit und warten auf einen Platz: {waiting}.',
              'Oyunda: {online}. Giriş yapıyor: {returning}. Dinleniyor: {resting}{soon}. Hazır ve boş yer bekliyor: {waiting}.'),
    'soon': (' (najbliższy wraca o {at}, w ciągu godziny wróci {hour})', ' (the first returns at {at}, {hour} within the hour)',
             ' (der erste kommt um {at} zurück, {hour} innerhalb einer Stunde)', ' (ilki {at} saatinde dönüyor, bir saat içinde {hour})'),
    'short': ('Do celu brakuje {gap}. Rotacja wpuszcza najwyżej {per_min} botów na minutę (2% celu), a gdy zabraknie gotowych, budzi te, którym odpoczynek kończy się najwcześniej. W tym tempie cel zostanie osiągnięty za ok. {mins} min.',
              '{gap} short of the target. The rotation lets in at most {per_min} bots a minute (2% of the target), and when no bot is ready it wakes the ones whose rest ends first. At this pace the target is reached in about {mins} min.',
              'Bis zum Ziel fehlen {gap}. Die Rotation lässt höchstens {per_min} Bots pro Minute herein (2% des Ziels) und weckt, wenn keiner bereit ist, die, deren Ruhe zuerst endet. In diesem Tempo ist das Ziel in etwa {mins} Min. erreicht.',
              'Hedefe {gap} eksik. Rotasyon dakikada en fazla {per_min} bot alır (hedefin %2si); hazır bot kalmazsa dinlenmesi en erken bitenleri uyandırır. Bu hızla hedefe yaklaşık {mins} dk içinde ulaşılır.'),
    # The launcher's "Dodatkowe boty pozniej" (PLAYERBOT_LATE_JOINERS), which
    # lives in the game container's environment only: each core says what it
    # scheduled in playerbot_late_join.tsv (issue #202).
    'late': ('Dodatkowe boty później (ustawienie launchera, nie rotacji): po starcie serwera dołączyło {joined} z {total}, czeka {waiting}. Dochodzą po jednym: następny za ok. {next} min, ostatni za ok. {last} h.{rot}',
             'Extra bots later (a launcher setting, not the rotation\'s): since the server started {joined} of {total} have joined, {waiting} are waiting. They come one at a time: the next in about {next} min, the last in about {last} h.{rot}',
             'Zusätzliche Bots später (eine Launcher-Einstellung, nicht die der Rotation): seit dem Serverstart sind {joined} von {total} dazugekommen, {waiting} warten. Sie kommen einzeln: der nächste in etwa {next} Min., der letzte in etwa {last} h.{rot}',
             'Sonradan gelen ek botlar (rotasyonun değil, başlatıcının ayarı): sunucu başladığından beri {total} bottan {joined} katıldı, {waiting} bekliyor. Birer birer gelirler: sonraki yaklaşık {next} dk, sonuncusu yaklaşık {last} sa içinde.{rot}'),
    'late_done': ('Dodatkowe boty później (ustawienie launchera, nie rotacji): wszystkie {total} dołączyły po starcie serwera. Przy następnym starcie znów będą dochodzić po jednym.{rot}',
                  'Extra bots later (a launcher setting, not the rotation\'s): all {total} have joined since the server started. After the next start they come in one at a time again.{rot}',
                  'Zusätzliche Bots später (eine Launcher-Einstellung, nicht die der Rotation): alle {total} sind seit dem Serverstart dazugekommen. Nach dem nächsten Start kommen sie wieder einzeln.{rot}',
                  'Sonradan gelen ek botlar (rotasyonun değil, başlatıcının ayarı): {total} botun hepsi sunucu başladığından beri katıldı. Bir sonraki başlatmada yine birer birer gelirler.{rot}'),
    'late_rot': (' Przy włączonej rotacji dołączają do jej puli i grają wtedy, gdy rotacja je wpuści.',
                 ' With the rotation on they join its pool and play when the rotation lets them in.',
                 ' Bei eingeschalteter Rotation kommen sie in ihren Pool und spielen, wenn die Rotation sie hereinlässt.',
                 ' Rotasyon açıkken havuzuna katılırlar ve rotasyon izin verdiğinde oynarlar.'),
    'late_free': (' Wchodzą do gry same, także przy wyłączonej rotacji; liczbę ustawisz w launcherze („Dodatkowe boty później”, 0 = brak).',
                  ' They come into the game by themselves, with the rotation off too; set the number in the launcher ("Extra bots later", 0 = none).',
                  ' Sie kommen von selbst ins Spiel, auch bei ausgeschalteter Rotation; die Anzahl stellst du im Launcher ein („Extra bots later“, 0 = keine).',
                  ' Rotasyon kapalıyken de oyuna kendiliğinden girerler; sayıyı başlatıcıda ayarlarsın ("Extra bots later", 0 = yok).'),
    'why_rest': ('Bot odpoczywa po swojej zmianie ({smin}–{smax} h gry). Jak długo, zależy od jego chęci do gry: zwykle kilka godzin, przy bardzo niskiej 1–3 dni. Wszystkie boty i tak liczą się do puli.',
                 'A bot rests after its session ({smin}–{smax} h of play). How long depends on its wish to play: usually a few hours, 1–3 days when it is very low. Every bot still counts in the pool.',
                 'Ein Bot ruht nach seiner Sitzung ({smin}–{smax} h Spiel). Wie lange, hängt von seiner Spiellust ab: meist ein paar Stunden, bei sehr geringer 1–3 Tage. Alle Bots zählen weiter zum Pool.',
                 'Bot oturumundan ({smin}–{smax} sa oyun) sonra dinlenir. Ne kadar süreceği oynama isteğine bağlıdır: genelde birkaç saat, çok düşükse 1–3 gün. Tüm botlar havuzda sayılmaya devam eder.'),
    'stale': ('Uwaga: żaden rdzeń nie planował rotacji od ponad 3 minut. Sprawdź, czy serwer działa.',
              'Note: no core has planned the rotation for over 3 minutes. Check that the server is running.',
              'Hinweis: Kein Kern hat die Rotation seit über 3 Minuten geplant. Prüfe, ob der Server läuft.',
              'Not: 3 dakikadan uzun süredir hiçbir çekirdek rotasyonu planlamadı. Sunucunun çalıştığını kontrol et.'),
    'paused': ('Rotacja jest wstrzymana: nikt nie wchodzi ani nie wychodzi, dopóki jej nie wznowisz.',
               'The rotation is paused: nobody comes in or leaves until you resume it.',
               'Die Rotation ist pausiert: Niemand kommt oder geht, bis du sie fortsetzt.',
               'Rotasyon duraklatıldı: devam ettirene kadar kimse girmez veya çıkmaz.'),
    'off': ('Rotacja botów jest wyłączona.', 'Bot rotation is off.', 'Die Bot-Rotation ist aus.', 'Bot rotasyonu kapalı.'),
    'realism': ('Realizm sesji {p}%: tyle botów gra w rytmie prawdziwych graczy (pory dnia, przerwy, dni bez gry), więc część z nich jest poza grą.',
                'Session realism {p}%: that share of the bots plays to real players\' hours (time of day, breaks, days off), so some of them are out of the game.',
                'Sitzungsrealismus {p}%: dieser Anteil der Bots spielt wie echte Spieler (Tageszeit, Pausen, freie Tage), also ist ein Teil nicht im Spiel.',
                'Oturum gerçekçiliği %{p}: botların bu kadarı gerçek oyuncuların saatlerine göre oynar (gün saati, molalar, oyunsuz günler), bu yüzden bir kısmı oyunda değildir.'),
    'life': ('„Boty grają jak żywi ludzie”: każdy gra {h} h dziennie, potem odpoczywa.',
             '"Bots play like real people": each plays {h} h a day, then rests.',
             '„Bots spielen wie echte Menschen“: jeder spielt {h} h am Tag und ruht dann.',
             '"Botlar gerçek insanlar gibi oynar": her biri günde {h} sa oynar, sonra dinlenir.'),
    'life_default': ('„Boty grają jak żywi ludzie”: zmiany po 3–6 h i odpoczynek 3–9 h, najwyżej 2 boty na 5 odpoczywają naraz.',
                     '"Bots play like real people": sessions of 3–6 h and rests of 3–9 h, at most 2 bots in 5 rest at once.',
                     '„Bots spielen wie echte Menschen“: Sitzungen von 3–6 h und Ruhe von 3–9 h, höchstens 2 von 5 Bots ruhen gleichzeitig.',
                     '"Botlar gerçek insanlar gibi oynar": 3–6 sa oturum, 3–9 sa dinlenme, aynı anda en fazla 5 bottan 2si dinlenir.'),
    'plain': ('Żaden harmonogram nie wylogowuje botów: w grze jest tyle, ile ustawiono w launcherze (boty na kanał i królestwo), o ile kanały działają.',
              'No schedule logs the bots out: the game holds as many as the launcher sets (bots per channel and kingdom), while the channels run.',
              'Kein Zeitplan meldet die Bots ab: Im Spiel sind so viele, wie der Launcher einstellt (Bots pro Kanal und Reich), solange die Kanäle laufen.',
              'Hiçbir zamanlama botları çıkarmaz: kanallar çalıştığı sürece oyunda başlatıcıda ayarlanan kadar bot olur (kanal ve krallık başına).'),
    'off_state': ('W grze: {online}. Odpoczywa: {resting}.', 'In the game: {online}. Resting: {resting}.',
                  'Im Spiel: {online}. Ruhen: {resting}.', 'Oyunda: {online}. Dinleniyor: {resting}.'),
    'preview': ('Podgląd: cel teraz {now} botów, za godzinę {next} (pula: {cap} botów).',
                'Preview: target now {now} bots, in an hour {next} (pool: {cap} bots).',
                'Vorschau: Ziel jetzt {now} Bots, in einer Stunde {next} (Pool: {cap} Bots).',
                'Önizleme: şu anki hedef {now} bot, bir saat sonra {next} (havuz: {cap} bot).'),
    'help': ('Jak to działa: „Ile botów w grze” to cel na szczyt dnia. W nocy (4:00–8:00) cel spada do „Dolina”, wieczorem (od 19:00) wraca do „Szczyt”, a w weekend rośnie o „Weekend dodatkowo”. Każdy bot gra jedną zmianę (od „Długość zmiany min” do „max”), potem odpoczywa, a na jego miejsce wchodzi inny. „Tolerancja” to margines, w którym nikt nie jest wylogowywany na siłę. „Ile może rotować na godzinę” ogranicza, ilu botów wymienia się w ciągu godziny. „Pula” to udział poziomów wśród botów w grze (−1 = jak w całej populacji), a „Limit poziomów 1–9” nie wpuszcza za dużo nowych postaci. Cel nigdy nie przekroczy liczby botów ustawionej w launcherze.',
             'How it works: "Online target" is the target at the day\'s peak. At night (4:00–8:00) it falls to "Trough", in the evening (from 19:00) it is back at "Peak", and at the weekend it grows by "Weekend extra". Each bot plays one session (from "Minimum session" to "Maximum session"), then rests while another takes its place. "Tolerance" is the margin within which nobody is logged out by force. "Hourly turnover" limits how many bots are exchanged in an hour. "Pool" is the share of each level band among the bots in the game (−1 = as in the whole population), and "Levels 1–9 cap" keeps out too many new characters. The target never exceeds the number of bots set in the launcher.',
             'So funktioniert es: „Online target“ ist das Ziel zur Tagesspitze. Nachts (4:00–8:00) sinkt es auf „Trough“, abends (ab 19:00) ist es wieder auf „Peak“, am Wochenende steigt es um „Weekend extra“. Jeder Bot spielt eine Sitzung (von „Minimum session“ bis „Maximum session“) und ruht dann, während ein anderer seinen Platz einnimmt. „Tolerance“ ist der Spielraum, in dem niemand zwangsweise abgemeldet wird. „Hourly turnover“ begrenzt, wie viele Bots pro Stunde getauscht werden. „Pool“ ist der Anteil jeder Stufengruppe unter den Bots im Spiel (−1 = wie in der ganzen Population), und „Levels 1–9 cap“ hält zu viele neue Charaktere fern. Das Ziel übersteigt nie die im Launcher eingestellte Anzahl Bots.',
             'Nasıl çalışır: "Online target" günün zirvesindeki hedeftir. Gece (4:00–8:00) "Trough"a düşer, akşam (19:00 sonrası) "Peak"e döner, hafta sonu "Weekend extra" kadar artar. Her bot bir oturum oynar ("Minimum session"dan "Maximum session"a), sonra dinlenir ve yerine başkası girer. "Tolerance", kimsenin zorla çıkarılmadığı paydır. "Hourly turnover" bir saatte kaç botun değiştirileceğini sınırlar. "Pool" oyundaki botlar arasında her seviye aralığının payıdır (−1 = tüm nüfustaki gibi), "Levels 1–9 cap" çok fazla yeni karakteri dışarıda tutar. Hedef, başlatıcıda ayarlanan bot sayısını asla aşmaz.'),
}


def explain_text(mod, key, **values):
    pl, en, de, tr = EXPLAIN_TEXTS[key]
    return {'pl': pl, 'de': de, 'tr': tr}.get(mod.lang(), en).format(**values)


def rotation_capacity(cur):
    cur.execute('SELECT COALESCE(SUM(capacity),0) AS cap FROM common.playerbot_rotation_core '
                'WHERE seen_at>NOW()-INTERVAL 150 SECOND')
    row = cur.fetchone() or {}
    return int(row.get('cap') or 0)


def late_join_census(mod):
    """What every core scheduled of the launcher's late joiners (playerbot_late_join.tsv):
    (total, waiting, next seconds, last seconds), or None when no core schedules any."""
    # The files' own clock: the explanation's `now` may be a test's.
    now = time.time()
    total = waiting = last = 0
    nearest = None
    for _channel, _core, folder in mod._ix_core_dirs():
        path = os.path.join(folder, 'playerbot_late_join.tsv')
        try:
            age = max(0, now - os.path.getmtime(path))
            # A core writes it a minute apart; an older file is a core that stopped.
            if age > 150:
                continue
            with open(path, encoding='ascii') as stream:
                if stream.readline().strip() != 'scheduled\twaiting\tnext_s\tlast_s':
                    continue
                fields = stream.readline().strip().split('\t')
        except (OSError, UnicodeDecodeError):
            continue
        if len(fields) != 4 or not all(f.isdecimal() for f in fields):
            continue
        scheduled, left, next_s, last_s = map(int, fields)
        total += scheduled
        left = min(left, scheduled)
        waiting += left
        if left:
            next_s = max(0, next_s - int(age))
            nearest = next_s if nearest is None else min(nearest, next_s)
            last = max(last, last_s - int(age))
    if not total:
        return None
    return total, waiting, nearest or 0, max(0, last)


def late_join_line(mod, rotation):
    census = late_join_census(mod)
    if not census:
        return None
    total, waiting, next_s, last_s = census
    rot = explain_text(mod, 'late_rot' if rotation else 'late_free')
    if not waiting:
        return explain_text(mod, 'late_done', total=total, rot=rot)
    return explain_text(mod, 'late', total=total, joined=total - waiting, waiting=waiting,
                        next=max(1, (next_s + 59) // 60), last='%g' % round(last_s / 3600.0, 1), rot=rot)


def population_explain(mod, live, now=None):
    """Lines that say why the game holds the bots it holds, and their counts."""
    now = int(time.time()) if now is None else now
    online = len(live or {})
    values = read(os.path.join(mod.AI_SPOOL, 'playerbot_world_settings.tsv'))
    lines = []
    counts = {'online': online}
    if values['ROTATION_ENABLED']:
        with mod.db() as con, con.cursor() as cur:
            capacity = rotation_capacity(cur)
            cur.execute('SELECT COALESCE(SUM(r.online=0 AND r.admitted=0 AND r.rest_until>%s),0) AS resting,'
                        'COALESCE(SUM(r.online=0 AND r.admitted=0 AND r.rest_until<=%s),0) AS waiting,'
                        'COALESCE(SUM(r.online=0 AND r.admitted>0),0) AS returning,'
                        'MIN(IF(r.online=0 AND r.admitted=0 AND r.rest_until>%s,r.rest_until,NULL)) AS soonest,'
                        'COALESCE(SUM(r.online=0 AND r.admitted=0 AND r.rest_until>%s AND r.rest_until<=%s),0) AS hour '
                        'FROM common.playerbot_rotation r JOIN common.playerbot_rotation_core c ON c.core=r.core '
                        'WHERE r.selected=1 AND r.retired=0 AND c.seen_at>NOW()-INTERVAL 150 SECOND',
                        (now, now, now, now, now + 3600))
            state = cur.fetchone() or {}
            cur.execute('SELECT planned_min FROM player.web_m2p_rotation_control WHERE singleton=1')
            control = cur.fetchone() or {}
        target_now, percent, weekend = rotation_target(values, now, capacity)
        target_next = rotation_target(values, now + 3600, capacity)[0]
        tolerance = target_now * values['ROTATION_TOLERANCE'] // 100
        counts.update(resting=int(state.get('resting') or 0), waiting=int(state.get('waiting') or 0),
                      returning=int(state.get('returning') or 0), target=target_now, target_next=target_next,
                      capacity=capacity, tolerance=tolerance)
        lines.append(explain_text(mod, 'rotation', now=target_now, target=values['ROTATION_TARGET'], pct=int(round(percent)),
                                  weekend=explain_text(mod, 'weekend', w=values['ROTATION_WEEKEND']) if weekend else '',
                                  next=target_next, tol=tolerance))
        soon = ''
        if state.get('soonest'):
            soon = explain_text(mod, 'soon', at=time.strftime('%H:%M', time.localtime(int(state['soonest']))),
                                hour=int(state.get('hour') or 0))
        lines.append(explain_text(mod, 'state', online=online, returning=counts['returning'], resting=counts['resting'],
                                  soon=soon, waiting=counts['waiting']))
        if values['ROTATION_PAUSED']:
            lines.append(explain_text(mod, 'paused'))
        elif online + counts['returning'] + tolerance < target_now:
            gap = target_now - online - counts['returning']
            per_min = max(1, target_now * 2 // 100)
            lines.append(explain_text(mod, 'short', gap=gap, per_min=per_min, mins=(gap + per_min - 1) // per_min))
        planned = int(control.get('planned_min') or 0)
        if planned and now // 60 - planned > 3:
            lines.append(explain_text(mod, 'stale'))
        lines.append(explain_text(mod, 'why_rest', smin='%g' % (values['ROTATION_SESSION_MIN'] / 60.0),
                                  smax='%g' % (values['ROTATION_SESSION_MAX'] / 60.0)))
        late = late_join_line(mod, True)
        if late:
            lines.append(late)
        return {'lines': lines, 'counts': counts}
    weights = mod.read_ai_weights()
    resting = len(resting_ids(mod, live, now))
    counts['resting'] = resting
    lines.append(explain_text(mod, 'off'))
    scheduled = False
    if weights.get('SESSION_REALISM', 0):
        lines.append(explain_text(mod, 'realism', p=int(weights['SESSION_REALISM'])))
        scheduled = True
    if weights.get('LIFE', 0):
        hours = int(weights.get('LIFE_HOURS', 0) or 0)
        lines.append(explain_text(mod, 'life', h=hours) if hours else explain_text(mod, 'life_default'))
        scheduled = True
    if not scheduled:
        lines.append(explain_text(mod, 'plain'))
    lines.append(explain_text(mod, 'off_state', online=online, resting=resting))
    late = late_join_line(mod, False)
    if late:
        lines.append(late)
    return {'lines': lines, 'counts': counts}


def rotation_preview(mod, values, now=None):
    """The AI page's line under the rotation: the target now and in an hour."""
    now = int(time.time()) if now is None else now
    try:
        with mod.db() as con, con.cursor() as cur:
            capacity = rotation_capacity(cur)
    except Exception:  # noqa: BLE001 - a world without the rotation's tables yet
        capacity = 0
    if not capacity:
        capacity = values['ROTATION_TARGET']
    return explain_text(mod, 'preview', now=rotation_target(values, now, capacity)[0],
                        next=rotation_target(values, now + 3600, capacity)[0], cap=capacity)


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

    @app.route('/world-settings/bot-names', methods=['POST'])
    @mod.login_required
    def pb_name_language():
        try:
            note = request_name_language(mod, request.form.get('action', ''), request.form.get('language', ''))
            return jsonify(ok=True, message=name_text(mod, note) if note else '')
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except Exception:  # noqa: BLE001 - a world without the tables, a lost connection
            app.logger.exception('bot names: request not saved')
            return jsonify(ok=False, error='unavailable'), 503

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
                   'early': ('Obudzony przed końcem odpoczynku, bo brakowało botów do celu', 'Woken before its rest ended to reach the target'),
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
                # What the settings mean, what they aim at now and why the game
                # holds what it holds (issue #150).
                try:
                    explain = [explain_text(mod, 'help'), rotation_preview(mod, values)]
                    try:
                        explain += population_explain(mod, mod.read_playerbot_live_status() or {})['lines']
                    except Exception:  # noqa: BLE001 - the help and the preview stand alone
                        app.logger.exception('world settings: population explanation unavailable')
                    extra = extra.replace('<div style="display:grid', render_template_string(
                        '<div id="p21-explain">{% for line in lines %}<p>{{line}}</p>{% endfor %}</div>',
                        lines=explain) + '<div style="display:grid', 1)
                except Exception:  # noqa: BLE001 - the controls stay without it
                    app.logger.exception('world settings: rotation help unavailable')
                extra += SCRIPT.replace('__CSRF__', csrf).replace('__SAVED__', json.dumps(tr('Zapisano.', 'Saved.'))).replace('__FAILED__', json.dumps(tr('Błąd zapisu.', 'Save failed.')))
                try:
                    extra += name_language_card(mod)
                except Exception:  # noqa: BLE001 - the rotation card stays without it
                    app.logger.exception('bot names: card unavailable')
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
