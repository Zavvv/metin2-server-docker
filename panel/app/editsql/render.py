# =============================================================================
#  /editsql -- wyglad.
#
#  Szkielet to markup strony glownej (front_page.render): #page ->
#  .header-wrapper > #header, .container-wrapper > .container, .col-1 / .col-2,
#  .footer-wrapper > #footer. Arkusze te same co strona (reset -> all -> front)
#  plus editsql.css.
#
#  Czym rozni sie od strony glownej (i dlaczego):
#
#   * UKLAD JEST PLYNNY. Szablon ma sztywne 930 px i srodkowa kolumne 510 px -
#     w niej tabela potworow (11 kolumn) albo formularz przedmiotu (60 pol) nie
#     ma szans sie zmiescic, wiec rozjezdzal sie poza ramke. Edytor zajmuje
#     szerokosc okna (min. 930 px, maks. 1560 px): lewe menu zostaje 157 px,
#     a tresc rosnie. Pergaminowa ramka tresci jest rozciagana przez
#     border-image (rogi i krawedzie w naturalnym rozmiarze, srodek rozciagniety),
#     wiec nie ma znieksztalconych krawedzi przy zadnej szerokosci.
#   * NIE MA PRAWEJ KOLUMNY. Wyszukiwarka i filtry sa nad tabela, a wskazowki pod
#     trescia - prawa kolumna 157 px zabierala miejsce tabelom, a jej tekst
#     wylewal sie poza ramke.
#   * FORMULARZE W <div id="register">: reguly pol z all.css sa zapisane jako
#     "#register ...", editsql.css podnosi swoistosc przez #page.
# =============================================================================

import json
import os
import threading
import time

from . import db, i18n, schema
from .i18n import P, T, js, tr

_lock = threading.RLock()
_icons = {"ts": 0.0, "map": {}, "files": set()}
ICON_TTL = 900.0
UNKNOWN_ICON = "/static/icons/_unknown.png"


# -----------------------------------------------------------------------------
#  Ikony przedmiotow (konwencja tego projektu: /static/item_icons.json)
# -----------------------------------------------------------------------------
def _icon_state():
    with _lock:
        if _icons["map"] and time.time() - _icons["ts"] < ICON_TTL:
            return _icons
    here = db.ns().get("_HERE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mapping, files = {}, set()
    try:
        with open(os.path.join(here, "static", "item_icons.json"), encoding="utf-8") as handle:
            mapping = json.load(handle) or {}
    except Exception:                              # noqa: BLE001
        mapping = {}
    try:
        files = set(os.listdir(os.path.join(here, "static", "icons")))
    except OSError:
        files = set()
    with _lock:
        _icons.update({"map": mapping, "files": files, "ts": time.time()})
    return _icons


def icon_map():
    return _icon_state()["map"]


def item_icon(vnum):
    """URL ikony przedmiotu albo ikona zastepcza.

    Nazwa pliku NIE jest vnumem - jest w item_icons.json. Gdy mapy nie ma,
    probujemy pliku 00000-owego, ale tylko jesli NAPRAWDE istnieje na dysku;
    inaczej przegladarka dostawala 404 i pokazywala pusta ramke.
    """
    try:
        key = str(int(vnum))
    except (TypeError, ValueError):
        return UNKNOWN_ICON
    state = _icon_state()
    name = state["map"].get(key)
    if not name:
        guess = ("00000" + key)[-5:] + ".png"
        name = guess if guess in state["files"] else None
    if name and (not state["files"] or name in state["files"]):
        return "/static/icons/" + name
    return UNKNOWN_ICON


def icon_img(vnum, size="", title=""):
    return ('<img class="esq-icon%s" src="%s" alt="" loading="lazy"%s '
            'onerror="this.onerror=null;this.src=\'%s\'" />'
            % ((" esq-icon-" + size) if size else "", _esc(item_icon(vnum)),
               (' title="%s"' % _esc(title)) if title else "", UNKNOWN_ICON))


def skill_icon(vnum, master=False):
    return "/static/skill_icons/%s%s.png" % (vnum, "_m" if master else "")


# -----------------------------------------------------------------------------
#  Nazwy przedmiotow i potworow - prosto z bazy, paczkami (jedno IN na strone)
# -----------------------------------------------------------------------------
_names = {"item": {}, "mob": {}, "ts": 0.0}
# vnum -> the official English name, for the vnums whose stored name is the
# one the names file matched (i18n.english_name), worked out when the stored
# name is read, before it is trimmed. Cleared with _names.
_names_en = {"item": {}, "mob": {}}
NAMES_TTL = 120.0


def _name_table(kind):
    if kind == "item":
        return schema.table("world", "item_proto") or schema.table("player", "item_proto")
    return schema.table("world", "mob_proto") or schema.table("player", "mob_proto")


def prefetch_names(kind, vnums):
    """Wczytuje nazwy dla wielu vnumow jednym zapytaniem (cache 2 min)."""
    wanted = set()
    for value in vnums:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            wanted.add(number)
    with _lock:
        if time.time() - _names["ts"] > NAMES_TTL:
            _names["item"].clear()
            _names["mob"].clear()
            _names_en["item"].clear()
            _names_en["mob"].clear()
            _names["ts"] = time.time()
        missing = [v for v in wanted if v not in _names[kind]]
    if not missing:
        return
    table = _name_table(kind)
    if table is None:
        return
    col = "locale_name" if "locale_name" in table["by_name"] else (
        "name" if "name" in table["by_name"] else None)
    if col is None or "vnum" not in table["by_name"]:
        return
    found, english = {}, {}
    try:
        for start in range(0, len(missing), 400):
            chunk = missing[start:start + 400]
            rows = db.query("SELECT `vnum` AS v, %s AS n FROM %s WHERE `vnum` IN (%s)"
                            % (db.qi(col), db.qt(table["db"], table["name"]),
                               ",".join(["%s"] * len(chunk))), tuple(chunk))
            for row in rows:
                stored = db.decode(row["n"], table["by_name"][col]["charset"]) or ""
                found[int(row["v"])] = stored.strip()
                if col == "locale_name":
                    # The name as the engine holds it, CP1250, whatever the
                    # column's own charset (i18n.english_name).
                    english[int(row["v"])] = i18n.english_name(kind, row["v"], stored)
    except Exception:                              # noqa: BLE001
        return
    with _lock:
        for number in missing:
            _names[kind][number] = found.get(number)      # None = nie ma w bazie
            if english.get(number):
                _names_en[kind][number] = english[number]
            else:
                _names_en[kind].pop(number, None)


def known_name(kind, vnum):
    """(istnieje, nazwa). istnieje=None, gdy nie wiadomo (tabeli brak)."""
    try:
        number = int(vnum)
    except (TypeError, ValueError):
        return False, ""
    if number <= 0:
        return False, ""
    with _lock:
        cached = _names[kind].get(number, "missing")
    if cached == "missing":
        prefetch_names(kind, [number])
        with _lock:
            cached = _names[kind].get(number, "missing")
    if cached == "missing":
        return None, ""
    if cached is None:
        return False, ""
    return True, cached


def shown_name(kind, vnum, name=None):
    """The name of a vnum this reader reads: the official English one for a
    reader of English where the world's stored name is the one the names file
    matched, else the stored name. `name` is that stored name when the caller
    has it already (a label it read itself); a name that is not the stored
    one is shown as it is."""
    if name is not None and i18n.lang() == "pl":
        return name
    stored = known_name(kind, vnum)[1]
    if name is None:
        name = stored
    if not name or i18n.lang() == "pl" or name != stored:
        return name
    try:
        number = int(vnum)
    except (TypeError, ValueError):
        return name
    with _lock:
        english = _names_en[kind].get(number)
    return english or name


def item_name(vnum):
    """Shown to the reader (shown_name); known_name keeps the stored one."""
    return shown_name("item", vnum)


def mob_name(vnum):
    return shown_name("mob", vnum)


def invalidate_names():
    with _lock:
        _names["item"].clear()
        _names["mob"].clear()
        _names_en["item"].clear()
        _names_en["mob"].clear()


# -----------------------------------------------------------------------------
#  Nawigacja
# -----------------------------------------------------------------------------
#  Kolejnosc i ikony to warstwa prezentacji; to, CZY modul istnieje,
#  rozstrzyga schema.detect() na podstawie realnych tabel.
MODULES = [
    ("items",     "\U0001F5E1", P("Przedmioty", "Items"),
     P("Nazwy, typ, ceny, limity, bonusy, ulepszanie i gniazda.",
       "Names, type, prices, limits, bonuses, refining and sockets.")),
    ("mobs",      "\U0001F479", P("Potwory i bossowie", "Monsters and bosses"),
     P("PŻ, obrażenia, obrona, poziom, ranga, nagroda, zachowanie, odporności.",
       "HP, damage, defence, level, rank, reward, behaviour, resistances.")),
    ("drops",     "\U0001F48E", P("Drop specjalny", "Special drop"),
     P("Potwory, które mają przypisany przedmiot w kolumnie drop_item.",
       "Monsters with an item in their drop_item column.")),
    ("refine",    "\U0001F528", P("Ulepszenia", "Refining"),
     P("Przepisy +N → +N+1: koszt, szansa, materiały i przedmioty, które ich używają.",
       "Recipes +N → +N+1: cost, chance, materials and the items that use them.")),
    ("bonuses",   "\U0001F3B2", P("Bonusy", "Bonuses"),
     P("Które bonusy losują się na jakim slocie i z jakimi wartościami.",
       "Which bonuses roll on which slot, and with what values.")),
    ("chests",    "\U0001F381", P("Skrzynki", "Chests"),
     P("Przedmioty-skrzynki (typ 20 i 23). Zawartość jest w plikach serwera.",
       "Chest items (types 20 and 23). What they hold is in the server's files.")),
    ("shops",     "\U0001F3EA", P("Sklepy NPC", "NPC shops"),
     P("Sklep, NPC, który go otwiera, i jego pozycje.",
       "A shop, the NPC who opens it, and what it sells.")),
    ("spawns",    "\U0001F4CD", P("Działki gildii", "Guild land"),
     P("Działki (world.land) na mapie i stojące na nich budynki.",
       "Plots (world.land) on the map and the buildings standing on them.")),
    ("skills",    "✨",     P("Umiejętności", "Skills"),
     P("Wzory obrażeń, czas trwania, koszt PE, cooldown, wymagania.",
       "Damage formulas, duration, SP cost, cooldown, requirements.")),
    ("exp",       "\U0001F4CA", P("Doświadczenie", "Experience"),
     P("Ile doświadczenia potrzeba na awans z poziomu na poziom.",
       "How much experience each level needs to reach the next.")),
    ("crafting",  "\U0001F3AF", P("Wytwarzanie", "Crafting"),
     P("Przepisy: wynik, składniki, cena, szansa.",
       "Recipes: result, ingredients, price, chance.")),
    ("quests",    "\U0001F4DC", P("Nagrody questów", "Quest rewards"),
     P("Doświadczenie, yang i przedmioty za quest.",
       "Experience, yang and items for a quest.")),
    ("itemshop",  "\U0001F6D2", P("ItemShop", "ItemShop"),
     P("Co, za ile i od jakiego poziomu można kupić.",
       "What can be bought, for how much and from which level.")),
    ("gm",        "\U0001F451", P("Prawa GM", "GM rights"),
     P("Lista GM w common.gmlist.", "The GM list in common.gmlist.")),
    ("structure", "\U0001F5C4", P("Struktura bazy", "Database structure"),
     P("Bazy, tabele i kolumny: typy, klucze, indeksy, liczba wierszy.",
       "Databases, tables and columns: types, keys, indexes, row counts.")),
    ("history",   "\U0001F570", P("Historia zmian", "Change history"),
     P("Kto, kiedy i co zmienił - z cofaniem jednym kliknięciem.",
       "Who changed what and when - with one-click undo.")),
    ("labels",    "\U0001F3F7", P("Etykiety", "Labels"),
     P("Nazwy typów przedmiotów, rang i typów potworów.",
       "Names of item types, monster ranks and monster types.")),
    ("apply",     "✅",     P("Zastosuj", "Apply"),
     P("Przekazanie zmian do gry: restart rdzeni.",
       "Handing the changes to the game: a restart of the cores.")),
]
MODULE_TITLES = {key: title for key, _icon, title, _hint in MODULES}
MODULE_ICONS = {key: icon for key, icon, _title, _hint in MODULES}

NAV_GROUPS = [
    (P("Dane gry", "Game data"), ("items", "mobs", "drops", "refine", "bonuses", "chests")),
    (P("Świat i handel", "World and trade"), ("shops", "spawns", "skills", "exp", "crafting")),
    (P("Pozostałe", "Other"), ("quests", "itemshop", "gm")),
    (P("Narzędzia", "Tools"), ("structure", "history", "labels", "apply")),
]


def available_modules():
    """Moduly, ktore NAPRAWDE istnieja w tej bazie (schema.detect())."""
    try:
        return schema.detect()
    except Exception:                              # noqa: BLE001
        return {}


def nav_html(active, found):
    out = []
    for group_title, ids in NAV_GROUPS:
        rows = [m for m in MODULES if m[0] in ids and m[0] in found]
        if not rows:
            continue
        out.append('<li class="esq-nav-group">%s</li>' % _esc(group_title))
        for key, icon, title, _hint in rows:
            cls = ' class="active"' if key == active else ""
            out.append('<li><a href="/editsql/%s"%s title="%s"><span class="esq-nav-ico">%s</span>%s</a></li>'
                       % (key, cls, _esc(title), icon, _esc(title)))
    return "".join(out)


# -----------------------------------------------------------------------------
#  Pomocnicze
# -----------------------------------------------------------------------------
def _esc(value):
    """HTML-escape bez zaleznosci od MarkupSafe (pakiet testuje sie bez Flaska)."""
    import html
    return html.escape("" if value is None else str(value), quote=True)


esc = _esc


def raw(value):
    """Markup, ktory juz jest bezpieczny (budowany tylko w tym module)."""
    return value


def num(value):
    """1234567 -> '1 234 567' (twarda spacja, zeby liczba nie lamala sie)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            number = float(value)
            text = ("%.2f" % number).rstrip("0").rstrip(".")
            return _esc(text)
        except (TypeError, ValueError):
            return _esc(value)
    return "{:,}".format(number).replace(",", "&#8239;")


def brand():
    return db.ns().get("BRAND") or "Metin2 Singleplayer"


def messages(items):
    """items = [(kind, text)]: ok / info / error."""
    out = []
    for kind, text in items or ():
        cls = {"ok": "esq-note-ok", "info": "esq-note-info"}.get(kind, "esq-note-warn")
        out.append('<div class="esq-note esq-flash %s" role="status">%s</div>' % (cls, _esc(text)))
    return "".join(out)


# -----------------------------------------------------------------------------
#  Szkielet strony
# -----------------------------------------------------------------------------
CSS_VERSION = "5"

_HEAD = """<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>%(title)s</title>
<link rel="icon" type="image/png" href="/favicon.ico" />
<link href="/static/cms/css/reset.css" rel="stylesheet" type="text/css" media="all" />
<link href="/static/cms/css/all.css" rel="stylesheet" type="text/css" media="all" />
<link href="/static/cms/css/front.css?v=6" rel="stylesheet" type="text/css" media="all" />
<link href="/static/cms/css/editsql.css?v=%(css)s" rel="stylesheet" type="text/css" media="all" />"""

_FOOTER = """<div class="footer-wrapper">
	<div id="footer">
		<ul>
			<li class="first"><a href="/admin">%(admin)s</a> &nbsp;&bull;&nbsp;
			<a href="/editsql">%(editor)s</a> &nbsp;&bull;&nbsp;
			<a href="/editsql/history">%(history)s</a> &nbsp;&bull;&nbsp;
			<a href="/editsql/apply">%(apply)s</a><br />%(brand)s</li>
		</ul>
	</div>
</div>"""

_SCRIPT = """<script>
(function () {
  document.addEventListener('click', function (ev) {
    var open = ev.target.closest('[data-esq-preview]');
    if (open) { ev.preventDefault(); document.getElementById(open.getAttribute('data-esq-preview')).showModal(); return; }
    var close = ev.target.closest('[data-esq-close]');
    if (close) { ev.preventDefault(); close.closest('dialog').close(); return; }
    // Caly wiersz listy jest klikalny (poza linkami, przyciskami i polami).
    var row = ev.target.closest('tr[data-href]');
    if (row && !ev.target.closest('a, button, input, select, textarea, label, form')) {
      if (ev.ctrlKey || ev.metaKey || ev.button === 1) { window.open(row.getAttribute('data-href'), '_blank'); }
      else { window.location.href = row.getAttribute('data-href'); }
    }
  });
  // Potwierdzenie przy przyciskach niszczacych (usun pozycje, cofnij).
  document.addEventListener('submit', function (ev) {
    var btn = ev.submitter || ev.target.querySelector('[data-confirm]');
    var text = (btn && btn.getAttribute && btn.getAttribute('data-confirm')) || ev.target.getAttribute('data-confirm');
    if (text && !window.confirm(text)) { ev.preventDefault(); }
  });
  // Zmienione pola formularza dostaja znacznik, a licznik pokazuje, ile ich jest.
  var form = document.querySelector('form[data-esq-edit]');
  if (form) {
    var counter = document.getElementById('esq-dirty');
    var refresh = function () {
      var n = 0;
      form.querySelectorAll('.esq-field').forEach(function (f) {
        var changed = false;
        f.querySelectorAll('input, select, textarea').forEach(function (el) {
          if (el.type === 'hidden' || el.readOnly || el.disabled) { return; }
          if (el.type === 'checkbox' || el.type === 'radio') { if (el.checked !== el.defaultChecked) { changed = true; } }
          else if (el.tagName === 'SELECT') { for (var i = 0; i < el.options.length; i++) { if (el.options[i].selected !== el.options[i].defaultSelected) { changed = true; } } }
          else if (el.value !== el.defaultValue) { changed = true; }
        });
        f.classList.toggle('esq-dirty', changed);
        if (changed) { n++; }
      });
      if (counter) { counter.textContent = n ? ('%(changed)s' + n) : '%(unchanged)s'; counter.classList.toggle('esq-has', n > 0); }
    };
    form.addEventListener('input', refresh);
    form.addEventListener('change', refresh);
    form.addEventListener('reset', function () { setTimeout(refresh, 0); });
    refresh();
  }
  // "Zaznacz wszystkie" w naglowku listy: pola "pk" przypiete atrybutem form.
  document.querySelectorAll('input[data-esq-check-all]').forEach(function (all) {
    all.addEventListener('change', function () {
      var id = all.getAttribute('data-esq-check-all');
      document.querySelectorAll('input[type="checkbox"][name="pk"]').forEach(function (box) {
        if (box.getAttribute('form') === id) { box.checked = all.checked; }
      });
    });
  });
  // Podglad nazwy przedmiotu/potwora pod polem vnum (bez przeladowania).
  document.querySelectorAll('input[data-esq-lookup]').forEach(function (input) {
    var out = document.getElementById(input.id + '_look');
    var timer = null;
    input.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var v = parseInt(input.value, 10);
        if (!out) { return; }
        if (!v) { out.innerHTML = '<span class="esq-dim">%(none)s</span>'; return; }
        fetch('/editsql/api/name?kind=' + input.getAttribute('data-esq-lookup') + '&vnum=' + v, {credentials: 'same-origin'})
          .then(function (r) { return r.json(); })
          .then(function (d) { out.innerHTML = d.html; })
          .catch(function () {});
      }, 250);
    });
  });
})();
</script>"""


def page(title, body, active=None, messages_list=(), side="", head_extra="", found=None,
         wide=True, crumbs=None, subtitle=""):
    """Pelna strona w stylu strony glownej (uklad plynny, bez prawej kolumny).

    `side` (dawniej prawa kolumna) laduje pod trescia jako ramka wskazowek.
    `crumbs` = [(etykieta, href albo None)] - sciezka nad tytulem.
    """
    if found is None:
        found = available_modules()
    title = tr(title)
    if crumbs is None:
        crumbs = []
        if active and active in MODULE_TITLES and title != tr(MODULE_TITLES[active]):
            crumbs.append((MODULE_TITLES[active], "/editsql/%s" % active))
    crumb_html = ""
    if crumbs:
        parts = ['<a href="/editsql">%s</a>' % _esc(T("Edytor", "Editor"))]
        for label, href in crumbs:
            parts.append(('<a href="%s">%s</a>' % (_esc(href), _esc(label))) if href
                         else '<span>%s</span>' % _esc(label))
        crumb_html = '<nav class="esq-crumbs">%s</nav>' % ' <i>&rsaquo;</i> '.join(parts)
    icon = MODULE_ICONS.get(active, "")
    center = """
<div class="content esq-content">
	<div class="content-bg">
		<div class="content-bg-bottom">
			%(crumbs)s
			<h2>%(title)s%(sub)s</h2>
			%(msgs)s
			%(body)s
			%(side)s
		</div>
	</div>
</div>""" % {"crumbs": crumb_html, "title": _esc(title),
             "sub": ('<small>%s</small>' % _esc(subtitle)) if subtitle else "",
             "msgs": messages(messages_list), "body": body, "side": side}
    html = """<!DOCTYPE html>
<html lang="%(lang)s">
	<head>
		%(head)s
		%(head_extra)s
	</head>
	<body class="editsql-body">
<div id="page">
	<div class="header-wrapper">
		<div id="header">
			<a class="logo" href="/"><strong>Metin2</strong></a>
			%(langs)s
			<div class="esq-banner">
				<a class="esq-banner-title" href="/editsql">&#128736; %(editor)s</a>
				<div class="esq-banner-sub">%(banner_sub)s</div>
			</div>
		</div>
	</div>
	<div class="container-wrapper">
		<div class="container esq-container">
			<div class="col-1">
				<div class="boxes-top">&nbsp;</div>
				<div class="modul-box">
					<div class="modul-box-bg">
						<div class="modul-box-bg-bottom">
							<ul class="main-nav esq-nav">
								<li><a href="/editsql"%(home_cls)s><span class="esq-nav-ico">&#127968;</span>%(home)s</a></li>
%(nav)s
							</ul>
						</div>
					</div>
				</div>
				<div class="boxes-middle">&nbsp;</div>
				<div class="modul-box modul-box-2">
					<div class="modul-box-bg">
						<div class="modul-box-bg-bottom">
							<ul class="main-nav" style="padding-bottom: 0px;">
								<li><a href="/admin">%(admin)s</a></li>
								<li><a href="/map">%(live_map)s</a></li>
%(logout)s
							</ul>
						</div>
					</div>
				</div>
				<div class="boxes-bottom">&nbsp;</div>
			</div>
			<div class="col-2 esq-main">
%(center)s
				<div class="shadow">&nbsp;</div>
			</div>
		</div>
	</div>
</div>
%(footer)s
%(script)s
	</body>
</html>""" % {
        "lang": i18n.lang(),
        "head": _HEAD % {"title": _esc("%s — %s" % (title, brand())), "css": CSS_VERSION},
        "head_extra": head_extra,
        "langs": lang_bar(),
        "editor": _esc(T("Edytor bazy danych", "Database editor")),
        "banner_sub": (icon + " " + _esc(MODULE_TITLES.get(active, ""))) if active in MODULE_TITLES
        else _esc(T("Przedmioty, potwory, drop, sklepy i reszta danych gry",
                    "Items, monsters, drops, shops and the rest of the game's data")),
        "home_cls": ' class="active"' if not active else "",
        "home": _esc(T("Start edytora", "Editor home")),
        "admin": _esc(T("Panel administratora", "Admin panel")),
        "live_map": _esc(T("Mapa na żywo", "Live map")),
        "logout": _logout_item(),
        "nav": nav_html(active, found),
        "center": center,
        "footer": _FOOTER % {
            "brand": _esc(brand()),
            "admin": _esc(T("Panel administratora", "Admin panel")),
            "editor": _esc(T("Edytor bazy danych", "Database editor")),
            "history": _esc(T("Historia zmian", "Change history")),
            "apply": _esc(T("Zastosuj zmiany", "Apply changes"))},
        "script": _SCRIPT % {
            "changed": js(T("Zmienione pola: ", "Changed fields: ")),
            "unchanged": js(T("Brak zmian", "No changes")),
            "none": js(_esc(T("brak", "none")))},
    }
    return raw(html)


def lang_bar():
    """The language bar of the front page (front_page._langs), for the editor.

    Polski and English go through the panel's own /lang/<code>, so the choice is
    the panel's and the front page's too, and the panel sends the reader back
    to the page they were on. German and Turkish are shown but greyed out: the
    editor is not in them yet, and a reader of either reads English, which is
    the one marked.
    """
    current = i18n.lang()
    panel = db.ns()
    names = panel.get("LANGS") or {"pl": "Polski", "en": "English", "de": "Deutsch", "tr": "Türkçe"}
    out = ['<div class="front-langs esq-langs">']
    for code, label in names.items():
        if code in i18n.LANGUAGES:
            try:
                href = panel.url_for("setlang", code=code)
            except Exception:                      # noqa: BLE001 - outside the panel's app
                href = "/lang/%s" % code
            out.append('<a href="%s"%s>%s</a>' % (_esc(href), ' class="on"' if code == current else "",
                                                 _esc(label)))
        else:
            out.append('<span class="esq-lang-off" title="%s" aria-disabled="true">%s</span>'
                       % (_esc(T("Jeszcze niegotowe", "Not ready yet")), _esc(label)))
    out.append("</div>")
    return "".join(out)


def _logout_item():
    """Link "Wyloguj z edytora" - tylko gdy wejscie bylo hasłem do edytora."""
    try:
        session = db.ns().session
        if session.get("editsql_auth") and not session.get("auth"):
            return '<li><a href="/editsql/logout">%s</a></li>' % _esc(T("Wyloguj z edytora",
                                                                        "Log out of the editor"))
    except Exception:                              # noqa: BLE001
        pass
    return ""


# -----------------------------------------------------------------------------
#  Komponenty
# -----------------------------------------------------------------------------
def box(title, inner, hint="", klass="", hint_html=False):
    hint_block = ""
    if hint:
        hint_block = '<p class="esq-hint">%s</p>' % (hint if hint_html else _esc(hint))
    return ('<section class="esq-box %s"><h3 class="esq-box-title">%s</h3>%s<div class="esq-box-body">%s</div></section>'
            % (klass, _esc(title), hint_block, inner))


def section(title, inner, hint=""):
    """Sekcja formularza (fieldset z legenda i siatka pol)."""
    return ('<fieldset class="esq-section"><legend>%s</legend>%s'
            '<div class="esq-grid">%s</div></fieldset>'
            % (_esc(title), ('<p class="esq-hint">%s</p>' % _esc(hint)) if hint else "", inner))


def field(name, label, value, hint=None, widget="text", choices=None, extra_attrs="",
          note="", column=None, after="", title_attr="", wide=False):
    """Pole formularza: etykieta nad polem, nazwa kolumny obok, podpowiedz pod.

    choices: lista wartosci albo lista par (wartosc, etykieta).
    """
    name_attr = _esc(name)
    label = tr(label)
    value_attr = _esc("" if value is None else value)
    if widget == "select" and choices is not None:
        options = []
        seen = False
        for choice in choices:
            if isinstance(choice, (tuple, list)):
                opt_value, opt_label = choice[0], choice[1]
            else:
                opt_value, opt_label = choice, choice
            selected = str(opt_value) == str("" if value is None else value)
            seen = seen or selected
            options.append('<option value="%s"%s>%s</option>'
                           % (_esc(opt_value), " selected" if selected else "", _esc(opt_label)))
        if not seen and value not in (None, ""):
            # Wartosc spoza listy (np. typ, ktorego nie zna silnik) nie moze
            # zniknac z formularza - zapis wyzerowalby ja po cichu.
            options.insert(0, '<option value="%s" selected>%s %s</option>'
                           % (value_attr, value_attr, _esc(T("(spoza listy)", "(not on the list)"))))
        control = ('<select name="%s" id="f_%s" %s>%s</select>'
                   % (name_attr, name_attr, extra_attrs, "".join(options)))
    elif widget == "textarea":
        control = ('<textarea name="%s" id="f_%s" rows="3" %s>%s</textarea>'
                   % (name_attr, name_attr, extra_attrs, value_attr))
    elif widget == "set":
        picked = set(p for p in str(value or "").split(",") if p)
        boxes = ['<input type="hidden" name="__set__%s" value="1" />' % name_attr]
        for choice in choices or ():
            boxes.append('<label class="esq-chip"><input type="checkbox" name="%s" value="%s"%s %s />'
                         '<span>%s</span></label>'
                         % (name_attr, _esc(choice), " checked" if choice in picked else "",
                            extra_attrs, _esc(choice)))
        control = '<div class="esq-chips" id="f_%s">%s</div>' % (name_attr, "".join(boxes))
    else:
        control = ('<input type="%s" name="%s" id="f_%s" value="%s" %s />'
                   % (_esc(widget), name_attr, name_attr, value_attr, extra_attrs))
    col_tag = ('<code class="esq-col" title="%s">%s</code>' % (_esc(title_attr), _esc(column))
               if column and column != label else "")
    return ('<div class="esq-field%s">'
            '<label for="f_%s"><span class="esq-label" title="%s">%s</span>%s</label>%s'
            '%s%s%s</div>'
            % (" esq-field-wide" if wide or widget in ("set", "textarea") else "",
               name_attr, _esc(label), _esc(label), col_tag,
               ('<span class="esq-field-note">%s</span>' % _esc(note)) if note else "",
               control, after,
               ('<span class="esq-field-hint">%s</span>' % _esc(hint)) if hint else ""))


def widget_for(col):
    """(widget, extra_atrybuty) dla kolumny z metamodelu."""
    if col["enum"]:
        return "select", ""
    if col["set"]:
        return "set", ""
    if col["data_type"] in ("text", "mediumtext", "longtext"):
        return "textarea", ""
    if col["data_type"] in ("tinyint", "smallint", "mediumint", "int", "bigint"):
        attrs = 'step="1"'
        if col["range"]:
            attrs += ' min="%d" max="%d"' % col["range"]
        return "number", attrs
    if col["data_type"] in ("float", "double", "decimal"):
        return "text", 'inputmode="decimal"'
    attrs = ""
    if col.get("length"):
        attrs = 'maxlength="%d"' % col["length"]
    return "text", attrs


def column_hint(col):
    """Pelny opis kolumny: typ, NULL, default, kodowanie (do dymka)."""
    bits = [col["type"]]
    bits.append("NULL" if col["nullable"] else "NOT NULL")
    if col["default"] is not None:
        bits.append(T("domyślnie %s", "default %s") % col["default"])
    if col["charset"]:
        bits.append(col["charset"])
    if col["comment"]:
        bits.append(col["comment"])
    return " · ".join(bits)


def table(headers, rows, klass="esq-table", empty=None, scroll=True,
          head_html=None):
    """Tabela. rows = [(atrybuty_tr, [komorki])], komorka = html albo (klasa, html).

    Naglowki zostaja takze przy pustym wyniku. Tabela siedzi w .esq-scroll, wiec
    za szeroka przewija sie w ramce zamiast wylewac sie poza pergamin.
    """
    if empty is None:
        empty = T("Brak wierszy.", "No rows.")
    if head_html is None:
        head_html = "".join(_cell("th", h) for h in headers)
    if not rows:
        span = max(1, len(headers) if headers else head_html.count("<th"))
        body = '<tr><td colspan="%d" class="esq-empty-cell">%s</td></tr>' % (span, _esc(empty))
    else:
        body = "".join("<tr%s>%s</tr>" % (attrs, "".join(_cell("td", c) for c in cells))
                       for attrs, cells in rows)
    html = '<table class="%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (
        klass, head_html, body)
    return ('<div class="esq-scroll">%s</div>' % html) if scroll else html


def _cell(tag, cell):
    if isinstance(cell, tuple):
        return '<%s class="%s">%s</%s>' % (tag, cell[0], cell[1], tag)
    return "<%s>%s</%s>" % (tag, cell, tag)


def pager(base_url, page_no, per_page, total, extra=""):
    """"1–50 z 18 420" z numerami stron. `extra` to gotowe "a=1&b=2&"."""
    if total <= 0:
        return ""
    pages = max(1, (total + per_page - 1) // per_page)
    if pages == 1:
        return ""
    page_no = min(max(1, page_no), pages)
    first = (page_no - 1) * per_page + 1
    last = min(total, page_no * per_page)
    sep = "&" if "?" in base_url else "?"

    def href(n):
        return _esc("%s%s%spage=%d" % (base_url, sep, extra, n))

    links = []
    if page_no > 1:
        links.append('<a class="esq-page" href="%s" rel="prev" title="%s">&#8592;</a>'
                     % (href(page_no - 1), _esc(T("Poprzednia", "Previous"))))
    else:
        links.append('<span class="esq-page esq-page-off">&#8592;</span>')
    shown = sorted({1, 2, pages - 1, pages, page_no - 2, page_no - 1, page_no, page_no + 1, page_no + 2})
    prev = 0
    for n in shown:
        if n < 1 or n > pages:
            continue
        if prev and n - prev > 1:
            links.append('<span class="esq-page-gap">&hellip;</span>')
        if n == page_no:
            links.append('<span class="esq-page esq-page-on">%d</span>' % n)
        else:
            links.append('<a class="esq-page" href="%s">%d</a>' % (href(n), n))
        prev = n
    if page_no < pages:
        links.append('<a class="esq-page" href="%s" rel="next" title="%s">&#8594;</a>'
                     % (href(page_no + 1), _esc(T("Następna", "Next"))))
    else:
        links.append('<span class="esq-page esq-page-off">&#8594;</span>')
    return ('<div class="esq-pager"><span class="esq-page-info">%s&ndash;%s %s %s</span>'
            '<span class="esq-page-links">%s</span></div>'
            % (num(first), num(last), _esc(T("z", "of")), num(total), "".join(links)))


def actions(buttons, sticky=False, extra=""):
    """buttons = [(etykieta, rodzaj, atrybuty)] - rodzaj: primary, plain, danger, link."""
    out = []
    for label, kind, attrs in buttons:
        if kind == "link":
            out.append('<a class="esq-btn esq-btn-plain" %s>%s</a>' % (attrs, _esc(label)))
        elif kind == "reset":
            out.append('<button type="reset" class="esq-btn esq-btn-plain" %s>%s</button>'
                       % (attrs, _esc(label)))
        else:
            out.append('<button type="submit" class="esq-btn esq-btn-%s" %s>%s</button>'
                       % (kind, attrs, _esc(label)))
    return '<div class="esq-actions%s">%s%s</div>' % (" esq-actions-sticky" if sticky else "",
                                                      "".join(out), extra)


def dialog(dialog_id, title, inner, close_label=None):
    if close_label is None:
        close_label = T("Zamknij", "Close")
    return ('<dialog id="%s" class="esq-dialog"><h3>%s</h3>%s'
            '<div class="esq-actions"><button data-esq-close type="button" '
            'class="esq-btn esq-btn-plain">%s</button></div></dialog>'
            % (_esc(dialog_id), _esc(title), inner, _esc(close_label)))


def csrf_input():
    return ('<input type="hidden" name="_csrf" value="%s" />'
            % _esc(db.ns().csrf_token()))


def _module_db(kind):
    table_ = _name_table(kind)
    return table_["db"] if table_ else None


def link_item(vnum, label=None, icon=True, show_vnum=True):
    """Ikona + nazwa przedmiotu z linkiem do jego edycji (albo sam numer)."""
    try:
        number = int(vnum)
    except (TypeError, ValueError):
        return _esc(vnum)
    if number <= 0:
        return '<span class="esq-dim">—</span>'
    exists, name = known_name("item", number)
    name = shown_name("item", number, label or name)
    db_name = _module_db("item")
    icon_html = icon_img(number, title=name) if icon else ""
    text = ('<span class="esq-ref-name">%s</span>' % _esc(name)) if name else ""
    vnum_html = ('<span class="esq-ref-vnum">#%s</span>' % number) if show_vnum else ""
    if exists is False:
        return ('<span class="esq-ref esq-ref-missing" title="%s">'
                '%s<span class="esq-ref-name">%s</span>%s</span>'
                % (_esc(T("Nie ma przedmiotu o tym vnum", "There is no item with this vnum")),
                   icon_img(0) if icon else "", _esc(T("nie ma przedmiotu", "no such item")),
                   vnum_html))
    if db_name is None:
        return '<span class="esq-ref">%s%s%s</span>' % (icon_html, text, vnum_html)
    return ('<a class="esq-ref" href="/editsql/items/%s/%d">%s%s%s</a>'
            % (_esc(db_name), number, icon_html, text, vnum_html))


def link_mob(vnum, label=None, show_vnum=True):
    try:
        number = int(vnum)
    except (TypeError, ValueError):
        return _esc(vnum)
    if number <= 0:
        return '<span class="esq-dim">—</span>'
    exists, name = known_name("mob", number)
    name = shown_name("mob", number, label or name)
    vnum_html = ('<span class="esq-ref-vnum">#%s</span>' % number) if show_vnum else ""
    if exists is False:
        return ('<span class="esq-ref esq-ref-missing" title="%s">'
                '<span class="esq-ref-name">%s</span>%s</span>'
                % (_esc(T("Nie ma potwora o tym vnum", "There is no monster with this vnum")),
                   _esc(T("nie ma potwora", "no such monster")), vnum_html))
    db_name = _module_db("mob")
    text = ('<span class="esq-ref-name">%s</span>' % _esc(name)) if name else ""
    if db_name is None:
        return '<span class="esq-ref">%s%s</span>' % (text, vnum_html)
    return ('<a class="esq-ref" href="/editsql/mobs/%s/%d">%s%s</a>'
            % (_esc(db_name), number, text, vnum_html))


def notes_html(db_name, table_name):
    """Ostrzezenia o tabeli (schema.table_notes) - zawsze pod naglowkiem."""
    out = []
    for kind, text in schema.table_notes(db_name, table_name):
        out.append('<div class="esq-note esq-note-%s">%s</div>' % (kind, _esc(text)))
    return "".join(out)


def side_help(title, paragraphs, extra=""):
    """Wskazowki pod trescia (dawniej prawa kolumna)."""
    items = "".join("<li>%s</li>" % _esc(p) for p in paragraphs if p)
    if not items and not extra:
        return ""
    return ('<details class="esq-help"><summary>%s</summary><ul>%s</ul>%s</details>'
            % (_esc(title), items, extra))


def side_search(action, placeholder="", value="", hidden=None):
    """Zostawione dla zgodnosci: wyszukiwarka jest teraz w pasku nad tabela."""
    return ""


def status_badge(ok, text_ok, text_bad):
    return ('<span class="esq-badge %s">%s</span>'
            % ("esq-badge-ok" if ok else "esq-badge-bad", _esc(text_ok if ok else text_bad)))


def badge(text, kind=""):
    return '<span class="esq-badge%s">%s</span>' % ((" esq-badge-" + kind) if kind else "", _esc(text))
