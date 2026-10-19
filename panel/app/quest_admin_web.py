"""The GM's quest skip on the classic panel ("Misje graczy"; Kiciamol, 16 October).

A character's saved quests, their stages and flags, and a "full skip" that
gives the reward the remaining stages would have given and ends the quest (or
its current cycle). Nothing here writes a quest flag, an item or Yang: a
confirmed skip is a row of player.web_quest_admin_actions, which the
character's own timer on its own core carries out when it is in the game
(gm_quest_admin.lua, gm_quest_full_skip.lua), checking its stage, cycle and
reward again. The plans are quest_catalog.json, generated with the game
image's gm_quest_catalog.lua from the package's quests; resolve() is the
Python twin of the Lua's M.resolve and signs a plan the same way, so the core
refuses a reward that changed between the preview and the click.

Kiciamol's quest_admin_web.py and quest_skip_model.py in one module, with
what ours adds: a bot of the population or a player's companion is shown and
never skipped (Tieru: no bot gets anything for free); the page reads in the
panel's language (Polish, or English for every other); and the switch the
core asks (player.web_quest_admin_config) is a button on the search page.
"""
import copy
import hashlib
import json
import unicodedata
import uuid
from pathlib import Path

from flask import abort, flash, redirect, render_template_string, request, url_for

CATALOG = json.loads(Path(__file__).with_name('quest_catalog.json').read_text('utf-8'))

# The catalog's Polish words, with their English (gm_quest_full_skip.lua's M.WORDS).
WORDS = {
    'Pelny skip': 'Full skip', 'Bron 1': 'Weapon 1', 'Bron 2': 'Weapon 2',
    'Prawda': 'The truth', 'Klamstwo': 'The lie', 'Sukces': 'Success',
    'Niepowodzenie': 'Failure', 'Yang': 'Yang', 'Doswiadczenie': 'Experience',
    'Zemsta zakonczona': 'Revenge done', 'Rezygnacja z zemsty': 'Revenge given up',
    'Pierwsza profesja': 'First skill group', 'Druga profesja': 'Second skill group',
    'Skrypt systemowy lub nieaktywna definicja; nie ma jednorazowej misji do zakonczenia.':
        'A system script or an inactive definition; there is no one-time quest to complete.',
    'Biolog 92 ma w tej dystrybucji pusta definicje (bez zadania i nagrody).':
        'The Biologist of 92 has an empty definition here (no task and no reward).',
}
BIO_REWARDS = {
    30: ('+10 szybkosci ruchu; szkatulka 50109', '+10 movement speed; casket 50109'),
    40: ('+5 szybkosci ataku; szkatulka 50110', '+5 attack speed; casket 50110'),
    50: ('+60 obrony; szkatulka 50111', '+60 defence; casket 50111'),
    60: ('+50 ataku; szkatulka 50112', '+50 attack; casket 50112'),
    70: ('+11 szybkosci ruchu, +10% obrony; szkatulka 50113', '+11 movement speed, +10% defence; casket 50113'),
    80: ('+6 szybkosci ataku, +10% ataku (czas jak w oryginalnej misji); szkatulka 50114',
         '+6 attack speed, +10% attack (for as long as the quest gives it); casket 50114'),
    85: ('+10 odpornosci na ludzi; szkatulka 50115', '+10 resistance against humans; casket 50115'),
    90: ('+8 sily przeciw ludziom; szkatulka 50114', '+8 strength against humans; casket 50114'),
}
STATUS = {
    'pending': ('Oczekuje na gracza (maks. 2 minuty)', 'Waiting for the player (2 minutes at most)'),
    'applying': ('Wykonywanie', 'Being carried out'),
    'done': ('Zakonczono z nagroda', 'Completed with its reward'),
    'rejected': ('Odrzucono przed wykonaniem', 'Refused before anything changed'),
    'expired': ('Wygaslo - gracz nieobecny lub zajety', 'Expired - the player was away or busy'),
    'uncertain': ('Wymaga sprawdzenia - nie ponawiaj nagrody', 'Needs checking - do not give the reward again'),
}


# ---- the plan, as the core resolves it (gm_quest_full_skip.lua) -------------
def sex_for_job(job):
    return [0, 1, 0, 1, 1, 0, 1, 0][int(job) % 8]


def stage_name(key, value):
    return next((k for k, v in CATALOG.get(key, {}).get('states', {}).items() if v == value), str(value))


def options(key, value, job):
    f = CATALOG.get(key, {}).get('full_skip')
    stage = stage_name(key, value)
    if not f or stage not in f['active']:
        return []
    return [(k, p['label']) for k, p in sorted(f['plans'].items(), key=lambda pair: (pair[0] != f['default'], pair[0]))
            if ('jobs' not in p or int(job) % 4 in p['jobs'])
            and ('stages' not in p or stage in p['stages']) and stage not in p.get('exclude_stages', [])]


def resolve(key, value, job, flags, variant='', horse_level=0, all_flags=None):
    choices = options(key, value, job)
    if not choices:
        raise ValueError('unsupported_or_inactive')
    variant = variant or choices[0][0]
    if variant not in dict(choices):
        raise ValueError('invalid_reward_choice')
    f = CATALOG[key]['full_skip']
    stage = stage_name(key, value)
    s = copy.deepcopy(f['plans'][variant])
    items = s['items'][:]
    rewards = s.get('rewards_by_stage', {}).get(stage, s['rewards'])
    items += s.get('items_by_job', {}).get(str(int(job) % 4), [])
    if stage not in s.get('items_sex_paid_states', []):
        items += s.get('items_by_sex', {}).get(str(sex_for_job(job)), [])
    if stage not in s.get('items_before_paid_states', []):
        for row in s.get('items_before_stage', {}).values():
            items += row
    if stage not in s.get('items_early_paid_states', []):
        items += s.get('items_early', [])
    cycle = int(flags.get(f.get('cycle_flag', ''), 0)) if f.get('cycle_flag') else -1
    if f.get('cycle_context') == 'horse':
        cycle = int(horse_level)
    out = {'variant': variant, 'label': s['label'], 'cycle': cycle, 'spec': s, 'stage': stage,
           'terminal': s.get('terminal', f['terminal']), 'rewards': rewards, 'items': items,
           'exp': s['exp'], 'gold': s.get('gold_by_stage', {}).get(stage, s['gold']),
           'alignment': s['alignment'], 'context': []}
    if key == 'hunting':
        data = f['hunting_data']
        index = cycle
        if not 0 <= index < len(data):
            raise ValueError('quest_cycle_finished')
        d = data[index]
        out['gold'] += d['gold']
        out['exp_percent'] = [d['level'], d['percent']]
        for i in range(0, len(d['items']), 2):
            item = d['items'][i]
            if item == 'primary_armor':
                item = [11200, 11400, 11600, 11800][int(job) % 4]
            if item == 'primary_helmet':
                item = [12200, 12340, 12480, 12620][int(job) % 4]
            out['items'].append([item, d['items'][i + 1]])
    if s.get('native') in ('horse', 'horse_training'):
        if s['native'] == 'horse':
            if int(horse_level) != s['horse_target'] - 1:
                raise ValueError('horse_level_changed')
            out['horse_target'] = s['horse_target']
        else:
            if not s['horse_min'] <= int(horse_level) <= s['horse_max']:
                raise ValueError('horse_level_changed')
            out['horse_target'] = int(horse_level) + 1
    if s.get('native') == 'quest_book':
        index = int((all_flags or {}).get('quest_book_manage', {}).get('quest_index', 0))
        if index <= 0:
            raise ValueError('quest_cycle_finished')
        out['context'].append(str(index))
    return out


def signature_parts(key, value, job, flags, resolved):
    return ['full2', CATALOG[key]['full_skip']['revision'], str(value), resolved['variant'],
            str(resolved['cycle']), str(int(job) % 4), str(sex_for_job(job))] + resolved['context']


def signature(parts):
    return hashlib.md5('|'.join(parts).encode('ascii')).hexdigest()


def is_active(key, value):
    c = CATALOG.get(key)
    a = c and c['adapter']
    return bool(a and value in [c['states'][s] for s in a['active']])


def fold(s):
    return ''.join(x for x in unicodedata.normalize('NFKD', s.lower().replace('ł', 'l')) if not unicodedata.combining(x))


def decode_db(s):
    try:
        return s.encode('latin1').decode('cp1250')
    except (UnicodeError, AttributeError):
        return str(s or '')


def items_from_field(s):
    values = [x.strip() for x in (s or '').split(',') if x.strip()]
    if len(values) % 2:
        raise ValueError('reward_definition_invalid')
    return [(values[i], int(values[i + 1])) for i in range(0, len(values), 2)]


def register(app, db, base, login_required, lang=lambda: 'pl', item_name=None, tr_text=None):
    """The three pages and the switch. `lang` is the panel's language (Polish,
    or English for every other); `item_name(vnum, raw)` names an item for the
    reader when the panel can, else the world's Polish name is shown.
    Turkish patch: `lang` may say 'tr', and `tr_text(en)` then gives the
    Turkish of an English text (the English where it has none)."""

    def tr(pl, en):
        language = lang()
        if language == 'pl':
            return pl
        if language == 'tr' and tr_text is not None:
            return tr_text(en)
        return en

    def word(pl):
        en = WORDS.get(pl)
        if en is None and pl.startswith('Przedmiot #'):
            en = 'Item #' + pl[len('Przedmiot #'):]
        return tr(pl, en) if en else pl

    def status_text(code):
        pair = STATUS.get(code)
        return tr(*pair) if pair else code

    def name_item(vnum, raw):
        if item_name is not None:
            try:
                named = item_name(vnum, raw)
                if named:
                    return named
            except Exception:  # noqa: BLE001 - a name is a nicety
                pass
        return decode_db(raw) if raw else tr('Przedmiot', 'Item')

    def is_bot(cur, pid):
        # A registered identity of the seed: a bot of the population or a
        # player's companion.
        try:
            cur.execute('SELECT pid FROM common.playerbot_seed_state WHERE pid=%s LIMIT 1', (pid,))
            return cur.fetchone() is not None
        except Exception:  # noqa: BLE001 - no ledger: nothing is a bot here
            return False

    # Iwakura's Patch 20, 4J: a bot of the population ends a quest too, carried
    # out by its own core (a QUESTDONE row, source 'panel_bot' - the same Lua
    # as a person's); a player's companion stays view only, and so does a GM's
    # character (the server refuses both again).
    def is_companion(cur, pid):
        try:
            cur.execute('SELECT 1 AS n FROM player.playerbot_sidekick WHERE sidekick_pid=%s LIMIT 1', (pid,))
            return cur.fetchone() is not None
        except Exception:  # noqa: BLE001 - no table: no companions
            return False

    def is_gm(cur, name):
        try:
            cur.execute('SELECT 1 AS n FROM common.gmlist WHERE mName=%s LIMIT 1', (name,))
            return cur.fetchone() is not None
        except Exception:  # noqa: BLE001
            return False

    def player_flags(pid):
        with db() as con, con.cursor() as cur:
            cur.execute('SELECT id,name,job,level,horse_level FROM player.player WHERE id=%s', (pid,))
            p = cur.fetchone()
            if not p:
                abort(404)
            p['name'] = decode_db(p['name'])
            cur.execute('SELECT szName,szState,lValue FROM player.quest WHERE dwPID=%s ORDER BY szName,szState', (pid,))
            flags = {}
            for row in cur.fetchall():
                flags.setdefault(row['szName'], {})[row['szState']] = int(row['lValue'])
            bot = is_bot(cur, pid)
            # 'companion' and 'gm' are the two that never end a quest here.
            p['companion'] = bot and is_companion(cur, pid)
            p['gm'] = is_gm(cur, p['name'])
        return p, flags, bot

    def enabled_now(cur):
        cur.execute('SELECT enabled FROM player.web_quest_admin_config WHERE id=1')
        conf = cur.fetchone()
        return bool(conf and conf['enabled'])

    def reward_preview(cur, p, key, flags, variant):
        own = flags[key]
        value = own.get('__status', 0)
        choices = [(k, word(v)) for k, v in options(key, value, p['job'])]
        try:
            rplan = resolve(key, value, p['job'], own, variant, p['horse_level'], flags)
        except ValueError as error:
            reason = CATALOG.get(key, {}).get('readonly_reason') or str(error)
            return [word(reason)], '', None, choices
        parts = signature_parts(key, value, p['job'], own, rplan)
        lines = []
        items = list(rplan['items'])
        exp, gold, alignment = rplan['exp'], rplan['gold'], rplan['alignment']
        field = ['warrior_items', 'assassin_items', 'sura_items', 'shaman_items'][int(p['job']) % 4]
        for name in rplan['rewards']:
            cur.execute('SELECT * FROM world.quest_reward_proto WHERE quest_name=%s', (name,))
            r = cur.fetchone()
            if not r:
                return [tr('Brak definicji nagrody: ', 'No reward definition: ') + name], '', rplan, choices
            exp += r['exp']
            gold += r['gold']
            alignment += r['alignment']
            items += items_from_field(r['items']) + items_from_field(r[field])
            parts.extend([name, hashlib.md5('|'.join(str(x if x is not None else '') for x in
                         [r['exp'], r['gold'], r['alignment'], r['items'], r[field]]).encode('ascii')).hexdigest()])
        lines.append(tr('Pelny skip: {}. EXP: {:,}; Yang: {:,}; ranga: {}', 'Full skip: {}. EXP: {:,}; Yang: {:,}; rank: {}')
                     .format(word(rplan['label']), exp, gold, alignment))
        if rplan.get('exp_percent'):
            lines.append(tr('Dodatkowo {}% EXP poziomu {}.', 'Plus {}% of the EXP of level {}.')
                         .format(rplan['exp_percent'][1], rplan['exp_percent'][0]))
        for vnum, count in items:
            vnum = str(vnum)
            if vnum.startswith('s'):
                lines.append(tr('Losowy przedmiot z grupy {} x{} (jak w misji)', 'A random item of group {} x{} (as in the quest)')
                             .format(vnum[1:], count))
            else:
                cur.execute('SELECT locale_name FROM world.item_proto WHERE vnum=%s', (int(vnum),))
                item = cur.fetchone()
                lines.append('{} (#{}), x{}'.format(name_item(int(vnum), item['locale_name'] if item else None), vnum, count))
        native = rplan['spec'].get('native')
        if native == 'biologist':
            pair = BIO_REWARDS.get(int(key.split('lv')[-1]))
            if pair:
                lines.append(tr(*pair))
        elif native == 'quest_book':
            lines.append(tr('Losowe EXP, Yang i przedmioty wedlug oryginalnych tabel zwoju, z oryginalnymi bonusami do liczby i jakosci przedmiotow.',
                            "Random EXP, Yang and items by the scroll's own tables, with its bonuses to the number and quality of the items."))
        elif native == 'senior':
            lines.append(tr('Losowy bonus na 5 minut, wedlug oryginalnego zadania: HP, regeneracja HP, sila, witalnosc, krytyk, szybkosc ataku albo sila przeciw zwierzetom.',
                            'A random bonus for 5 minutes, as the quest gives it: HP, HP regeneration, strength, vitality, critical hits, attack speed or strength against animals.'))
        elif native == 'warehouse':
            lines.append(tr('Odblokowanie drugiej strony magazynu na koncie.', "Unlocks the storage's second page on the account."))
        elif native == 'dragon_soul':
            lines.append(tr('Odblokowanie alchemii smoczych kamieni i rozpoczecie codziennych zadan.',
                            'Unlocks the Dragon Stone Alchemy and starts its daily tasks.'))
        elif native == 'skill_group':
            lines.append(tr('Wybrana profesja: {}.', 'Skill group: {}.').format(rplan['spec']['group']))
        elif native == 'herbalism':
            # gm_quest_full_skip.lua: the introduction's 5% of a level, and the
            # first knife for a character that has none (kaethasger, 18 October).
            lines.append(tr('Zielarstwo odblokowane u Baek-Go; 5% EXP poziomu; Nozyk Zielarza+0, jesli postac go nie ma.',
                            "Herbalism unlocked at Baek-Go; 5% of a level's EXP; a Herbalist's Knife+0 if the character has none."))
        if rplan.get('horse_target'):
            lines.append(tr('Poziom konia po skipie: {}.', 'Horse level after the skip: {}.').format(rplan['horse_target']))
        if rplan['spec'].get('reputation'):
            lines.append(tr('Reputacja: +{}.', 'Reputation: +{}.').format(rplan['spec']['reputation'][1]))
        lines.append(tr('Koncowy etap: {}. Nagrody z wczesniejszych etapow nie sa powtarzane.',
                        'Final stage: {}. Earlier stages\' rewards are not paid again.').format(rplan['terminal']))
        for name, state in rplan['spec']['follow']:
            lines.append(tr('Dalszy ciag: {} ({}).', 'Continues with: {} ({}).').format(name, state))
        return lines, signature(parts), rplan, choices

    def page(body, **ctx):
        return render_template_string(base.replace('__BODY__', body), tr=tr, **ctx)

    @app.route('/quests')
    @login_required
    def quest_admin_search():
        query = request.args.get('name', '').strip()[:24]
        players = []
        with db() as con, con.cursor() as cur:
            enabled = enabled_now(cur)
            if query:
                cur.execute('SELECT id,name,level FROM player.player WHERE name LIKE %s ORDER BY name LIMIT 50',
                            ('%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%',))
                players = cur.fetchall()
                for row in players:
                    row['name'] = decode_db(row['name'])
        return page('''
<p><a href="{{url_for('dash')}}">{{tr('Wroc do graczy','Back to players')}}</a></p>
<div class="card"><h3>{{tr('Misje graczy','Player quests')}}</h3>
<form method="get"><label>{{tr('Nick gracza','Character name')}} <input name="name" maxlength="24" value="{{query}}"></label> <button>{{tr('Szukaj','Search')}}</button></form>
<p class="muted">{{tr('Wybierz postac, aby zobaczyc zapisane misje, ich etapy, flagi i historie dzialan GM. Bot populacji i towarzysz gracza sa tylko do podgladu.','Pick a character to see its saved quests, their stages, flags and the GM actions. A bot of the population and a player\\'s companion are view only.')}}</p>
{% for p in players %}<p><a class="btn" href="{{url_for('quest_admin_player',pid=p.id)}}">{{p.name}} - {{tr('poziom','level')}} {{p.level}}</a></p>{% else %}{% if query %}<p>{{tr('Nie znaleziono postaci.','No such character.')}}</p>{% endif %}{% endfor %}</div>
<div class="card"><h3>{{tr('Konczenie misji przez GM','Quest completion by a GM')}}</h3>
<p>{{tr('Teraz:','Now:')}} <b>{{tr('wlaczone','on') if enabled else tr('wylaczone','off')}}</b>. {{tr('Wylaczone - zadne nowe zlecenie z F9 ani stad nie zostanie wykonane.','Off - no new request from F9 or from here is carried out.')}}</p>
<form method="post" action="{{url_for('quest_admin_switch')}}"><input type="hidden" name="_csrf" value="{{csrf_token}}"><input type="hidden" name="enabled" value="{{0 if enabled else 1}}">
<button>{{tr('Wylacz','Switch off') if enabled else tr('Wlacz','Switch on')}}</button></form></div>''',
                    query=query, players=players, enabled=enabled)

    @app.route('/quests/switch', methods=['POST'])
    @login_required
    def quest_admin_switch():
        # The host panel's before_request checks the form's CSRF token.
        on = 1 if request.form.get('enabled') == '1' else 0
        with db() as con, con.cursor() as cur:
            cur.execute('INSERT INTO player.web_quest_admin_config(id,enabled) VALUES(1,%s) '
                        'ON DUPLICATE KEY UPDATE enabled=VALUES(enabled)', (on,))
        flash(tr('Konczenie misji: wlaczone.', 'Quest completion: on.') if on else
              tr('Konczenie misji: wylaczone.', 'Quest completion: off.'), 'success')
        return redirect(url_for('quest_admin_search'))

    @app.route('/player/<int:pid>/quests')
    @login_required
    def quest_admin_player(pid):
        p, flags, bot = player_flags(pid)
        query = request.args.get('q', '')[:100]
        mode = request.args.get('mode', 'active')
        quests = []
        for key, f in flags.items():
            c = CATALOG.get(key, {})
            value = f.get('__status', 0)
            state = stage_name(key, value)
            active = value != 0 and state.lower().strip('_') not in ('complete', 'giveup', 'cancel')
            if mode != 'all' and not active:
                continue
            if fold(query) not in fold(key + ' ' + c.get('label', key) + ' ' + state):
                continue
            quests.append(dict(key=key, label=c.get('label', key), value=value, state=state,
                               can=is_active(key, value) and not p['companion'] and not p['gm'],
                               handled=bool(c.get('adapter') or c.get('full_skip')), active=active, flags=f))
        quests.sort(key=lambda q: q['key'])
        with db() as con, con.cursor() as cur:
            cur.execute('SELECT id,quest_name,requester,source,status,result,created_at,finished_at '
                        'FROM player.web_quest_admin_actions WHERE player_id=%s ORDER BY id DESC LIMIT 50', (pid,))
            history = cur.fetchall()
        for h in history:
            h['status_text'] = status_text(h['status'])
        return page('''
<p><a href="{{url_for('quest_admin_search')}}">{{tr('Misje graczy','Player quests')}}</a> / <a href="{{url_for('player',pid=p.id)}}">{{p.name}}</a></p>
<div class="card"><h3>{{tr('Misje','Quests')}}: {{p.name}}</h3>
{% if p.companion %}<p><b>{{tr('Towarzysz gracza - tylko podglad, bez skipu i nagrod.','A player\\'s companion - view only, no skip and no reward.')}}</b></p>{% elif p.gm %}<p><b>{{tr('Postac GM - tylko podglad.','A GM\\'s character - view only.')}}</b></p>{% elif bot %}<p><b>{{tr('Bot populacji: zakonczenie wykonuje jego rdzen, gdy bot jest w grze.','A bot of the population: its own core carries the completion out while it is in the game.')}}</b></p>{% endif %}
<p class="muted">{{tr('To zapis z bazy serwera. Podczas gry moze chwilowo odbiegac od stanu postaci. Przed nagroda serwer sprawdza aktualny etap w pamieci gry.','This is the server database\\'s copy. While the character plays it can lag behind. Before any reward the server checks the stage the game holds.')}}</p>
<form method="get"><input name="q" placeholder="{{tr('Nazwa misji lub etap','Quest or stage')}}" value="{{query}}">
<select name="mode"><option value="active" {% if mode!='all' %}selected{% endif %}>{{tr('Aktywne','Active')}}</option><option value="all" {% if mode=='all' %}selected{% endif %}>{{tr('Wszystkie zapisane','Everything saved')}}</option></select> <button>{{tr('Filtruj','Filter')}}</button></form>
<p>{{quests|length}} {{tr('misji','quests')}}</p><div style="overflow-x:auto"><table><thead><tr><th>{{tr('Misja','Quest')}}</th><th>{{tr('Etap','Stage')}}</th><th></th></tr></thead><tbody>
{% for q in quests %}<tr><td><a href="{{url_for('quest_admin_detail',pid=p.id,key=q.key)}}">{{q.label}}</a><br><small>{{q.key}}</small></td><td>{{q.state}}<br><small>{{q.value}}</small></td><td>{% if q.can %}<a class="btn" href="{{url_for('quest_admin_detail',pid=p.id,key=q.key)}}">{{tr('Zakoncz','Complete')}}</a>{% elif q.active and not q.handled %}<button disabled title="{{tr('ten quest nie ma jeszcze obslugi autozakonczenia','this quest has no automatic completion yet')}}">{{tr('Zakoncz','Complete')}}</button>{% else %}<a href="{{url_for('quest_admin_detail',pid=p.id,key=q.key)}}">{{tr('Podglad','View')}}</a>{% endif %}</td></tr>{% else %}<tr><td colspan="3">{{tr('Brak misji spelniajacych filtr.','No quest matches the filter.')}}</td></tr>{% endfor %}</tbody></table></div></div>
<div class="card"><h3>{{tr('Historia dzialan GM','GM actions')}}</h3><p class="muted">{{tr('Nagroda wymaga obecnosci postaci w grze i zamkniecia handlu i sklepu. Nieudane lub niepewne wykonanie widac ponizej.','A reward needs the character in the game with its trade and shop closed. A failed or uncertain one shows below.')}}</p>
{% for h in history %}<p>#{{h.id}} · {{h.quest_name}} · {{h.status_text}}<br><small>{{h.created_at}} · {{h.requester}} / {{h.source}} · {{h.result}}</small></p>{% else %}<p>{{tr('Brak dzialan.','No actions.')}}</p>{% endfor %}
<a class="btn" href="{{url_for('quest_admin_player',pid=p.id,mode=mode,q=query)}}">{{tr('Odswiez','Refresh')}}</a></div>''',
                    p=p, quests=quests, query=query, mode=mode, history=history, bot=bot)

    @app.route('/player/<int:pid>/quests/<key>', methods=['GET', 'POST'])
    @login_required
    def quest_admin_detail(pid, key):
        p, flags, bot = player_flags(pid)
        if key not in flags:
            abort(404)
        f = flags[key]
        value = f.get('__status', 0)
        c = CATALOG.get(key, {})
        with db() as con, con.cursor() as cur:
            enabled = enabled_now(cur)
            variant = (request.form if request.method == 'POST' else request.args).get('variant', '')[:32]
            reward, sig, rplan, choices = reward_preview(cur, p, key, flags, variant)
            cycle = rplan['cycle'] if rplan else -1
            active_key = str(pid) + ':' + key + (':' + str(cycle) if cycle >= 0 else '')
            cur.execute('SELECT id,status FROM player.web_quest_admin_actions WHERE active_key=%s', (active_key,))
            previous = cur.fetchone()
        if previous:
            previous['status_text'] = status_text(previous['status'])
        can = (not p['companion'] and not p['gm'] and is_active(key, value) and bool(sig)
               and (cycle >= 0 or not f.get('qa_reward_id', 0)) and not previous)
        if request.method == 'POST':
            # The host panel's before_request checks the form's CSRF token too.
            if not enabled:
                abort(409, tr('Konczenie misji jest wylaczone.', 'Quest completion is switched off.'))
            if p['companion'] or p['gm']:
                abort(409, tr('Towarzysz gracza i postac GM nie koncza misji z panelu.',
                              "A player's companion and a GM's character end no quest from the panel."))
            if not can:
                abort(409, tr('Misja nie moze zostac zakonczona ponownie. Odswiez liste.', 'The quest cannot be completed again. Refresh the list.'))
            try:
                expected = int(request.form['expected'])
                token = uuid.UUID(request.form['token']).hex
            except (KeyError, ValueError):
                abort(400)
            reason = request.form.get('reason', '').strip()
            if expected != value:
                abort(409, tr('Etap misji sie zmienil. Odswiez liste.', 'The quest\'s stage changed. Refresh the list.'))
            if request.form.get('expected_cycle') != str(cycle):
                abort(409, tr('Cykl misji sie zmienil. Odswiez podglad.', 'The quest\'s cycle changed. Refresh the preview.'))
            if request.form.get('reward_signature') != sig:
                abort(409, tr('Nagroda sie zmienila. Odswiez podglad przed potwierdzeniem.', 'The reward changed. Refresh the preview before confirming.'))
            if request.form.get('confirm') != 'yes' or not 3 <= len(reason) <= 160:
                abort(400, tr('Potwierdz wykonanie i wpisz powod (3-160 znakow).', 'Confirm it and give a reason (3-160 characters).'))
            try:
                stored_reason = reason.encode('cp1250').decode('latin1')
            except UnicodeError:
                abort(400, tr('Powod zawiera nieobslugiwane znaki.', 'The reason holds characters the database cannot keep.'))
            with db() as con, con.cursor() as cur:
                cur.execute("SELECT COUNT(*) n FROM player.web_quest_admin_actions WHERE status='pending'")
                if cur.fetchone()['n'] >= 1000:
                    abort(429, tr('Kolejka jest pelna.', 'The queue is full.'))
                # Patch 20, 4J: the request waits for a character out of the
                # game (a week), and a bot's is its core's (QUESTDONE).
                cur.execute('INSERT IGNORE INTO player.web_quest_admin_actions(request_key,active_key,player_id,quest_name,'
                            'expected_state,reward_signature,variant,expected_cycle,requester,source,reason,expires_at) '
                            'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,DATE_ADD(NOW(),INTERVAL 7 DAY))',
                            ('web:' + token, active_key, pid, key, expected, sig, rplan['variant'], cycle,
                             'admin@' + (request.remote_addr or '?')[:40], 'panel_bot' if bot else 'web', stored_reason))
                if bot:
                    cur.execute('SELECT id FROM player.web_quest_admin_actions WHERE request_key=%s', ('web:' + token,))
                    made = cur.fetchone()
                    if made:
                        cur.execute("INSERT INTO player.web_admin_queue (player_name,cmd,arg1,arg2,status) "
                                    "VALUES (%s,'QUESTDONE',%s,%s,'await')", (p['name'], key, str(made['id'])))
            flash(tr('Zlecenie zapisano. Wykona sie, gdy postac bedzie w grze; wynik pojawi sie w historii.',
                     'Queued. It is carried out when the character is in the game; the result shows in the history.'), 'success')
            return redirect(url_for('quest_admin_player', pid=pid, mode='all'))
        follow = c.get('adapter') and c['adapter'].get('follow') or []
        return page('''
<p><a href="{{url_for('quest_admin_player',pid=p.id,mode='all')}}">{{tr('Misje','Quests')}}: {{p.name}}</a></p>
<div class="card"><h3>{{c.get('label',key)}}</h3><p>{{key}} · {{tr('etap','stage')}} <b>{{state}}</b> ({{value}})</p>
{% if p.companion %}<p><b>{{tr('Towarzysz gracza - tylko podglad, bez skipu i nagrod.','A player\\'s companion - view only, no skip and no reward.')}}</b></p>{% elif p.gm %}<p><b>{{tr('Postac GM - tylko podglad.','A GM\\'s character - view only.')}}</b></p>{% endif %}
{% if choices|length > 1 %}<form method="get"><label>{{tr('Wariant zakonczenia i nagrody','How it ends and its reward')}} <select name="variant">{% for id,label in choices %}<option value="{{id}}" {% if rplan and id==rplan.variant %}selected{% endif %}>{{label}}</option>{% endfor %}</select></label> <button>{{tr('Pokaz nagrode','Show the reward')}}</button></form>{% endif %}
<h4>{{tr('Nagroda dla tej postaci','The reward for this character')}}</h4>{% for r in reward %}<p>{{r}}</p>{% endfor %}
{% if follow %}<p>{{tr('Dalszy ciag','Continues with')}}: {% for q,s in follow %}{{q}} ({{s}}) {% endfor %}. {{tr('Serwer zachowa juz rozpoczety dalszy etap.','A later quest already begun is kept.')}}</p>{% endif %}
{% if can and enabled %}<form method="post" onsubmit="return confirm('{{tr('Quest zostanie zakonczony, a postac dostanie nagrode. Nie da sie tego cofnac.','The quest will be completed and the character rewarded. This cannot be undone.')}}')"><input type="hidden" name="_csrf" value="{{csrf_token}}"><input type="hidden" name="expected" value="{{value}}"><input type="hidden" name="token" value="{{token}}"><input type="hidden" name="reward_signature" value="{{signature}}">
<input type="hidden" name="variant" value="{{rplan.variant}}"><input type="hidden" name="expected_cycle" value="{{cycle}}">
<label>{{tr('Powod interwencji GM','Why the GM steps in')}} <input name="reason" required minlength="3" maxlength="160"></label>
<p><label><input type="checkbox" name="confirm" value="yes" required> {{tr('Wykonaj pelny skip misji gracza','Do the full skip of the quest of')}} {{p.name}}: {{tr('przyznaj opisane pozostale nagrody, pomin wymagania i przejdz do konca zadania lub nastepnego cyklu.','give the remaining rewards above, skip what is required and go to the quest\\'s end or its next cycle.')}}</label></p><button class="big">{{tr('Pelny skip z nagroda','Full skip with reward')}}</button></form>
{% elif previous %}<p>{{tr('Zlecenie','Request')}} #{{previous.id}}: {{previous.status_text}}. {{tr('Ponowne przyznanie nagrody jest zablokowane.','The reward cannot be given again.')}}</p>
{% elif can %}<p>{{tr('Konczenie misji jest wylaczone (Misje graczy).','Quest completion is switched off (Player quests).')}}</p>{% else %}<p>{{tr('Tylko podglad: misja jest nieaktywna, juz nagrodzona, nalezy do bota albo nie ma sprawdzonej obslugi zakonczenia.','View only: the quest is inactive, already rewarded, a bot\\'s, or has no checked way to end it.')}}</p>{% endif %}
</div><div class="card"><h3>{{tr('Zapisane flagi','Saved flags')}}</h3><table><tr><th>{{tr('Flaga','Flag')}}</th><th>{{tr('Wartosc','Value')}}</th></tr>{% for k,v in flags.items() %}<tr><td>{{k}}</td><td>{{v}}</td></tr>{% endfor %}</table></div>''',
                    p=p, key=key, c=c, value=value, state=stage_name(key, value), flags=f, reward=reward, can=can,
                    enabled=enabled, token=uuid.uuid4().hex, previous=previous, signature=sig, rplan=rplan,
                    choices=choices, cycle=cycle, bot=bot, follow=follow)

    try:
        app.jinja_env.globals['quest_admin_ready'] = True
    except Exception:  # noqa: BLE001
        pass
