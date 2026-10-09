# =============================================================================
#  /editsql -- widoki specjalne (tam, gdzie zwykla tabela nie wystarcza).
#
#   * LANCUCH ULEPSZEN: przepis i nastepny stopien z refine_set/refined_vnum
#     (NIE z vnum+1 - w tej bazie 69 przypadkow nie jest vnum+1).
#   * SIATKA BONUSOW: ktore bonusy moga sie wylosowac na broni, zbroi, helmie...
#   * MAPA DZIALEK: world.land trzyma x/y WZGLEDEM MAPY (dzialka 1 na mapie 1
#     ma x=20200, a mapa zaczyna sie od 409600) - wczesniej liczone byly jak
#     wspolrzedne bezwzgledne i znaczniki lezaly poza obrazkiem.
#   * POZYCJE SKLEPU: dodawanie i usuwanie po jednym wierszu, kazde z historia.
# =============================================================================

from . import db, i18n, labels, render, safety, schema
from .i18n import P, T, js, tr

MAP_BOUNDS_NAME = "PLAYERBOT_MAP_BOUNDS"
# The English names are the panel's (admin_panel.EVENT_MAPS).
MAP_NAMES = {
    1: "Yongan (Shinsoo M1)", 3: "Jayang (Shinsoo M2)",
    4: P("Ziemia Klanu Shinsoo", "Shinsoo Guild Land"),
    21: "Joan (Chunjo M1)", 23: "Bokjung (Chunjo M2)",
    24: P("Ziemia Klanu Chunjo", "Chunjo Guild Land"),
    41: "Pyongmoo (Jinno M1)", 43: "Bakra (Jinno M2)",
    44: P("Ziemia Klanu Jinno", "Jinno Guild Land"),
    61: P("Góra Sohan", "Mount Sohan"), 62: P("Ognista Ziemia", "Doyyumhwaji"),
    63: P("Pustynia Yongbi", "Yongbi Desert"), 64: P("Dolina Orków", "Orc Valley"),
    65: P("Świątynia Hwang", "Hwang Temple"), 67: P("Las Duchów", "Ghost Wood"),
    68: P("Czerwony Las", "Red Wood"),
}


def map_label(map_index):
    try:
        number = int(map_index)
    except (TypeError, ValueError):
        return str(map_index)
    name = tr(MAP_NAMES.get(number))
    return ("%d · %s" % (number, name)) if name else (T("mapa %d", "map %d") % number)


def _qt(table):
    return db.qt(table["db"], table["name"])


# -----------------------------------------------------------------------------
#  Mapa (swiat <-> procenty, ta sama transformacja co /map)
# -----------------------------------------------------------------------------
def map_bounds():
    return db.ns().get(MAP_BOUNDS_NAME) or {}


def map_bounds_for(map_index):
    try:
        return map_bounds().get(int(map_index))
    except (TypeError, ValueError):
        return None


def _local(box, x, y):
    """Wspolrzedne dzialki wzgledem poczatku mapy.

    world.land trzyma je wzgledem mapy; gdyby ktos wpisal bezwzgledne (x wiekszy
    niz poczatek mapy), tez trafimy - odejmujemy poczatek.
    """
    base_x, base_y, span_x, span_y = box
    x, y = float(x), float(y)
    if x >= base_x and base_x > span_x:
        x -= base_x
    if y >= base_y and base_y > span_y:
        y -= base_y
    return x, y


def world_to_percent(map_index, x, y):
    box = map_bounds_for(map_index)
    if not box or not box[2] or not box[3]:
        return None
    lx, ly = _local(box, x, y)
    return 100.0 * lx / box[2], 100.0 * ly / box[3]


def _tile(map_index):
    tiles = db.ns().get("PLAYERBOT_MAP_TILES") or {}
    try:
        return int(map_index) in tiles
    except (TypeError, ValueError):
        return False


def map_html(map_index, x=None, y=None, width=None, height=None, dialog_id=None,
             clickable=False, target_x="x", target_y="y", others=()):
    """Podglad mapy z prostokatem dzialki; `others` = inne dzialki (szare)."""
    box = map_bounds_for(map_index)
    if not box:
        return ('<div class="esq-note esq-note-info">%s</div>'
                % (T("Mapa %s nie ma w panelu zdefiniowanych granic, więc nie mogę pokazać podglądu.",
                     "The panel has no bounds for map %s, so there is no picture of it.")
                   % render._esc(map_label(map_index))))
    _bx, _by, span_x, span_y = box
    overlay = []
    for other in others:
        origin = world_to_percent(map_index, other.get("x") or 0, other.get("y") or 0)
        if not origin:
            continue
        w = 100.0 * float(other.get("width") or 0) / span_x
        h = 100.0 * float(other.get("height") or 0) / span_y
        overlay.append('<a class="esq-map-box esq-map-other" href="/editsql/spawns/world/%s" '
                       'style="left:%.3f%%;top:%.3f%%;width:%.3f%%;height:%.3f%%" '
                       'title="%s"><span>%s</span></a>'
                       % (render._esc(other.get("id")), origin[0], origin[1], max(w, 0.6),
                          max(h, 0.6), render._esc(T("Działka %s", "Plot %s") % other.get("id")),
                          render._esc(other.get("id"))))
    if x is not None and y is not None:
        origin = world_to_percent(map_index, x, y)
        if origin and width and height:
            w = 100.0 * float(width) / span_x
            h = 100.0 * float(height) / span_y
            overlay.append('<span class="esq-map-box esq-map-current" style="left:%.3f%%;top:%.3f%%;'
                           'width:%.3f%%;height:%.3f%%"></span>' % (origin[0], origin[1],
                                                                   max(w, 0.6), max(h, 0.6)))
        if origin:
            overlay.append('<span class="esq-map-marker" style="left:%.3f%%;top:%.3f%%" '
                           'title="%s, %s"></span>' % (origin[0], origin[1],
                                                       render._esc(x), render._esc(y)))
    if _tile(map_index):
        image = ('<img class="esq-map-canvas" src="/api/map_tile/%s?v=%s" alt="%s" />'
                 % (render._esc(map_index),
                    render._esc(db.ns().get("PLAYERBOT_MAP_TILE_VERSION") or "1"),
                    render._esc(map_label(map_index))))
    else:
        image = ('<div class="esq-map-canvas esq-map-missing" style="aspect-ratio:%s/%s">'
                 '%s</div>' % (span_x, span_y, T("brak rysunku mapy %s", "no picture of map %s")
                               % render._esc(map_label(map_index))))
    attrs = ""
    if clickable:
        attrs = (' data-esq-map-click="1" data-span-x="%s" data-span-y="%s" '
                 'data-target-x="%s" data-target-y="%s"'
                 % (span_x, span_y, render._esc(target_x), render._esc(target_y)))
    return ('<div class="esq-map-wrap"><div class="esq-map"%s>%s%s</div></div>'
            '<p class="esq-hint">%s</p>'
            % (attrs, image, "".join(overlay),
               T("%s: rozmiar %s &times; %s (współrzędne działek liczone od lewego górnego rogu mapy).",
                 "%s: size %s &times; %s (plot coordinates count from the map's top left corner).")
               % (render._esc(map_label(map_index)), render.num(span_x), render.num(span_y))))


def map_script():
    """MAP_SCRIPT with its one sentence in the reader's language (replaced, not
    %-formatted: the script has percent signs of its own)."""
    return (MAP_SCRIPT.replace("%(picked)s", js(T("Nowe położenie: X ", "New position: X ")))
            .replace("%(then)s", js(T(" - zapisz przez „Podgląd zmian”.",
                                      " - save it through “Preview changes”."))))


MAP_SCRIPT = """
<script>
(function () {
  document.querySelectorAll('[data-esq-map-click]').forEach(function (box) {
    box.addEventListener('click', function (ev) {
      if (ev.target.closest('a')) { return; }
      var rect = box.getBoundingClientRect();
      var px = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
      var py = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height));
      var x = Math.round(px * parseFloat(box.getAttribute('data-span-x')));
      var y = Math.round(py * parseFloat(box.getAttribute('data-span-y')));
      var fx = document.getElementById('f_' + box.getAttribute('data-target-x'));
      var fy = document.getElementById('f_' + box.getAttribute('data-target-y'));
      if (fx && !fx.readOnly) { fx.value = x; fx.dispatchEvent(new Event('input', {bubbles: true})); }
      if (fy && !fy.readOnly) { fy.value = y; fy.dispatchEvent(new Event('input', {bubbles: true})); }
      var marker = box.querySelector('.esq-map-marker');
      if (marker) { marker.style.left = (px * 100).toFixed(3) + '%'; marker.style.top = (py * 100).toFixed(3) + '%'; }
      var cur = box.querySelector('.esq-map-current');
      if (cur) { cur.style.left = (px * 100).toFixed(3) + '%'; cur.style.top = (py * 100).toFixed(3) + '%'; }
      var info = document.getElementById('esq-map-pick');
      if (info) { info.textContent = '%(picked)s' + x + ', Y ' + y + '%(then)s'; }
    });
  });
})();
</script>
"""


# -----------------------------------------------------------------------------
#  Powiazania wiersza (relacje wbudowane, bo baza nie ma kluczy obcych)
# -----------------------------------------------------------------------------
def _select(table, columns, where="", params=(), order="", limit=200):
    """SELECT z METAMODELU: bierze tylko kolumny, ktore naprawde sa."""
    wanted = [name for name in columns if name in table["by_name"]]
    if not wanted:
        return []
    sql = "SELECT %s FROM %s" % (", ".join(db.qi(name) for name in wanted),
                                 db.qt(table["db"], table["name"]))
    if where:
        sql += " WHERE " + where
    if order:
        order_cols = [name for name in order if name in table["by_name"]]
        if order_cols:
            sql += " ORDER BY " + ", ".join(db.qi(name) for name in order_cols)
    if limit:
        sql += " LIMIT %d" % int(limit)
    rows = db.query(sql, tuple(params))
    return [safety.decode_row(table, row) for row in rows]


def _items_table():
    return schema.table("world", "item_proto") or schema.table("player", "item_proto")


def _kv(rows):
    return '<div class="esq-kv">%s</div>' % "".join(
        '<div class="esq-kv-row"><span class="esq-kv-key">%s</span><span class="esq-kv-val">%s</span></div>'
        % (render._esc(key), value) for key, value in rows)


def related_refine_from_item(spec, row):
    """Dla przedmiotu: jego przepis ulepszenia i nastepny stopien."""
    refine_set = row.get("refine_set")
    refined = row.get("refined_vnum")
    items = _items_table()
    recipes = schema.table("world", "refine_proto")
    blocks = []
    kv = []
    if refined:
        kv.append((T("Po udanym ulepszeniu", "After a successful refine"), render.link_item(refined)))
    if items is not None and row.get("vnum"):
        before = _select(items, ("vnum",), where="%s=%%s" % db.qi("refined_vnum"),
                         params=(row.get("vnum"),), limit=5)
        if before:
            kv.append((T("Powstaje z", "Made from"), " ".join(render.link_item(r["vnum"]) for r in before)))
    if refine_set and recipes is not None:
        rec = _select(recipes, ("id", "cost", "prob", "vnum0", "count0", "vnum1", "count1",
                                "vnum2", "count2", "vnum3", "count3", "vnum4", "count4"),
                      where="%s=%%s" % db.qi("id"), params=(refine_set,), limit=1)
        if rec:
            kv.extend(_recipe_rows(rec[0]))
            if items is not None:
                count = int(db.scalar("SELECT COUNT(*) AS n FROM %s WHERE %s=%%s"
                                      % (_qt(items), db.qi("refine_set")), (refine_set,), 0) or 0)
                if count > 1:
                    blocks.append('<div class="esq-note esq-note-info">%s</div>'
                                  % (T("Tego przepisu używa %d przedmiotów - zmiana kosztu, szansy "
                                       "albo materiałów dotyczy ich wszystkich.",
                                       "%d items use this recipe - a change of the cost, the chance "
                                       "or the materials applies to all of them.") % count))
        else:
            blocks.append('<div class="esq-note esq-note-warn">%s</div>'
                          % (T("Przepis #%s nie istnieje w world.refine_proto - ulepszenie tego "
                               "przedmiotu się nie uda.",
                               "Recipe #%s does not exist in world.refine_proto - refining this "
                               "item will fail.") % render._esc(refine_set)))
    if not kv and not blocks:
        return ""
    return render.box(T("Ulepszanie", "Refining"), _kv(kv) + "".join(blocks),
                      T("Kolejność stopni wynika z refine_set i refined_vnum, nie z vnum+1.",
                        "The order of the grades comes from refine_set and refined_vnum, not from vnum+1."))


def _recipe_rows(recipe):
    materials = []
    for index in range(5):
        vnum = recipe.get("vnum%d" % index)
        count = recipe.get("count%d" % index) or 0
        if vnum:
            materials.append('<span class="esq-mat">%s<b>&times;%s</b></span>'
                             % (render.link_item(vnum), render._esc(count)))
    return [(T("Przepis", "Recipe"),
             T('<a href="/editsql/refine/world/%s">#%s</a> &middot; koszt <b>%s</b> yang '
               '&middot; szansa <b>%s%%</b>',
               '<a href="/editsql/refine/world/%s">#%s</a> &middot; cost <b>%s</b> yang '
               '&middot; chance <b>%s%%</b>')
             % (render._esc(recipe.get("id")), render._esc(recipe.get("id")),
                render.num(recipe.get("cost")), render._esc(recipe.get("prob")))),
            (T("Materiały", "Materials"), "".join(materials) or
             '<span class="esq-dim">%s</span>' % render._esc(T("bez materiałów", "no materials")))]


def related_item_usage(spec, row):
    """Dla przedmiotu: gdzie jest uzywany (material ulepszen, drop potworow)."""
    vnum = row.get("vnum")
    if not vnum:
        return ""
    out = []
    recipes = schema.table("world", "refine_proto")
    if recipes is not None:
        cond = " OR ".join("%s=%%s" % db.qi("vnum%d" % i) for i in range(5)
                           if ("vnum%d" % i) in recipes["by_name"])
        if cond:
            found = _select(recipes, ("id", "cost", "prob"), where=cond,
                            params=tuple([vnum] * cond.count("%s")), order=("id",), limit=30)
            if found:
                out.append((T("Materiał w przepisach", "Material in recipes"), ", ".join(
                    '<a href="/editsql/refine/world/%s">#%s</a>' % (render._esc(r["id"]), render._esc(r["id"]))
                    for r in found) + ("…" if len(found) == 30 else "")))
    mobs = schema.table("world", "mob_proto") or schema.table("player", "mob_proto")
    if mobs is not None and "drop_item" in mobs["by_name"]:
        found = _select(mobs, ("vnum", "locale_name"), where="%s=%%s" % db.qi("drop_item"),
                        params=(vnum,), order=("vnum",), limit=20)
        if found:
            out.append((T("Drop specjalny potworów", "Monsters' special drop"), " ".join(
                render.link_mob(r["vnum"], r.get("locale_name")) for r in found)))
    if not out:
        return ""
    return render.box(T("Gdzie jest używany", "Where it is used"), _kv(out))


# Ile przedmiotow pokazac przy przepisie ulepszenia. Przepisy pierwszych stopni
# wskazuja setki przedmiotow, a ramka stoi nad formularzem, wiec strona pokazuje
# poczatek z liczba reszty, a "pokaz wszystkie" dopiero na zadanie (z twardym
# limitem).
REFINE_USAGE_LIMIT = 20
REFINE_USAGE_ALL = 3000
REFINE_USERS_IN_LIST = 3


def _refine_ready():
    items = _items_table()
    if items is None or "refine_set" not in items["by_name"] or "vnum" not in items["by_name"]:
        return None
    return items


def refine_users(recipe_ids, per_recipe=REFINE_USERS_IN_LIST):
    """{id przepisu: (ilu przedmiotow, [pierwsze vnumy])} dla strony listy - dwa zapytania."""
    items = _refine_ready()
    ids = sorted({int(i) for i in recipe_ids if i not in (None, "")})
    if items is None or not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    counts = {int(r["r"]): int(r["n"]) for r in db.query(
        "SELECT %s AS r, COUNT(*) AS n FROM %s WHERE %s IN (%s) GROUP BY %s"
        % (db.qi("refine_set"), _qt(items), db.qi("refine_set"), marks, db.qi("refine_set")),
        tuple(ids))}
    sample = {}
    if counts:
        for r in db.query("SELECT %s AS r, %s AS v FROM %s WHERE %s IN (%s) ORDER BY %s, %s LIMIT 5000"
                          % (db.qi("refine_set"), db.qi("vnum"), _qt(items), db.qi("refine_set"),
                             marks, db.qi("refine_set"), db.qi("vnum")), tuple(ids)):
            picked = sample.setdefault(int(r["r"]), [])
            if len(picked) < per_recipe:
                picked.append(int(r["v"]))
    render.prefetch_names("item", [v for vnums in sample.values() for v in vnums])
    return {rid: (total, sample.get(rid, [])) for rid, total in counts.items()}


def refine_usage(recipe_id, limit=REFINE_USAGE_LIMIT):
    """(ilu przedmiotow uzywa przepisu, pierwsze `limit` z nich po vnum)."""
    items = _refine_ready()
    if items is None:
        return 0, []
    total = int(db.scalar("SELECT COUNT(*) AS n FROM %s WHERE %s=%%s"
                          % (_qt(items), db.qi("refine_set")), (recipe_id,), 0) or 0)
    if not total:
        return 0, []
    rows = _select(items, ("vnum", "locale_name", "refined_vnum"),
                   where="%s=%%s" % db.qi("refine_set"), params=(recipe_id,),
                   order=("vnum",), limit=limit)
    return total, rows


def related_refine_items(spec, row):
    """Dla przepisu: gdzie jest uzywany - przedmioty, ktorych refine_set go wskazuje."""
    if _refine_ready() is None:
        return ""
    show_all = False
    try:
        show_all = db.ns().request.args.get("uzycia") == "wszystkie"
    except Exception:                              # noqa: BLE001 - poza zadaniem (testy)
        show_all = False
    total, rows = refine_usage(row.get("id"), REFINE_USAGE_ALL if show_all else REFINE_USAGE_LIMIT)
    title = T("Gdzie jest używany", "Where it is used")
    if not total:
        return render.box(title, '<p class="esq-empty">%s</p>' % render._esc(T(
            "Żaden przedmiot nie wskazuje tego przepisu (item_proto.refine_set) - jego zmiana "
            "nie wpłynie na grę.",
            "No item points at this recipe (item_proto.refine_set) - changing it will not "
            "change the game.")))
    render.prefetch_names("item", [r.get("vnum") for r in rows] + [r.get("refined_vnum") for r in rows])
    last = '<span class="esq-dim">%s</span>' % render._esc(T("ostatni stopień", "last grade"))
    body = [("", [("esq-c-ref", render.link_item(entry.get("vnum"))),
                  ("esq-c-arrow", "&rarr;"),
                  ("esq-c-ref", render.link_item(entry.get("refined_vnum"))
                   if entry.get("refined_vnum") else last)])
            for entry in rows]
    more = total - len(rows)
    tail = ""
    if more > 0:
        here = "/editsql/%s/%s/%s" % (render._esc(spec.get("id") or "refine"), render._esc(spec["db"]),
                                      render._esc(row.get("id")))
        tail = ('<p class="esq-more">%s%s</p>'
                % (T("i %d więcej", "and %d more") % more, "" if show_all else
                   ' &middot; <a href="%s?uzycia=wszystkie#esq-uzycia">%s</a>'
                   % (here, render._esc(T("pokaż wszystkie", "show all")))))
    return ('<div id="esq-uzycia">%s</div>' % render.box(
        "%s: %d %s" % (title, total, i18n.plural(total, ("przedmiot", "przedmioty", "przedmiotów"),
                                                 ("item", "items"))),
        render.table([T("Przedmiot", "Item"), "", T("Po ulepszeniu", "After refining")], body) + tail,
        T("Zmiana kosztu, szansy albo materiałów dotyczy wszystkich tych przedmiotów naraz.",
          "A change of the cost, the chance or the materials applies to all of these items at once.")))


# -----------------------------------------------------------------------------
#  Wytwarzanie: okna NPC z paczki gry
#
#  Okno wytwarzania NPC wymienia przepisy PO NUMERZE w pliku serwera
#  quest/libs/crafting/crafting_data.lua (mt2009), ktorego panel nie widzi.
#  Ponizej jest lista z paczki - tylko do ostrzezen: nowy przepis bez numeru na
#  liscie okna nie pojawi sie w grze, a usuniety numer, ktory lista dalej
#  wymienia, przerywa quest okna (crafting.send_avail/send_recipes czytaja
#  przepis bez sprawdzenia, czy jest). Edytor niczego tu nie blokuje.
# -----------------------------------------------------------------------------
CRAFTING_DATA_FILE = "quest/libs/crafting/crafting_data.lua"
_GUILD_SMELTING = P("Przetapianie gildii", "Guild smelting")
CRAFTING_WINDOWS = (
    (P("Kowal", "Blacksmith"), (20016,), tuple(range(1, 7))),
    (P("Baek-Go (zielarstwo)", "Baek-Go (herbalism)"), (20018,),
     tuple(range(11, 58)) + (67, 68, 71, 72, 73, 74) + tuple(range(78, 89)) + (92, 93, 94, 95)),
    (P("Kucharz", "Cook"), (20008,), (90, 91)),
    ("Heuk-Young", (20090,), (100, 101, 102, 103)),
    (P("Stajenny", "Stable keeper"), (20349,), (151, 152)),
    (P("Strzały", "Arrows"), (11001, 11003, 11005), tuple(range(8001, 8006))),
    (P("Czarna stal", "Black steel"), (20402,), (201, 202, 203, 204)),
    ("Nakajima", (20364,), (301, 302, 303)),
    (P("Alchemik (rudy)", "Alchemist (ores)"), (20001,), tuple(range(351, 363))),
    (P("Włóczęga", "Wanderer"), (20041,), (221,)),
    (_GUILD_SMELTING, (20060,), (50621,)),
) + tuple((_GUILD_SMELTING, (npc,), (50623 + npc - 20062,)) for npc in range(20062, 20073))


def crafting_windows_of(vnum):
    """[(nazwa okna, (npc,...))] z paczki, ktore wymieniaja ten numer przepisu."""
    try:
        number = int(vnum)
    except (TypeError, ValueError):
        return []
    return [(title, npcs) for title, npcs, numbers in CRAFTING_WINDOWS if number in numbers]


def _windows_text(windows):
    return ", ".join("%s (%s)" % (render._esc(title), " ".join(render.link_mob(n) for n in npcs))
                     for title, npcs in windows)


def crafting_window_note(vnum, deleting=False):
    windows = crafting_windows_of(vnum)
    if deleting:
        if not windows:
            return ""
        return ('<div class="esq-note esq-note-warn">%s</div>'
                % (T('Przepis <b>#%s</b> jest na liście okna wytwarzania %s w paczce gry (%s). '
                     'Okno odczytuje przepisy po numerze - bez tego wiersza quest przerwie się przy '
                     'jego otwieraniu. Jeśli usuwasz przepis na stałe, usuń też jego numer z tego '
                     'pliku serwera (edytor go nie zmienia).',
                     'Recipe <b>#%s</b> is on the list of the crafting window %s in the game '
                     'package (%s). The window reads its recipes by number - without this row its '
                     'quest stops when the window opens. If the recipe goes for good, take its '
                     'number out of that server file too (the editor does not change it).')
                   % (render._esc(vnum), _windows_text(windows), CRAFTING_DATA_FILE)))
    if windows:
        return ('<div class="esq-note esq-note-info">%s</div>'
                % (T('Numer <b>#%s</b> jest na liście okna wytwarzania %s w paczce gry (%s) - '
                     'przepis pojawi się w tym oknie po restarcie rdzeni.',
                     'Number <b>#%s</b> is on the list of the crafting window %s in the game '
                     'package (%s) - the recipe appears in that window after a restart of the '
                     'cores.')
                   % (render._esc(vnum), _windows_text(windows), CRAFTING_DATA_FILE)))
    return ('<div class="esq-note esq-note-warn">%s</div>'
            % (T('Żadne okno wytwarzania z paczki gry nie wymienia numeru <b>#%s</b>. Przepis '
                 'będzie w bazie, ale gracz zobaczy go dopiero wtedy, gdy ten numer trafi na listę '
                 'okna NPC w %s (plik serwera - edytor go nie zmienia).',
                 'No crafting window of the game package lists number <b>#%s</b>. The recipe '
                 'will be in the database, but a player sees it only once the number is on an '
                 'NPC window\'s list in %s (a server file - the editor does not change it).')
               % (render._esc(vnum), CRAFTING_DATA_FILE)))


def related_crafting_window(spec, row):
    """Dla przepisu wytwarzania: w ktorym oknie NPC go widac."""
    windows = crafting_windows_of(row.get("vnum"))
    body = (_kv([(T("Okno NPC", "NPC window"), _windows_text(windows))]) if windows else
            '<p class="esq-empty">%s</p>' % render._esc(T(
                "Żadne okno wytwarzania z paczki gry nie wymienia tego numeru - gracz go nie zobaczy.",
                "No crafting window of the game package lists this number - a player will not see it.")))
    return render.box(T("Okno wytwarzania", "Crafting window"), body,
                      T("Lista okien pochodzi z %s w paczce gry; panel nie widzi tego pliku na "
                        "serwerze.",
                        "The list of windows comes from %s in the game package; the panel cannot "
                        "see that file on the server.") % CRAFTING_DATA_FILE)


def crafting_rows_table(rows):
    """Przepisy do usuniecia, z tym, co robia - na ekranie potwierdzenia."""
    from . import editor
    render.prefetch_names("item", [r.get("item_vnum") for r in rows] +
                          [v for r in rows for v in editor._pairs(r.get("recipe"))[0::2]])
    body = []
    for row in rows:
        numbers = editor._pairs(row.get("recipe"))
        mats = "".join('<span class="esq-mat">%s<b>&times;%s</b></span>'
                       % (render.link_item(v, show_vnum=False), render._esc(c))
                       for v, c in zip(numbers[0::2], numbers[1::2]))
        windows = crafting_windows_of(row.get("vnum"))
        body.append(("", [
            ("esq-c-key", '<a href="/editsql/crafting/world/%s">#%s</a>'
             % (render._esc(row.get("vnum")), render._esc(row.get("vnum")))),
            ("esq-c-ref", render.link_item(row.get("item_vnum"))),
            ("esq-c-num", render._esc(row.get("count"))),
            ("esq-c-num", render.num(row.get("price"))),
            ("esq-c-num", "%s%%" % render._esc(row.get("chance"))),
            ("esq-c-ref", mats or render._esc(row.get("recipe"))),
            _windows_text(windows) if windows else
            '<span class="esq-dim">%s</span>' % render._esc(T("żadne", "none"))]))
    return render.table([T("Przepis", "Recipe"), T("Wynik", "Result"), T("Ilość", "Count"), "Yang",
                         T("Szansa", "Chance"), T("Składniki", "Ingredients"),
                         T("Okno NPC (paczka)", "NPC window (package)")], body)


# -----------------------------------------------------------------------------
#  ItemShop: which page of the client's window shows an offer
#
#  The client's uiitemshop.py lays its pages out by ranges of the offer's index
#  (ITEMSHOP_CATEGORIES, as clientrootify.py renders it), and the Dragon Marks
#  page takes every offer priced in marks. An index on no page is found only by
#  the window's search. The panel cannot read the client, so this is the list
#  as client 2.0.83 ships it; the English names are english_gui.py's.
# -----------------------------------------------------------------------------
ITEMSHOP_PAGES = (
    (P("Ekwipunek", "Equipment"), 1, 99),
    ("VIP", 101, 113),
    (P("Ślub", "Marriage"), 201, 299),
    (P("Fryzury", "Hairstyles"), 301, 450),
    (P("Ulepszanie", "Upgrading"), 451, 459),
    (P("Zwoje i księgi", "Scrolls and books"), 601, 699),
    (P("Kupony SM", "DC Vouchers"), 901, 905),
)
ITEMSHOP_MARKS_PAGE = P("Smocze Znaki", "Dragon Marks")
# The offers the migrator adds at every start unless the editor removed them
# (port/migratorify.py, itemshop_seed; writes.REMOVED).
ITEMSHOP_SEEDED = (6, 7, 8) + tuple(range(201, 212)) + (617,)


def itemshop_pages_of(index, currency=None):
    try:
        number = int(index)
    except (TypeError, ValueError):
        return []
    pages = [tr(name) for name, low, high in ITEMSHOP_PAGES if low <= number <= high]
    if currency == "DRAGON_MARK":
        pages.append(tr(ITEMSHOP_MARKS_PAGE))
    return pages


def _itemshop_page_list():
    return ", ".join("%s %d–%d" % (tr(name), low, high) for name, low, high in ITEMSHOP_PAGES)


def itemshop_page_note(index, currency=None):
    """For a new offer: the page of the client's window it lands on, or none."""
    pages = itemshop_pages_of(index, currency)
    if pages:
        return ('<div class="esq-note esq-note-info">%s</div>'
                % (T('Pozycja <b>%s</b> będzie w oknie ItemShopu na stronie: %s.',
                     'Position <b>%s</b> shows in the ItemShop window on the page: %s.')
                   % (render._esc(index), render._esc(", ".join(pages)))))
    return ('<div class="esq-note esq-note-warn">%s</div>'
            % (T('Okno ItemShopu w kliencie nie ma strony dla pozycji <b>%s</b> - gracz znajdzie ją '
                 'tylko wyszukiwarką okna. Strony to przedziały numerów: %s (i Smocze Znaki dla '
                 'cen w znakach).',
                 'The client\'s ItemShop window has no page for position <b>%s</b> - a player '
                 'finds it only with the window\'s search. The pages are ranges of numbers: %s '
                 '(and Dragon Marks for prices in marks).')
               % (render._esc(index), render._esc(_itemshop_page_list()))))


def related_itemshop_page(spec, row):
    """For an offer: the page of the client's window that shows it."""
    pages = itemshop_pages_of(row.get("index"), row.get("currency"))
    body = (_kv([(T("Strona okna", "Window page"), render._esc(", ".join(pages)))]) if pages else
            '<p class="esq-empty">%s</p>' % render._esc(T(
                "Żadna strona okna nie obejmuje tego numeru - gracz znajdzie pozycję tylko "
                "wyszukiwarką okna.",
                "No page of the window takes this number - a player finds the offer only with "
                "the window's search.")))
    return render.box(T("Okno ItemShopu", "ItemShop window"), body,
                      T("Strony okna w kliencie 2.0.83: %s.", "The window's pages in client 2.0.83: %s.")
                      % _itemshop_page_list())


def itemshop_broken_note(spec):
    """On the ItemShop's list: the offers the game cannot sell, if any.

    Drip's world holds twelve rows zeroed with 2.2.75's editor (vnum and count
    0). The game core skips such a row now and says so in its syserr, and the
    core of 2.2.75 died at the ItemShop's open - so the list says which rows
    they are and what to do with them."""
    items = _items_table()
    if items is None:
        return ""
    try:
        rows = db.query("SELECT o.%s AS i, o.%s AS v, o.%s AS c FROM %s o LEFT JOIN %s p "
                        "ON p.%s = o.%s WHERE o.%s < 1 OR o.%s < 1 OR o.%s < 1 OR p.%s IS NULL "
                        "ORDER BY o.%s LIMIT 60"
                        % (db.qi("index"), db.qi("vnum"), db.qi("count"),
                           db.qt(spec["db"], spec["table"]), db.qt(items["db"], items["name"]),
                           db.qi("vnum"), db.qi("vnum"), db.qi("index"), db.qi("vnum"),
                           db.qi("count"), db.qi("vnum"), db.qi("index")))
    except Exception:                              # noqa: BLE001 - the list shows anyway
        return ""
    if not rows:
        return ""
    offers = ", ".join(T("%s (przedmiot %s, ilość %s)", "%s (item %s, count %s)")
                       % (row["i"], row["v"], row["c"]) for row in rows)
    return ('<div class="esq-note esq-note-warn">%s</div>'
            % render._esc(T("Tych pozycji gra nie sprzeda: %s. Serwer je pomija (w syserr rdzenia: "
                            "„ITEMSHOP: offer index … skipped”), a rdzeń starszego serwera padał, "
                            "gdy ktoś otworzył ItemShop. Usuń je („Usuń zaznaczone”) albo wpisz "
                            "w nich przedmiot i ilość; pozycje wyzerowane w edytorze cofniesz też "
                            "w Historii zmian.",
                            "The game cannot sell these offers: %s. The server skips them (in the "
                            "core's syserr: “ITEMSHOP: offer index … skipped”), and an older "
                            "server's core went down when somebody opened the ItemShop. Delete "
                            "them (“Delete the selected”) or give them an item and a count; offers "
                            "zeroed in the editor can also be undone in the Change history.")
                          % offers))


def itemshop_delete_note(rows):
    """For a delete: when it takes effect, and that a seeded offer stays gone."""
    seeded = [int(r.get("index")) for r in rows if int(r.get("index") or 0) in ITEMSHOP_SEEDED]
    text = T('Usunięta pozycja znika ze sklepu po restarcie rdzeni („Zastosuj”).',
             'A deleted offer leaves the shop after a restart of the cores (“Apply”).')
    if seeded:
        text += " " + (T('Pozycje %s dodaje sam serwer przy każdym starcie - usunięte tutaj nie '
                         'wrócą (edytor zapisuje usunięcie w common.m2_itemshop_removed, a cofnięcie '
                         'je zdejmuje).',
                         'The server adds offers %s itself at every start - deleted here they do '
                         'not come back (the editor keeps the deletion in common.m2_itemshop_removed, '
                         'and an undo takes it off).')
                       % ", ".join(str(i) for i in seeded))
    return '<div class="esq-note esq-note-info">%s</div>' % render._esc(text)


def itemshop_rows_table(rows):
    """Offers to delete, with what they sell - on the confirmation screen."""
    render.prefetch_names("item", [r.get("vnum") for r in rows])
    body = []
    for row in rows:
        pages = itemshop_pages_of(row.get("index"), row.get("currency"))
        body.append(("", [
            ("esq-c-key", '<a href="/editsql/itemshop/common/%s">%s</a>'
             % (render._esc(row.get("index")), render._esc(row.get("index")))),
            ("esq-c-ref", render.link_item(row.get("vnum"))),
            ("esq-c-num", render._esc(row.get("count"))),
            ("esq-c-num", "%s %s" % (render.num(row.get("price")), render._esc(row.get("currency")))),
            ("esq-c-num", render._esc(row.get("minLevel"))),
            render._esc(", ".join(pages)) if pages else
            '<span class="esq-dim">%s</span>' % render._esc(T("żadna", "none"))]))
    return render.table([T("Pozycja", "Position"), T("Przedmiot", "Item"), T("Ilość", "Count"),
                         T("Cena", "Price"), T("Min. poziom", "Min. level"),
                         T("Strona okna", "Window page")], body)


def related_shop_npc(spec, row):
    """Dla sklepu: NPC, ktory go otwiera."""
    npc = row.get("npc_vnum")
    if not npc:
        return ""
    exists, _name = render.known_name("mob", npc)
    note = ""
    if exists is False:
        note = ('<div class="esq-note esq-note-warn">%s</div>'
                % (T("Nie ma NPC o vnum %s - sklepu nie da się otworzyć w grze.",
                     "There is no NPC with vnum %s - the shop cannot be opened in the game.")
                   % render._esc(npc)))
    return render.box(T("NPC tego sklepu", "This shop's NPC"), _kv([("NPC", render.link_mob(npc))]) + note)


def related_shop_usage(spec, row):
    """Dla przedmiotu: w jakich sklepach jest sprzedawany."""
    vnum = row.get("vnum")
    items = schema.table("world", "shop_item")
    shops = schema.table("world", "shop")
    if items is None or shops is None:
        return ""
    rows = _select(items, ("shop_vnum", "item_vnum", "count"),
                   where="%s=%%s" % db.qi("item_vnum"), params=(vnum,),
                   order=("shop_vnum",), limit=50)
    if not rows:
        return ""
    shop_ids = sorted({r.get("shop_vnum") for r in rows})
    info = {}
    if shop_ids:
        for shop in _select(shops, ("vnum", "name", "npc_vnum"),
                            where="%s IN (%s)" % (db.qi("vnum"), ",".join(["%s"] * len(shop_ids))),
                            params=tuple(shop_ids), limit=len(shop_ids)):
            info[shop["vnum"]] = shop
    render.prefetch_names("mob", [s.get("npc_vnum") for s in info.values()])
    body = []
    for entry in rows:
        shop = info.get(entry.get("shop_vnum")) or {}
        body.append(("", [('<a href="/editsql/shops/world/%s">#%s %s</a>'
                           % (render._esc(entry.get("shop_vnum")), render._esc(entry.get("shop_vnum")),
                              render._esc(shop.get("name") or ""))),
                          ("esq-c-ref", render.link_mob(shop.get("npc_vnum")) if shop.get("npc_vnum") else ""),
                          ("esq-c-num", render._esc(entry.get("count")))]))
    return render.box(T("Sprzedawany w sklepach", "Sold in shops"),
                      render.table([T("Sklep", "Shop"), "NPC", T("Ilość", "Count")], body))


def related_etc_drop(spec, row):
    """Dla przedmiotu: wpis w tabeli dropow mapowych (ktorej silnik nie czyta)."""
    table = schema.table("world", "etc_drop_item")
    if table is None:
        return ""
    rows = _select(table, ("item_vnum", "chance", "comment"),
                   where="%s=%%s" % db.qi("item_vnum"), params=(row.get("vnum"),), limit=10)
    if not rows:
        return ""
    return render.box(T("Drop mapowy (etc_drop_item)", "Map drop (etc_drop_item)"),
                      _kv([(T("Szansa", "Chance"), "%s%% %s" % (render._esc(r.get("chance")),
                                                               render._esc(r.get("comment") or "")))
                           for r in rows]),
                      T("Uwaga: silnik czyta ten drop z pliku etc_drop_item.txt, nie z tej tabeli.",
                        "Note: the engine reads this drop from etc_drop_item.txt, not from this table."))


def related_mob_drop(spec, row):
    """Dla potwora: jego drop specjalny."""
    vnum = row.get("drop_item")
    if not vnum:
        return ""
    return render.box(T("Drop specjalny", "Special drop"), _kv([(T("Przedmiot", "Item"), render.link_item(vnum))]),
                      T("Pełne grupy dropu są w pliku mob_drop_item.txt serwera.",
                        "The full drop groups are in the server's mob_drop_item.txt."))


def related_shop_of_npc(spec, row):
    """Dla NPC: jego sklepy."""
    shops = schema.table("world", "shop")
    if shops is None:
        return ""
    rows = _select(shops, ("vnum", "name", "npc_vnum"),
                   where="%s=%%s" % db.qi("npc_vnum"), params=(row.get("vnum"),), limit=20)
    if not rows:
        return ""
    body = [("", [('<a href="/editsql/shops/world/%s">#%s</a>'
                   % (render._esc(e.get("vnum")), render._esc(e.get("vnum")))),
                  render._esc(e.get("name")),
                  ("esq-c-num", render._esc(_shop_item_count(e.get("vnum"))))]) for e in rows]
    return render.box(T("Sklepy tego NPC", "This NPC's shops"),
                      render.table([T("Sklep", "Shop"), T("Nazwa", "Name"), T("Pozycji", "Items")], body))


def _shop_item_count(shop_vnum):
    table = schema.table("world", "shop_item")
    if table is None:
        return 0
    return int(db.scalar("SELECT COUNT(*) AS n FROM %s WHERE %s=%%s"
                         % (_qt(table), db.qi("shop_vnum")), (shop_vnum,), 0) or 0)


def related_bonus_points(spec, row):
    """Dla bonusu: skad pochodzi jego nazwa."""
    name, pl, source = labels.bonus_label(row.get("apply"))
    if not pl:
        return ('<div class="esq-note esq-note-warn">%s</div>'
                % render._esc(T("Tego bonusu nie ma w world.locale_point - silnik go zna, ale nie "
                                "ma dla niego polskiej nazwy.",
                                "This bonus is not in world.locale_point - the engine knows it, "
                                "but it has no name there.")))
    # The label is the table's own (Polish) text, shown as the table holds it.
    return render.box(T("Nazwa bonusu w grze", "The bonus's name in world.locale_point (Polish)"),
                      _kv([(name, render._esc(pl))]),
                      T("Źródło: world.locale_point.", "Source: world.locale_point."))


# -----------------------------------------------------------------------------
#  Siatka bonusow: co moze sie wylosowac na danym slocie
# -----------------------------------------------------------------------------
SLOT_LABELS = (
    ("weapon", P("Broń", "Weapon")), ("body", P("Zbroja", "Armour")), ("head", P("Hełm", "Helmet")),
    ("shield", P("Tarcza", "Shield")),
    ("wrist", P("Bransoleta", "Bracelet")), ("foots", P("Buty", "Shoes")),
    ("neck", P("Naszyjnik", "Necklace")), ("ear", P("Kolczyki", "Earrings")),
    ("pendant", P("Talizman", "Talisman")), ("glove", P("Rękawice", "Gloves")),
    ("costume_body", P("Kostium (strój)", "Costume (outfit)")),
    ("costume_hair", P("Kostium (fryzura)", "Costume (hairstyle)")),
    ("costume_weapon", P("Kostium (broń)", "Costume (weapon)")),
)


def bonuses_grid(table_name):
    """Kolumna na slot: bonusy z udzialem w losowaniu (waga / suma wag)."""
    table = schema.table("world", table_name)
    if table is None:
        return ""
    available = [name for name, _label in SLOT_LABELS if name in table["by_name"]]
    rows = [safety.decode_row(table, row)
            for row in db.query("SELECT * FROM %s ORDER BY `apply`" % db.qt("world", table_name))]
    columns = []
    for slot in available:
        entries = []
        for row in rows:
            try:
                weight = int(row.get(slot) or 0)
            except (TypeError, ValueError):
                weight = 0
            if weight > 0:
                entries.append((row, weight))
        if not entries:
            continue
        total = sum(w for _r, w in entries)
        top = max(w for _r, w in entries)
        items = []
        for row, weight in sorted(entries, key=lambda item: (-item[1], str(item[0].get("apply")))):
            text, code = labels.bonus_text(row.get("apply"))
            share = 100.0 * weight / total
            key = (row.get("apply"),)
            items.append(
                '<li><a class="esq-bonus-name" href="/editsql/bonuses/world/%s" title="%s">%s</a>'
                '<span class="esq-bonus-bar"><i style="width:%.0f%%"></i></span>'
                '<span class="esq-bonus-share">%.1f%%</span>'
                '<span class="esq-bonus-max" title="%s">%s</span></li>'
                % (render._esc(key[0]), render._esc(code + " · " + text), render._esc(text),
                   100.0 * weight / top, share,
                   render._esc(T("stopnie 1–5: %s", "grades 1–5: %s")
                               % " / ".join(str(row.get("lv%d" % i)) for i in range(1, 6))),
                   render._esc(T("maks. %s", "max. %s") % row.get("lv5"))))
        columns.append('<div class="esq-bonus-col"><h4>%s <span class="esq-dim">%d %s</span></h4>'
                       '<ul class="esq-bonus-list">%s</ul></div>'
                       % (render._esc(dict(SLOT_LABELS).get(slot, slot)), len(entries),
                          i18n.plural(len(entries), ("bonus", "bonusy", "bonusów"),
                                      ("bonus", "bonuses")),
                          "".join(items)))
    if not columns:
        return ""
    return ('<details class="esq-fold" open><summary>%s</summary>'
            '<p class="esq-hint">%s</p>'
            '<div class="esq-bonus-grid">%s</div></details>'
            % (render._esc(T("Rozkład bonusów po slotach", "Bonuses by slot")),
               render._esc(T("Udział = waga bonusu na danym slocie podzielona przez sumę wag "
                             "wszystkich bonusów tego slotu; „maks.” to wartość na 5. stopniu "
                             "(najedź, żeby zobaczyć wszystkie).",
                             "Share = the bonus's weight on the slot divided by the sum of the "
                             "weights of every bonus of that slot; “max.” is the value at "
                             "grade 5 (hover to see them all).")),
               "".join(columns)))


# -----------------------------------------------------------------------------
#  Dzialki i budynki (mapa)
# -----------------------------------------------------------------------------
def lands_map_html(selected_map=None, highlight_land=None):
    """Wybor mapy + wszystkie dzialki tej mapy na podgladzie."""
    table = schema.table("world", "land")
    if table is None:
        return ""
    rows = _select(table, ("id", "map_index", "x", "y", "width", "height", "enable"),
                   order=("map_index", "id"), limit=2000)
    maps = sorted({int(row.get("map_index") or 0) for row in rows})
    current = int(selected_map) if selected_map in maps else (maps[0] if maps else 0)
    on_map = [row for row in rows if int(row.get("map_index") or 0) == current]
    parts = ['<p class="esq-hint">%s</p>'
             % (T('Mapa: <b>%s</b> (%d działek). Inną mapę wybierzesz filtrem „Mapa” nad tabelą.',
                  'Map: <b>%s</b> (%d plots). Pick another map with the "Map" filter above the table.')
                % (render._esc(map_label(current)), len(on_map)))] if maps else []
    if on_map:
        parts.append(map_html(current, others=on_map))
    else:
        parts.append('<p class="esq-empty">%s</p>'
                     % render._esc(T("Na tej mapie nie ma działek.", "There are no plots on this map.")))
    return "".join(parts)


def lands_on_map(map_index, exclude=None):
    table = schema.table("world", "land")
    if table is None:
        return []
    rows = _select(table, ("id", "map_index", "x", "y", "width", "height"),
                   where="%s=%%s" % db.qi("map_index"), params=(map_index,), limit=2000)
    return [r for r in rows if r.get("id") != exclude]


def objects_on_land(land_id):
    """Budynki postawione na dzialce (player.object), ze sprawdzeniem obszaru."""
    table = schema.table("player", "object")
    land = schema.table("world", "land")
    if table is None or land is None:
        return ""
    rows = []
    if "land_id" in table["by_name"]:
        rows = _select(table, ("id", "land_id", "vnum", "map_index", "x", "y"),
                       where="%s=%%s" % db.qi("land_id"), params=(land_id,), order=("id",))
    if not rows:
        return render.box(T("Budynki na tej działce", "Buildings on this plot"),
                          '<p class="esq-empty">%s</p>'
                          % render._esc(T("Na tej działce nie stoi żaden budynek.",
                                          "No building stands on this plot.")))
    area = _select(land, ("id", "x", "y", "width", "height", "map_index"),
                   where="%s=%%s" % db.qi("id"), params=(land_id,), limit=1)
    area = area[0] if area else None
    prototypes = schema.table("world", "object_proto")
    body = []
    for row in rows:
        inside = ""
        if area and None not in (row.get("x"), row.get("y")):
            box = map_bounds_for(area.get("map_index"))
            try:
                ox, oy = (_local(box, row["x"], row["y"]) if box else (row["x"], row["y"]))
                ok = (area["x"] <= ox <= area["x"] + area["width"]
                      and area["y"] <= oy <= area["y"] + area["height"])
                inside = render.status_badge(ok, T("w obrębie działki", "inside the plot"),
                                             T("POZA działką", "OUTSIDE the plot"))
            except (TypeError, KeyError):
                inside = ""
        name = ""
        if prototypes is not None and row.get("vnum"):
            found = _select(prototypes, ("vnum", "name"), where="%s=%%s" % db.qi("vnum"),
                            params=(row.get("vnum"),), limit=1)
            if found:
                name = found[0].get("name") or ""
        body.append(("", [render._esc(row.get("id")), render._esc(row.get("vnum")),
                          render._esc(name), ("esq-c-num", render._esc(row.get("x"))),
                          ("esq-c-num", render._esc(row.get("y"))), inside]))
    return render.box(T("Budynki na tej działce (%d)", "Buildings on this plot (%d)") % len(rows),
                      render.table(["ID", "VNUM", T("Nazwa", "Name"), "X", "Y", ""], body))


# -----------------------------------------------------------------------------
#  Pozycje sklepu - z dodawaniem i usuwaniem po jednym wierszu
# -----------------------------------------------------------------------------
def shop_items_html(shop_vnum):
    table = schema.table("world", "shop_item")
    if table is None:
        return ""
    rows = [safety.decode_row(table, row) for row in db.query(
        "SELECT * FROM %s WHERE %s=%%s ORDER BY %s LIMIT 500"
        % (db.qt(table["db"], table["name"]), db.qi("shop_vnum"), db.qi("item_vnum")),
        (shop_vnum,))]
    render.prefetch_names("item", [r.get("item_vnum") for r in rows])
    action = "/editsql/shops/world/%s" % render._esc(shop_vnum)
    body = []
    for row in rows:
        body.append(("", [
            ("esq-c-ref", render.link_item(row["item_vnum"])),
            ("esq-c-num", render._esc(row["count"])),
            ("esq-c-act", '<form method="post" action="%s" class="esq-inline-form">%s'
                          '<input type="hidden" name="action" value="child_delete" />'
                          '<input type="hidden" name="item_vnum" value="%s" />'
                          '<input type="hidden" name="count" value="%s" />'
                          '<button class="esq-btn esq-btn-small esq-btn-danger" type="submit" '
                          'data-confirm="%s">%s</button></form>'
                          % (action, render.csrf_input(), render._esc(row["item_vnum"]),
                             render._esc(row["count"]),
                             render._esc(T("Usunąć tę pozycję ze sklepu?",
                                           "Remove this item from the shop?")),
                             render._esc(T("Usuń", "Remove"))))]))
    add_form = ('<form method="post" action="%s" class="esq-toolbar esq-add-form">%s'
                '<input type="hidden" name="action" value="child_add" />'
                '<div class="esq-tb-field"><label for="add_item">%s</label>'
                '<input type="number" min="1" id="add_item" name="item_vnum" required '
                'data-esq-lookup="item" /></div>'
                '<div class="esq-tb-field esq-tb-narrow"><label for="add_count">%s</label>'
                '<input type="number" min="1" id="add_count" name="count" value="1" required /></div>'
                '<div class="esq-tb-buttons"><button class="esq-btn esq-btn-small esq-btn-go" '
                'type="submit">%s</button></div>'
                '<span class="esq-lookup" id="add_item_look"></span></form>'
                % (action, render.csrf_input(), render._esc(T("VNUM przedmiotu", "Item VNUM")),
                   render._esc(T("Ilość", "Count")), render._esc(T("Dodaj pozycję", "Add item"))))
    return render.box(T("Pozycje sklepu (%d)", "Shop items (%d)") % len(rows),
                      render.table([T("Przedmiot", "Item"), T("Ilość", "Count"), ""], body,
                                   empty=T("Sklep jest pusty.", "The shop is empty.")) + add_form,
                      T("Każde dodanie i usunięcie to jeden wiersz w world.shop_item i jeden wpis "
                        "w historii.",
                        "Every addition and removal is one row of world.shop_item and one entry "
                        "in the history."))
