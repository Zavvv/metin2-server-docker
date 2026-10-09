# =============================================================================
#  /market -- the market preview, a sibling of admin_panel.py (Iwakura's
#  Patch 12, point 1, "PANEL PODGLAD RYNKU - WERSJA EKSPERYMENTALNA").
#
#  Loaded as the database editor is: admin_panel.py imports this package under
#  a name of its own and calls init(globals()) once, so the routes, the login
#  and the CSRF check are the panel's own - its login_required on the page, its
#  global before_request on every POST - and the package itself imports no
#  Flask (tests/market_preview_test.py loads it bare).
#
#      GET  /market                  the page (login_required)
#      GET  /market/api/offers       a page of offers, the counts, the chart
#      POST /market/api/tp           the TP order (CSRF), a MARKETTP 'await' row
#      GET  /market/api/tp/<id>      that order's answer
#      GET  /market/api/tp_history   the last twenty orders
#      POST /market/settings         the TP's fare (CSRF)
#
#  rules.py is what a request means, snapshot.py the data, texts.py the words,
#  page.py the page; sheet.py is rendered from the overlay's price and tier
#  tables. The core's side of the TP is playerbot_market_tp.cpp.
# =============================================================================

import json
import os
import re
import threading
import time

from . import page, rules, sheet, snapshot, texts  # noqa: F401

_registered = {"done": False}
_state = {"ns": None, "store": None, "limiter": rules.RateLimiter(), "icons": None, "persons": (0.0, []),
          "lock": threading.Lock()}

# Map names of the maps a stand stands on: the first villages, where "a bot's
# stand stands" (market.md), and the second ones; any other by its number.
MAP_NAMES = {1: "Yongan", 21: "Joan", 41: "Pyongmoo", 3: "Jayang", 23: "Bokjung", 43: "Bakra"}
SETTINGS_FILE = "market_preview.json"
HISTORY_FILE = "market_history.sqlite"


class _Ns(object):
    """admin_panel.py's names, looked up when used (the editor's pattern)."""

    def __init__(self, module):
        self._m = module if isinstance(module, dict) else vars(module)

    def __getattr__(self, name):
        try:
            return self._m[name]
        except KeyError:
            raise AttributeError(name)

    def get(self, name, default=None):
        return self._m.get(name, default)


def ns():
    return _state["ns"]


def store():
    return _state["store"]


def enabled():
    return bool(ns() is not None and ns().get("ENGINE_MT2009"))


def lang():
    try:
        return "pl" if ns().lang() == "pl" else "en"
    except Exception:                                # noqa: BLE001 - outside a request
        return "pl"


def say(key, **fields):
    text = texts.text(key, lang())
    for name, value in fields.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def _json(payload, status=200):
    from flask import Response
    return Response(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), status=status,
                    mimetype="application/json")


def _authorized():
    panel = ns()
    try:
        return bool(panel.session.get("auth") or panel.local_open())
    except Exception:                                # noqa: BLE001
        return False


def _gate():
    """None when the request may go on; the JSON answer that refuses it."""
    if not enabled():
        return _json({"ok": False, "error": "not_here", "message": say("not_here")}, 404)
    if not _authorized():
        return _json({"ok": False, "error": "login", "message": say("login")}, 401)
    panel = ns()
    try:
        key = panel.session.get("_csrf") or panel.request.remote_addr or "?"
    except Exception:                                # noqa: BLE001
        key = "?"
    with _state["lock"]:                            # the panel serves from several threads
        allowed = _state["limiter"].allow(key)
    if not allowed:
        return _json({"ok": False, "error": "rate", "message": say("too_fast")}, 429)
    return None


# -----------------------------------------------------------------------------
#  What an offer row says
# -----------------------------------------------------------------------------
def _icons():
    if _state["icons"] is None:
        icons = {}
        try:
            path = os.path.join(ns().app.static_folder, "item_icons.json")
            with open(path, encoding="utf-8") as fh:
                icons = json.load(fh)
        except Exception:                            # noqa: BLE001 - no icon set: the placeholder draws
            icons = {}
        _state["icons"] = icons
    return _state["icons"]


def icon_url(vnum):
    """The client's own icon (files/static/icons, the live map's set) of the
    vnum, else of its +0, else none - the page draws a neutral square."""
    icons = _icons()
    for key in (vnum, vnum - vnum % 10):
        name = icons.get(str(int(key)))
        if name and re.match(r"^[A-Za-z0-9_.-]{1,64}$", name):
            return "/static/icons/" + name
    return ""


def item_name(vnum, socket0, language):
    panel = ns()
    try:
        return panel.item_full_name(int(vnum), int(socket0 or 0), language)
    except Exception:                                # noqa: BLE001
        try:
            return panel.localized_item_name(int(vnum), language)
        except Exception:                            # noqa: BLE001
            return "#%d" % int(vnum)


def _names_for_search(vnum, socket0):
    """A kind's Polish and English names, which the search reads both of."""
    return item_name(vnum, socket0, "pl"), item_name(vnum, socket0, "en")


_PLACEHOLDER = re.compile(r"\s*[:+]?\s*[+-]?%[-+ ]?\d*(?:\.\d+)?[df](?:%%)?")


def apply_label(point, value=None, language="pl"):
    """A bonus line in the reader's language, as the live map writes it (the
    panel's APPLY_TEXTS through apply_key: mt2009 stores POINT numbers); the
    line's name alone when `value` is None."""
    panel = ns()
    entry = None
    try:
        entry = panel.APPLY_TEXTS.get(panel.apply_key(int(point)))
    except Exception:                                # noqa: BLE001
        entry = None
    template = None
    if entry:
        template = entry[1].get(language) or entry[1].get("en")
    if not template:
        row = sheet.BONUS_TIERS.get(int(point))
        name = row[4] if row else "Bonus #%d" % int(point)
        return name if value is None else "%s %s" % (name, value)
    if value is None:
        return _PLACEHOLDER.sub("", template).strip(" :+")
    try:
        return template % value if "%" in template else template
    except (TypeError, ValueError):
        return "%s %s" % (_PLACEHOLDER.sub("", template).strip(" :+"), value)


def _base_lines(proto, language):
    """A piece's own lines for the tooltip: attack, defence, the proto's
    applies (the live map's tooltip reads the same fields)."""
    if proto is None:
        return []
    v = proto.values
    out = []
    if proto.type == rules.ITEM_WEAPON:
        if v[3] or v[4]:
            out.append(say("tt_attack", a=v[3] + v[5], b=v[4] + v[5]))
        if v[1] or v[2]:
            out.append(say("tt_magic", a=v[1] + v[5], b=v[2] + v[5]))
        if v[0] > 0:
            out.append(say("tt_speed", n=v[0]))
    elif proto.type == rules.ITEM_ARMOR:
        defence = {0: v[1] + v[5] * 2, 1: v[1] + v[5], 2: v[1] + v[5] * 2, 4: v[1] + v[5]}.get(proto.subtype, 0)
        if defence > 0:
            out.append(say("tt_defence", n=defence))
    for point, value in proto.applies:
        if point and value:
            out.append(apply_label(point, value, language))
    return out


def render_row(snap, row, language):
    proto = snap.protos.get(row["vnum"])
    socket0 = snap.variants.get((row["vnum"], row["var"]), 0)
    name, plus = rules.split_plus(item_name(row["vnum"], socket0, language))
    plus = row["plus"] if row["plus"] >= 0 else plus
    shop = snap.shops.get(row["owner"], {})
    classes = [i for i, bit in enumerate(rules.CLASS_BITS) if row["cls"] & bit]
    bonuses = []
    for k in range(7):
        point, value = row["a%d" % k], row["v%d" % k]
        if not point or not value or point in snapshot.DAMAGE_POINTS:
            continue
        pve, pvp = rules.tier_pair(point)
        bonuses.append({"p": point, "v": value, "t": apply_label(point, value, language),
                        "max": rules.is_max_line(point, value, snap.tops), "pve": pve, "pvp": pvp})
    stones = [{"v": s, "n": item_name(s, 0, language)} for s in (row["s0"], row["s1"], row["s2"]) if s]
    deal = row["bkey"] if row["bkey"] > rules.NO_REFERENCE_KEY else None
    map_name = MAP_NAMES.get(shop.get("map", 0)) or say("map_n", n=shop.get("map", 0))
    return {
        "id": row["id"], "vnum": row["vnum"], "var": row["var"], "name": name, "plus": plus,
        "cnt": row["cnt"], "price": row["price"], "unit": round(row["unit"], 2), "lvl": row["lvl"],
        "classes": classes, "cls_all": row["cls"] == rules.ALL_CLASSES, "owner": row["owner"],
        "seller": shop.get("seller") or "", "bot": bool(row["bot"]), "emp": row["emp"],
        "shop_name": shop.get("name") or "", "ch": row["ch"], "map": row["map"],
        "where": say("map_ch", map=map_name, ch=row["ch"]), "running": bool(row["running"]),
        "ref": round(row["ref"] or 0), "deal": deal, "slip": bool(row["slip"]), "icon": icon_url(row["vnum"]),
        "bonuses": bonuses, "avg": row["avg"], "skl": row["skl"], "stones": stones,
        "base": _base_lines(proto, language),
    }


def _persons():
    """The person's own characters (DbSource.persons), a minute at a time."""
    at, rows = _state["persons"]
    if time.time() - at < 60:
        return rows
    try:
        rows = store().source.persons()
    except Exception:                                # noqa: BLE001 - the page works without them
        rows = []
    _state["persons"] = (time.time(), rows)
    return rows


def _counts_json(counts):
    out = {"all": sum(counts.values()), "cats": {}}
    for key, cid, _pl, _en, subs in rules.CATEGORIES:
        entry = {"n": sum(n for (c, _s), n in counts.items() if c == cid), "subs": {}}
        for skey, sid, _spl, _sen in subs:
            entry["subs"][skey] = counts.get((cid, sid), 0)
        out["cats"][key] = entry
    return out


# -----------------------------------------------------------------------------
#  Routes
# -----------------------------------------------------------------------------
def _settings_path():
    return os.path.join(str(ns().get("PANEL_DIR") or "."), SETTINGS_FILE)


def read_settings():
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        cost = int(data.get("tp_cost", 0))
        return {"tp_cost": cost if 0 <= cost <= rules.PRICE_MAX else 0}
    except Exception:                                # noqa: BLE001 - absent: the switch is off
        return {"tp_cost": 0}


def _page():
    panel = ns()
    language = lang()
    snap = store().current if store() else None
    bonus_points = snap.bonus_points if snap else tuple(sorted(sheet.BONUS_TIERS))
    bonuses = sorted(({"p": p, "t": apply_label(p, None, language)} for p in bonus_points),
                     key=lambda b: rules.normalize(b["t"]))
    data = {
        "lang": language, "texts": texts.for_language(language), "csrf": panel.csrf_token(),
        "defaults": rules.DEFAULTS, "persons": _persons() if enabled() else [],
        "bonuses": bonuses, "deal_badge": rules.DEAL_BADGE_PCT, "deal_suspect": rules.DEAL_SUSPECT_PCT,
        "categories": [{"key": key, "name": pl if language == "pl" else en,
                        "subs": [{"key": sk, "name": spl if language == "pl" else sen} for sk, _sid, spl, sen in subs]}
                       for key, _cid, pl, en, subs in rules.CATEGORIES],
    }
    # The panel's frame with the page's own title; the script is in the body
    # inside {% raw %}, as JavaScript and no template.
    template = panel.BASE.replace("<title>{{brand}}</title>", "<title>{{ T.doc_title }}</title>") \
        .replace("__BODY__", page.body())
    # r40250 has no offline shops: no snapshot thread there, or it would fail
    # a build every quarter of an hour for as long as the panel runs.
    if store() and enabled():
        store().viewed()
        store().start()
    return panel.render_template_string(template, T=texts.for_language(language), enabled=enabled(), data=data,
                                        persons=data["persons"], sorts=list(rules.SORTS), class_keys=rules.CLASS_KEYS,
                                        tp_cost=read_settings()["tp_cost"],
                                        stones=[{"v": v, "n": item_name(v, 0, language)} for v in (snap.stones if snap else ())])


def _api_offers():
    refused = _gate()
    if refused is not None:
        return refused
    panel = ns()
    started = time.time()
    st = store()
    st.viewed()
    st.start()
    if panel.request.args.get("refresh") == "1":
        st.request_refresh()
    snap = st.current
    if snap is None:
        st.request_refresh()
        return _json({"ok": True, "generated_at": 0, "building": True, "error": st.last_error, "rows": [],
                      "total": 0, "counts": None, "page": 1, "pages": 1, "per": rules.DEFAULT_PER, "errors": {}})
    my_classes = {p["pid"]: p["cls"] for p in _persons()}
    f, errors = rules.parse_filters(panel.request.args, snap.bonus_points, my_classes)
    rows, total, counts, page_no, pages = snap.page(f)
    language = lang()
    out = {
        "ok": True, "generated_at": int(snap.generated_at),
        "generated_text": time.strftime("%H:%M:%S", time.localtime(snap.generated_at)),
        "building": st.building, "error": st.last_error, "total": total, "page": page_no, "pages": pages,
        "per": f["per"], "counts": _counts_json(counts), "errors": errors,
        "rows": [render_row(snap, r, language) for r in rows],
    }
    if "shop" in f:
        shop = snap.shops.get(f["shop"], {})
        out["shop"] = {"label": "%s · %s" % (shop.get("seller") or "#%d" % f["shop"], shop.get("name") or "")}
    if "vnum" in f:
        socket0 = f.get("var", snap.variants.get((f["vnum"], 0), 0))
        name = item_name(f["vnum"], socket0, language)
        out["item"] = name
        plus = rules.split_plus(name)[1]
        proto = snap.protos.get(f["vnum"])
        plus = proto.plus if proto is not None else plus
        try:
            points = st.history.chart(f["vnum"], plus, f.get("var", 0))
        except Exception:                            # noqa: BLE001
            points = []
        out["chart"] = {"name": name, "points": [[t, round(m, 2), round(lo, 2), n] for t, m, lo, n in points]}
    out["ms"] = int((time.time() - started) * 1000)
    return _json(out)


def _tp_message(status, owner, cost=0, seconds=0):
    snap = store().current if store() else None
    shop = snap.shops.get(int(owner or 0), {}) if snap else {}
    key = rules.TP_STATUS_KEYS.get(status, "tp_failed")
    return say(key, shop=(shop.get("name") or "#%s" % owner), ch=shop.get("ch", "?"), cost=rules.format_price(cost),
               n=max(1, int(seconds)))


def _api_tp():
    refused = _gate()
    if refused is not None:
        return refused
    panel = ns()
    form = panel.request.form
    try:
        pid = int(form.get("pid", ""))
        owner = int(form.get("shop", ""))
    except (TypeError, ValueError):
        return _json({"ok": False, "status": "bad_args", "message": say("tp_bad_args")}, 400)
    person = next((p for p in store().source.persons() if p["pid"] == pid), None)
    if person is None:
        return _json({"ok": False, "status": "not_person", "message": say("tp_not_person")})
    snap = store().current
    shop = snap.shops.get(owner) if snap else None
    if shop is None:
        return _json({"ok": False, "status": "no_shop", "message": say("tp_no_shop")})
    if not shop.get("running"):
        return _json({"ok": False, "status": "shop_closed", "message": say("tp_shop_closed")})
    cost = read_settings()["tp_cost"]
    name = person["name"]
    with panel.db() as c, c.cursor() as cur:
        # Thirty seconds between two teleports of one character: the core holds
        # it too, by its own clock; here, so a click is answered at once.
        cur.execute("SELECT TIMESTAMPDIFF(SECOND, created, NOW()) AS age FROM player.web_admin_queue "
                    "WHERE player_name = %s AND cmd = 'MARKETTP' AND (status = 'done' OR status LIKE 'w%%') "
                    "AND created > NOW() - INTERVAL %s SECOND ORDER BY id DESC LIMIT 1",
                    (name, rules.TP_COOLDOWN_SECONDS))
        recent = cur.fetchone()
        if recent:
            wait = rules.TP_COOLDOWN_SECONDS - int(recent.get("age") or 0)
            return _json({"ok": False, "status": "cooldown", "message": say("tp_cooldown", n=max(1, wait))})
        # One order a character: a newer click withdraws one still waiting.
        cur.execute("UPDATE player.web_admin_queue SET status = 'cancelled' WHERE player_name = %s "
                    "AND cmd = 'MARKETTP' AND status = 'await'", (name,))
        cur.execute("INSERT INTO player.web_admin_queue (player_name, cmd, arg1, arg2, status) "
                    "VALUES (%s, 'MARKETTP', %s, %s, 'await')", (name, str(owner), str(int(cost))))
        qid = cur.lastrowid
    try:
        panel.app.logger.info("market tp queued id=%s pid=%s name=%s shop=%s ch=%s cost=%s",
                              qid, pid, name, owner, shop.get("ch"), cost)
    except Exception:                                # noqa: BLE001
        pass
    return _json({"ok": True, "id": qid, "shop": shop.get("name"), "ch": shop.get("ch")})


def _api_tp_status(qid):
    refused = _gate()
    if refused is not None:
        return refused
    panel = ns()
    with panel.db() as c, c.cursor() as cur:
        cur.execute("SELECT status, arg1, arg2, TIMESTAMPDIFF(SECOND, created, NOW()) AS age "
                    "FROM player.web_admin_queue WHERE id = %s AND cmd = 'MARKETTP'", (int(qid),))
        row = cur.fetchone()
        if row is None:
            return _json({"ok": False, "final": True, "status": "bad_args", "message": say("tp_bad_args")}, 404)
        status = str(row.get("status") or "")
        # Nobody answered in fifteen seconds: the character is not in the game
        # (or no core could serve it). Withdrawn here, conditionally, so it can
        # never fire later - the core serves no row past twenty seconds either.
        if status == "await" and int(row.get("age") or 0) >= rules.TP_WAIT_SECONDS:
            cur.execute("UPDATE player.web_admin_queue SET status = 'offline' WHERE id = %s AND status = 'await'",
                        (int(qid),))
            if cur.rowcount:
                status = "offline"
            else:
                cur.execute("SELECT status FROM player.web_admin_queue WHERE id = %s", (int(qid),))
                again = cur.fetchone()
                status = str((again or {}).get("status") or "offline")
    if status not in rules.TP_FINAL:
        return _json({"ok": True, "final": False, "status": "waiting"})
    return _json({"ok": status == "done", "final": True, "status": status,
                  "message": _tp_message(status, row.get("arg1"), int(row.get("arg2") or 0) if str(
                      row.get("arg2") or "").isdigit() else 0, rules.TP_COOLDOWN_SECONDS)})


def _api_tp_history():
    refused = _gate()
    if refused is not None:
        return refused
    panel = ns()
    out = []
    try:
        with panel.db() as c, c.cursor() as cur:
            cur.execute("SELECT id, created, player_name, arg1, status FROM player.web_admin_queue "
                        "WHERE cmd = 'MARKETTP' ORDER BY id DESC LIMIT 20")
            rows = cur.fetchall()
    except Exception:                                # noqa: BLE001
        rows = []
    snap = store().current
    for r in rows:
        status = str(r.get("status") or "")
        owner = int(r.get("arg1") or 0) if str(r.get("arg1") or "").isdigit() else 0
        shop = snap.shops.get(owner, {}) if snap else {}
        created = r.get("created")
        out.append({"when": created.strftime("%d.%m %H:%M:%S") if hasattr(created, "strftime") else str(created),
                    "who": snapshot._text(r.get("player_name")),
                    "shop": "%s · %s" % (shop.get("seller") or "#%d" % owner, shop.get("name") or ""),
                    "result": _tp_message(status, owner) if status in rules.TP_FINAL else say("tp_waiting_word")})
    return _json({"ok": True, "rows": out})


def _settings():
    refused = _gate()
    if refused is not None:
        return refused
    raw = ns().request.form.get("tp_cost", "")
    try:
        cost = rules.parse_price(raw) or 0
    except ValueError:
        return _json({"ok": False, "message": say("bad_value")}, 400)
    if cost > rules.TP_COST_MAX:
        return _json({"ok": False, "message": say("bad_value")}, 400)
    path = _settings_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"tp_cost": int(cost)}, fh)
    os.replace(tmp, path)
    return _json({"ok": True, "message": say("tp_cost_saved", cost=rules.format_price(cost))})


# -----------------------------------------------------------------------------
#  Registration
# -----------------------------------------------------------------------------
def _home_texts(panel):
    """The home page's card, in the panel's own table of four languages: a
    German or Turkish reader reads it in English, as the editor's card."""
    def four(key):
        pl, en = texts.TEXTS[key]
        return {"pl": pl, "en": en, "de": en, "tr": en}
    panel.T.update({"mk_card_title": four("title"), "mk_experimental": four("experimental"),
                    "mk_card_hint": four("card_hint"), "mk_card_open": four("card_open")})


def init(module, history_path=None, source=None):
    """Called once from admin_panel.py: market_preview.init(globals())."""
    if _registered["done"]:
        raise RuntimeError("market preview already installed")
    panel = _Ns(module)
    _state["ns"] = panel
    path = history_path or os.environ.get("M2PANEL_MARKET_HISTORY", "").strip() or \
        os.path.join(str(panel.get("PANEL_DIR") or "."), HISTORY_FILE)
    _state["store"] = snapshot.Store(panel, path, source=source, names=_names_for_search)
    _home_texts(panel)
    app = panel.app
    app.add_url_rule("/market", "market_preview", panel.login_required(_page), methods=["GET"])
    app.add_url_rule("/market/api/offers", "market_api_offers", _api_offers, methods=["GET"])
    app.add_url_rule("/market/api/tp", "market_api_tp", _api_tp, methods=["POST"])
    app.add_url_rule("/market/api/tp/<int:qid>", "market_api_tp_status", _api_tp_status, methods=["GET"])
    app.add_url_rule("/market/api/tp_history", "market_api_tp_history", _api_tp_history, methods=["GET"])
    app.add_url_rule("/market/settings", "market_settings", _settings, methods=["POST"])

    @app.context_processor
    def _market_context():
        return {"market_ready": enabled()}

    _registered["done"] = True
    return app
