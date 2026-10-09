# =============================================================================
#  /editsql -- znaczenie kolumn.
#
#  Metamodel (schema.py) wie, JAKIEGO typu jest kolumna. Tutaj jest to, czego
#  information_schema nie powie: co kolumna ZNACZY dla gry. Dzieki temu:
#
#    * etykiety pol i naglowki sa po polsku ("Maks. PŻ"), a nazwa kolumny stoi
#      obok drobnym drukiem (max_hp) - nic nie jest ukryte,
#    * vnum przedmiotu jest linkiem do PRZEDMIOTU, vnum potwora - do POTWORA
#      (wczesniej kazda kolumna "vnum" byla traktowana jak przedmiot, wiec na
#      liscie potworow VNUM 101 pokazywal ikone miecza i link do broni 101),
#    * typ, ranga, krolestwo i bonus to listy wyboru z nazwami, a maski bitowe
#      (flag/antiflag/wearflag) maja rozpisane bity pod polem.
#
#  Kolumna, ktorej tu nie ma, dalej dziala - dostaje po prostu swoja nazwe.
#
#  Every label is a pair, P(Polish, English) (i18n.py): info() and label()
#  hand back the reader's language.
# =============================================================================

from . import labels
from .i18n import P, T, tr

# Rodzaje pol (kind):
#   item     - vnum przedmiotu (podglad nazwy + ikona, link)
#   mob      - vnum potwora/NPC
#   itemtype, itemsubtype, rank, mobtype, empire, limittype, apply - listy wyboru
#   flags:<nazwa> - maska bitowa z rozpisaniem
#   pct      - procent (tylko opis)

_ITEM = {
    "vnum": ("VNUM", None), "name": (P("Nazwa wewnętrzna (klient)", "Internal name (client)"), None),
    "locale_name": (P("Nazwa w grze", "Name in the game"), None),
    "type": (P("Typ", "Type"), "itemtype"),
    "subtype": (P("Podtyp", "Subtype"), "itemsubtype"),
    "stack": (P("Maks. stos", "Max. stack"), None),
    "weight": (P("Waga", "Weight"), None),
    "size": (P("Rozmiar (pola w ekwipunku)", "Size (inventory cells)"), None),
    "antiflag": (P("Zakazy (antiflag)", "Restrictions (antiflag)"), "flags:anti"),
    "flag": (P("Flagi (flag)", "Flags (flag)"), "flags:item"),
    "wearflag": (P("Miejsce noszenia (wearflag)", "Where it is worn (wearflag)"), "flags:wear"),
    "immuneflag": (P("Odporności przedmiotu", "Item immunities"), None),
    "gold": (P("Cena kupna w sklepie", "Buying price in a shop"), None),
    "shop_buy_price": (P("Cena skupu przez NPC", "Price an NPC pays"), None),
    "refined_vnum": (P("Przedmiot po ulepszeniu", "Item after refining"), "item"),
    "refine_set": (P("Przepis ulepszenia", "Refining recipe"), "refine"),
    "magic_pct": (P("Szansa na magiczny (%)", "Chance of magic (%)"), None),
    "specular": (P("Połysk", "Shine"), None),
    "socket_pct": (P("Szansa na gniazda (%)", "Chance of sockets (%)"), None),
    "addon_type": (P("Dodatkowy bonus (addon)", "Extra bonus (addon)"), None),
    "limittype0": (P("Wymaganie 1", "Requirement 1"), "limittype"),
    "limitvalue0": (P("Wartość wymagania 1", "Requirement 1 value"), None),
    "limittype1": (P("Wymaganie 2", "Requirement 2"), "limittype"),
    "limitvalue1": (P("Wartość wymagania 2", "Requirement 2 value"), None),
    "applytype0": (P("Bonus 1", "Bonus 1"), "apply"),
    "applyvalue0": (P("Wartość bonusu 1", "Bonus 1 value"), None),
    "applytype1": (P("Bonus 2", "Bonus 2"), "apply"),
    "applyvalue1": (P("Wartość bonusu 2", "Bonus 2 value"), None),
    "applytype2": (P("Bonus 3", "Bonus 3"), "apply"),
    "applyvalue2": (P("Wartość bonusu 3", "Bonus 3 value"), None),
}
for _i in range(6):
    _ITEM["value%d" % _i] = (P("Wartość %d" % _i, "Value %d" % _i), None)
    _ITEM["socket%d" % _i] = (P("Gniazdo %d" % (_i + 1), "Socket %d" % (_i + 1)), None)

_MOB = {
    "vnum": ("VNUM", None), "name": (P("Nazwa wewnętrzna (klient)", "Internal name (client)"), None),
    "locale_name": (P("Nazwa w grze", "Name in the game"), None),
    "rank": (P("Ranga", "Rank"), "rank"), "type": (P("Typ", "Type"), "mobtype"),
    "battle_type": (P("Typ walki", "Battle type"), None), "level": (P("Poziom", "Level"), None),
    "size": (P("Rozmiar", "Size"), None),
    "ai_flag": (P("Zachowanie (ai_flag)", "Behaviour (ai_flag)"), None),
    "mount_capacity": (P("Udźwig wierzchowca", "Mount capacity"), None),
    "setRaceFlag": (P("Rasa i żywioł", "Race and element"), None),
    "setImmuneFlag": (P("Odporności na efekty", "Effect immunities"), None),
    "empire": (P("Królestwo", "Kingdom"), "empire"), "folder": (P("Folder modelu", "Model folder"), None),
    "on_click": (P("Akcja po kliknięciu", "Action on click"), None),
    "st": (P("Siła (ST)", "Strength (ST)"), None),
    "dx": (P("Zręczność (DX)", "Dexterity (DX)"), None),
    "ht": (P("Witalność (HT)", "Vitality (HT)"), None),
    "iq": (P("Inteligencja (IQ)", "Intelligence (IQ)"), None),
    "damage_min": (P("Obrażenia min.", "Min. damage"), None),
    "damage_max": (P("Obrażenia maks.", "Max. damage"), None), "max_hp": (P("Maks. PŻ", "Max. HP"), None),
    "regen_cycle": (P("Cykl regeneracji", "Regeneration cycle"), None),
    "regen_percent": (P("Regeneracja (%)", "Regeneration (%)"), None),
    "gold_min": (P("Yang min.", "Min. yang"), None), "gold_max": (P("Yang maks.", "Max. yang"), None),
    "exp": (P("Doświadczenie", "Experience"), None), "def": (P("Obrona", "Defence"), None),
    "attack_speed": (P("Szybkość ataku", "Attack speed"), None),
    "move_speed": (P("Szybkość ruchu", "Movement speed"), None),
    "aggressive_hp_pct": (P("Agresja poniżej PŻ (%)", "Aggressive below HP (%)"), None),
    "aggressive_sight": (P("Zasięg wzroku agresji", "Aggression sight range"), None),
    "attack_range": (P("Zasięg ataku", "Attack range"), None),
    "drop_item": (P("Drop specjalny", "Special drop"), "item"),
    "resurrection_vnum": (P("Odradza się jako", "Comes back as"), "mob"),
    "polymorph_item": (P("Przedmiot polimorfii", "Polymorph item"), "item"),
    "enchant_curse": (P("Klątwa", "Curse"), None),
    "enchant_slow": (P("Spowolnienie", "Slow"), None), "enchant_poison": (P("Trucizna", "Poison"), None),
    "enchant_stun": (P("Ogłuszenie", "Stun"), None),
    "enchant_critical": (P("Cios krytyczny", "Critical hit"), None),
    "enchant_penetrate": (P("Przeszywające uderzenie", "Piercing hit"), None),
    "resist_sword": (P("Odp. na miecze", "Res. to swords"), None),
    "resist_twohand": (P("Odp. na broń dwuręczną", "Res. to two-handed weapons"), None),
    "resist_dagger": (P("Odp. na sztylety", "Res. to daggers"), None),
    "resist_bell": (P("Odp. na dzwony", "Res. to bells"), None),
    "resist_fan": (P("Odp. na wachlarze", "Res. to fans"), None),
    "resist_bow": (P("Odp. na łuki", "Res. to bows"), None),
    "resist_fire": (P("Odp. na ogień", "Res. to fire"), None),
    "resist_elect": (P("Odp. na błyskawice", "Res. to lightning"), None),
    "resist_magic": (P("Odp. na magię", "Res. to magic"), None),
    "resist_wind": (P("Odp. na wiatr", "Res. to wind"), None),
    "resist_poison": (P("Odp. na truciznę", "Res. to poison"), None),
    "dam_multiply": (P("Mnożnik obrażeń", "Damage multiplier"), None),
    "summon": (P("Przywołuje (vnum)", "Summons (vnum)"), "mob"),
    "drain_sp": (P("Wysysanie PE", "SP drain"), None),
    "mob_color": (P("Kolor", "Colour"), None),
    "polymorph_item_vnum": (P("Przedmiot polimorfii", "Polymorph item"), "item"),
    "sp_berserk": (P("Szał", "Berserk"), None), "sp_stoneskin": (P("Kamienna skóra", "Stone skin"), None),
    "sp_godspeed": (P("Boska szybkość", "Godspeed"), None),
    "sp_deathblow": (P("Śmiertelny cios", "Deathblow"), None),
    "sp_revive": (P("Odrodzenie", "Revive"), None), "fraction": (P("Frakcja", "Faction"), None),
}
for _i in range(5):
    _MOB["skill_vnum%d" % _i] = (P("Umiejętność %d" % (_i + 1), "Skill %d" % (_i + 1)), None)
    _MOB["skill_level%d" % _i] = (P("Poziom umiejętności %d" % (_i + 1), "Skill %d level" % (_i + 1)), None)
_MOB["enchant_fire"] = (P("Podpalenie", "Burning"), None)
_MOB["enchant_root"] = (P("Unieruchomienie", "Root"), None)

_REFINE = {"id": (P("Numer przepisu", "Recipe number"), None),
           "cost": (P("Koszt (yang)", "Cost (yang)"), None),
           "prob": (P("Szansa powodzenia (%)", "Chance of success (%)"), None),
           "src_vnum": (P("Przedmiot źródłowy", "Source item"), "item"),
           "result_vnum": (P("Przedmiot wynikowy", "Result item"), "item")}
for _i in range(5):
    _REFINE["vnum%d" % _i] = (P("Materiał %d" % (_i + 1), "Material %d" % (_i + 1)), "item")
    _REFINE["count%d" % _i] = (P("Ilość %d" % (_i + 1), "Count %d" % (_i + 1)), None)

_ATTR = {"apply": ("Bonus", None), "prob": (P("Szansa (waga)", "Chance (weight)"), None),
         "lv1": (P("Stopień 1", "Grade 1"), None), "lv2": (P("Stopień 2", "Grade 2"), None),
         "lv3": (P("Stopień 3", "Grade 3"), None),
         "lv4": (P("Stopień 4", "Grade 4"), None), "lv5": (P("Stopień 5", "Grade 5"), None),
         "weapon": (P("Broń", "Weapon"), None), "body": (P("Zbroja", "Armour"), None),
         "wrist": (P("Bransoleta", "Bracelet"), None),
         "foots": (P("Buty", "Shoes"), None), "neck": (P("Naszyjnik", "Necklace"), None),
         "head": (P("Hełm", "Helmet"), None),
         "shield": (P("Tarcza", "Shield"), None), "ear": (P("Kolczyki", "Earrings"), None),
         "costume_body": (P("Kostium (strój)", "Costume (outfit)"), None),
         "costume_hair": (P("Kostium (fryzura)", "Costume (hairstyle)"), None),
         "costume_weapon": (P("Kostium (broń)", "Costume (weapon)"), None),
         "pendant": (P("Talizman", "Talisman"), None),
         "glove": (P("Rękawice", "Gloves"), None)}

COLUMN_INFO = {
    ("world", "item_proto"): _ITEM,
    ("player", "item_proto"): _ITEM,
    ("world", "mob_proto"): _MOB,
    ("player", "mob_proto"): _MOB,
    ("world", "refine_proto"): _REFINE,
    ("world", "item_attr"): _ATTR,
    ("world", "item_attr_rare"): _ATTR,
    ("world", "shop"): {"vnum": (P("Numer sklepu", "Shop number"), None),
                        "name": (P("Nazwa", "Name"), None),
                        "npc_vnum": (P("NPC sklepu", "Shop NPC"), "mob")},
    ("world", "shop_item"): {"shop_vnum": (P("Sklep", "Shop"), None),
                             "item_vnum": (P("Przedmiot", "Item"), "item"),
                             "count": (P("Ilość", "Count"), None)},
    ("world", "land"): {"id": (P("Numer działki", "Plot number"), None),
                        "map_index": (P("Mapa", "Map"), None),
                        "x": ("X", None), "y": ("Y", None),
                        "width": (P("Szerokość", "Width"), None),
                        "height": (P("Wysokość", "Height"), None),
                        "guild_level_limit": (P("Min. poziom gildii", "Min. guild level"), None),
                        "price": (P("Cena", "Price"), None),
                        "enable": (P("Dostępna", "Available"), None)},
    ("world", "skill_proto"): {
        "dwVnum": (P("Numer", "Number"), None),
        "szName": (P("Nazwa techniczna", "Technical name"), None),
        "bType": (P("Klasa", "Class"), "skillgroup"),
        "bLevelStep": (P("Krok poziomu", "Level step"), None),
        "bMaxLevel": (P("Maks. poziom", "Max. level"), None),
        "bLevelLimit": (P("Limit poziomu", "Level limit"), None),
        "szPointOn": (P("Efekt 1 – co", "Effect 1 – what"), None),
        "szPointPoly": (P("Efekt 1 – wzór", "Effect 1 – formula"), None),
        "szSPCostPoly": (P("Koszt PE – wzór", "SP cost – formula"), None),
        "szDurationPoly": (P("Czas trwania – wzór", "Duration – formula"), None),
        "szDurationSPCostPoly": (P("Koszt PE w czasie – wzór", "SP cost over time – formula"), None),
        "szCooldownPoly": (P("Cooldown – wzór", "Cooldown – formula"), None),
        "szMasterBonusPoly": (P("Bonus mistrza – wzór", "Master bonus – formula"), None),
        "szAttackGradePoly": (P("Wartość ataku – wzór", "Attack value – formula"), None),
        "setFlag": (P("Flagi", "Flags"), None),
        "setAffectFlag": (P("Efekt 1", "Effect 1"), None),
        "szPointOn2": (P("Efekt 2 – co", "Effect 2 – what"), None),
        "szPointPoly2": (P("Efekt 2 – wzór", "Effect 2 – formula"), None),
        "szDurationPoly2": (P("Czas efektu 2", "Effect 2 duration"), None),
        "setAffectFlag2": (P("Efekt 2", "Effect 2"), None),
        "szPointOn3": (P("Efekt 3 – co", "Effect 3 – what"), None),
        "szPointPoly3": (P("Efekt 3 – wzór", "Effect 3 – formula"), None),
        "szDurationPoly3": (P("Czas efektu 3", "Effect 3 duration"), None),
        "setAffectFlag3": (P("Efekt 3", "Effect 3"), None),
        "szGrandMasterAddSPCostPoly": (P("Dodatkowy koszt PE (wielki mistrz)",
                                         "Extra SP cost (grand master)"), None),
        "prerequisiteSkillVnum": (P("Wymagana umiejętność", "Required skill"), None),
        "prerequisiteSkillLevel": (P("Wymagany poziom umiejętności", "Required skill level"), None),
        "eSkillType": (P("Rodzaj", "Kind"), None), "iMaxHit": (P("Maks. trafień", "Max. hits"), None),
        "szSplashAroundDamageAdjustPoly": (P("Obrażenia obszarowe – wzór",
                                             "Area damage – formula"), None),
        "dwTargetRange": (P("Zasięg celu", "Target range"), None),
        "dwSplashRange": (P("Zasięg obszaru", "Area range"), None)},
    ("common", "exp_table"): {"level": (P("Poziom", "Level"), None),
                              "exp": (P("Doświadczenie do awansu", "Experience to level up"), None)},
    ("world", "crafting_proto"): {"vnum": (P("Numer przepisu", "Recipe number"), None),
                                  "item_vnum": (P("Wynik", "Result"), "item"),
                                  "count": (P("Ilość", "Count"), None),
                                  "price": (P("Cena (yang)", "Price (yang)"), None),
                                  "chance": (P("Szansa (%)", "Chance (%)"), None),
                                  "recipe": (P("Składniki", "Ingredients"), None),
                                  "req_progress": (P("Wymagany postęp", "Required progress"), None),
                                  "req_level": (P("Wymagany poziom", "Required level"), None),
                                  # Nie przedmiot: klucz postepu nauki (flaga
                                  # crafting.progress_<numer>, quest/libs/crafting).
                                  "recipe_vnum": (P("Receptura (numer postępu nauki)",
                                                    "Recipe book (learning progress number)"), None),
                                  "comment": (P("Komentarz", "Comment"), None)},
    ("world", "quest_reward_proto"): {"quest_name": ("Quest", None),
                                      "exp": (P("Doświadczenie", "Experience"), None),
                                      "gold": ("Yang", None),
                                      "alignment": (P("Ranga (alignment)", "Rank (alignment)"), None),
                                      "items": (P("Przedmioty (wszyscy)", "Items (everybody)"), None),
                                      "warrior_items": (P("Przedmioty – wojownik", "Items – warrior"), None),
                                      "assassin_items": (P("Przedmioty – ninja", "Items – ninja"), None),
                                      "sura_items": (P("Przedmioty – sura", "Items – sura"), None),
                                      "shaman_items": (P("Przedmioty – szaman", "Items – shaman"), None),
                                      "comment": (P("Komentarz", "Comment"), None)},
    ("common", "itemshop_items"): {"index": (P("Pozycja", "Position"), None),
                                   "vnum": (P("Przedmiot", "Item"), "item"),
                                   "count": (P("Ilość", "Count"), None),
                                   "price": (P("Cena", "Price"), None),
                                   "currency": (P("Waluta", "Currency"), None),
                                   "minLevel": (P("Min. poziom", "Min. level"), None),
                                   "socket0": (P("Gniazdo 1", "Socket 1"), None),
                                   "socket1": (P("Gniazdo 2", "Socket 2"), None),
                                   "socket2": (P("Gniazdo 3", "Socket 3"), None)},
    ("common", "gmlist"): {"mID": ("ID", None), "mAccount": (P("Konto", "Account"), None),
                           "mName": (P("Postać", "Character"), None),
                           "mContactIP": (P("IP kontaktowe", "Contact IP"), None),
                           "mServerIP": (P("IP serwera", "Server IP"), None),
                           "mAuthority": (P("Uprawnienia", "Authority"), None)},
    ("world", "object_proto"): {"vnum": ("VNUM", None), "name": (P("Nazwa", "Name"), None),
                                "price": (P("Cena", "Price"), None),
                                "materials": (P("Materiały", "Materials"), None),
                                "upgrade_vnum": (P("Ulepszenie do", "Upgrades to"), None),
                                "npc": (P("NPC budynku", "Building NPC"), "mob"),
                                "life": (P("Wytrzymałość", "Durability"), None)},
}


def info(db_name, table_name, column):
    """(etykieta, rodzaj) kolumny; nieznana kolumna -> (nazwa, None).

    The label is in the reader's language (resolved here, on the request)."""
    if column == "*":                      # wpis historii o calym wierszu (safety.ROW_COLUMN)
        return T("Cały wiersz", "Whole row"), None
    entry = COLUMN_INFO.get((db_name, table_name), {}).get(column)
    if entry:
        return tr(entry[0]), entry[1]
    return column, None


def label(db_name, table_name, column):
    return info(db_name, table_name, column)[0]


def kind(db_name, table_name, column):
    return info(db_name, table_name, column)[1]


# -----------------------------------------------------------------------------
#  Wartosci list wyboru
# -----------------------------------------------------------------------------
LIMIT_TYPES = {0: P("brak", "none"), 1: P("Poziom postaci", "Character level"),
               2: P("Siła", "Strength"), 3: P("Zręczność", "Dexterity"),
               4: P("Inteligencja", "Intelligence"),
               5: P("Witalność", "Vitality"), 6: "PC-bang", 7: P("Czas rzeczywisty", "Real time"),
               8: P("Czas od 1. użycia", "Time from first use"),
               9: P("Czas noszenia", "Time worn")}

# Maski bitowe item_proto (item_length.h). Pokazywane jako rozpisanie pod polem.
FLAG_BITS = {
    "item": (P("Ulepszalny", "Refinable"), P("Zapisywany", "Saved"),
             P("Stakowalny", "Stackable"), P("Cena za sztukę", "Price per piece"),
             P("Wolne zapytanie", "Slow query"),
             P("(nieużywany)", "(unused)"), P("Unikalny", "Unique"),
             P("Liczba przy tworzeniu", "Count when made"), P("Nieusuwalny", "Irremovable"),
             P("Potwierdzenie użycia", "Confirm use"), P("Użycie w queście", "Quest use"),
             P("Wielokrotne użycie w queście", "Repeated quest use"),
             P("Oddawany w queście", "Given in a quest"), P("Logowany", "Logged"),
             P("Nakładany na inny", "Applied to another")),
    "anti": (P("Nie dla kobiet", "Not for women"), P("Nie dla mężczyzn", "Not for men"),
             P("Nie dla wojownika", "Not for a warrior"), P("Nie dla ninja", "Not for a ninja"),
             P("Nie dla sury", "Not for a sura"), P("Nie dla szamana", "Not for a shaman"),
             P("Nie można podnieść", "Cannot be picked up"), P("Nie można wyrzucić", "Cannot be dropped"),
             P("Nie można sprzedać", "Cannot be sold"), P("Nie dla Shinsoo", "Not for Shinsoo"),
             P("Nie dla Chunjo", "Not for Chunjo"), P("Nie dla Jinno", "Not for Jinno"),
             P("Nie zapisywany", "Not saved"), P("Nie można oddać", "Cannot be given"),
             P("Nie wypada przy PK", "Not dropped in PK"), P("Nie można łączyć", "Cannot be stacked"),
             P("Nie do sklepu gracza", "Not for a player's shop"),
             P("Nie do magazynu", "Not for the storeroom")),
    "wear": (P("Zbroja", "Armour"), P("Hełm", "Helmet"), P("Buty", "Shoes"),
             P("Bransoleta", "Bracelet"), P("Broń", "Weapon"), P("Naszyjnik", "Necklace"),
             P("Kolczyki", "Earrings"), P("Unikalny", "Unique"), P("Tarcza", "Shield"),
             P("Strzały", "Arrows"), P("Fryzura", "Hairstyle"),
             P("Pierścień umiejętności", "Skill ring")),
}


def flag_names(group, value):
    try:
        mask = int(value or 0)
    except (TypeError, ValueError):
        return []
    names = FLAG_BITS.get(group, ())
    out = []
    bit = 0
    while mask >> bit:
        if mask & (1 << bit):
            out.append(tr(names[bit]) if bit < len(names) else "bit %d" % bit)
        bit += 1
    return out


def choices(kind_name, row=None, current=None):
    """[(wartosc, etykieta)] dla listy wyboru albo None (zwykle pole)."""
    unnamed = T("bez nazwy", "no name")
    if kind_name == "itemtype":
        known = dict(labels.DEFAULT_ITEM_TYPES)
        for number in labels.item_type_hints():
            known.setdefault(number, "")
        return [(n, "%d · %s" % (n, labels.name_of(labels.KIND_ITEM_TYPE, n) or unnamed))
                for n in sorted(known)]
    if kind_name == "itemsubtype":
        try:
            item_type = int((row or {}).get("type"))
        except (TypeError, ValueError):
            return None
        names = labels.DEFAULT_ITEM_SUBTYPES.get(item_type)
        if not names:
            return None
        return [(n, "%d · %s" % (n, t)) for n, t in sorted(names.items())]
    if kind_name == "rank":
        known = dict(labels.DEFAULT_MOB_RANKS)
        for number in labels.mob_rank_hints():
            known.setdefault(number, "")
        return [(n, "%d · %s" % (n, labels.name_of(labels.KIND_MOB_RANK, n) or unnamed))
                for n in sorted(known)]
    if kind_name == "mobtype":
        known = dict(labels.DEFAULT_MOB_TYPES)
        for number in labels.mob_type_hints():
            known.setdefault(number, "")
        return [(n, "%d · %s" % (n, labels.name_of(labels.KIND_MOB_TYPE, n) or unnamed))
                for n in sorted(known)]
    if kind_name == "empire":
        return [(n, "%d · %s" % (n, t)) for n, t in sorted(labels.EMPIRES.items())]
    if kind_name == "skillgroup":
        return [(n, "%d · %s" % (n, t)) for n, t in sorted(labels.SKILL_GROUPS.items())]
    if kind_name == "limittype":
        return [(n, "%d · %s" % (n, t)) for n, t in sorted(LIMIT_TYPES.items())]
    if kind_name == "apply":
        points = labels.point_labels()["by_number"]
        out = [(0, T("0 · brak bonusu", "0 · no bonus"))]
        for number in sorted(points):
            if number == 0:
                continue
            text, _code = labels.bonus_text(points[number]["name"])
            out.append((number, "%d · %s" % (number, text)))
        return out
    return None
