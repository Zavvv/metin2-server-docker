# =============================================================================
#  The front page  --  http://<server>:7788/
#
#  The public start page, built element for element from the template in
#  "CMS Metin2 & Itemshop Oldschool" (index.php -> head.php, main.php,
#  footer.php, user/*.php, main/*.php). The markup below uses the template's
#  own classes and stylesheet (static/cms/css/all.css, without its obsolete
#  IE behavior). front.css adapts the language switch, server data, credits
#  and eight screenshot slots. The gallery uses the browser's native dialog.
#
#      template                         here
#      -------------------------------  ---------------------------------------
#      header  "Regisztrálj..." button   "Zarejestruj się..." -> ?s=register
#      header  ItemShop/User/Logout      Moje konto / Zmień hasło / Wyloguj
#      col-1   main menu                 Panel seban latino, Discord, GitHub,
#                                        Mapa na żywo, Hasło panelu admina
#      col-1   download box              /download (the panel's own client)
#      col-2   ?s=home / register / ...  the same pages, this server's content
#      col-3   login box                 game-account login (same check as
#                                        the panel's /account)
#      col-3   "Ranglista" box           top 10 by level -- the /map Level tab
#      main/rankings.php ("Top 100")     ?s=rankings  -- top 100 characters
#      main/guildrank.php                ?s=guildrank -- top 100 guilds by wins
#      footer  copyright                 server state
#
#  Accounts are not reimplemented: login and registration use the panel's own
#  m2_hash() and account.account exactly like /account and /register do. The
#  delete code goes into social_id, which is what the game asks for.
#
#  Four languages (pl/en/de/tr); Polish is the default, as everywhere else in
#  the panel. The choice goes through the panel's own /lang/<code> route.
#
#  Wired up from the bottom of admin_panel.py:  front_page.init(module)
# =============================================================================

import hmac
import os
import threading
import time

from markupsafe import escape
from flask import (Response, get_flashed_messages, redirect, request,
                   send_from_directory, session, url_for)

panel = None          # admin_panel, handed in by init()


def _env(name, default):
    return os.environ.get(name, "").strip() or default


BAN_PANEL_PORT = _env("M2PANEL_BAN_PORT", "7790")
BAN_PANEL_URL = _env("M2PANEL_BAN_URL", "")
MAP_URL = _env("M2PANEL_MAP_URL", "/map")
GITHUB_URL = "https://github.com/TieruYT/metin2-playerbots"

PAGES = ("home", "register", "account", "pwchange", "admin", "rankings", "guildrank")


def ban_panel_url(host):
    """Same host the visitor used, the ban panel's port. The Host header is
    visitor-controlled, so anything that is not a plain hostname is dropped."""
    if BAN_PANEL_URL:
        return BAN_PANEL_URL
    host = str(host or "")
    if host.startswith("["):                       # [::1]:7788
        host = host[1:].split("]")[0]
    else:
        host = host.split(":")[0]
    if not host or not all(c.isalnum() or c in ".-:" for c in host):
        host = "127.0.0.1"
    if ":" in host:
        host = "[%s]" % host
    return "http://%s:%s/" % (host, BAN_PANEL_PORT)



# =============================================================================
# Texts. Every key in all four languages.
# =============================================================================
S = {
    "title": {
        "pl": "Metin2 SinglePlayer",
        "en": "Metin2 SinglePlayer",
        "de": "Metin2 SinglePlayer",
        "tr": "Metin2 SinglePlayer"
    },

    # header
    "reg_banner": {
        "pl": "Zarejestruj się w Metin2 SinglePlayer!",
        "en": "Register and play Metin2 SinglePlayer now!",
        "de": "Registriere dich jetzt Metin2 SinglePlayer!",
        "tr": "Kayıt ol ve hemen Metin2 SinglePlayer oyna!"
    },
    "reg_steps": {
        "pl": "Kliknij tutaj aby zarejestrować nowe konto w Metin2 SinglePlayer!",
        "en": "Click here to register a new Metin2 SinglePlayer account!",
        "de": "Klicke hier, um ein neues Metin2 SinglePlayer-Konto zu registrieren!",
        "tr": "Yeni bir Metin2 SinglePlayer hesabı oluşturmak için buraya tıkla!"
    },
    "nav_account": {
        "pl": "Moje konto",
        "en": "My account",
        "de": "Mein Konto",
        "tr": "Hesabım"
    },
    "nav_pw": {
        "pl": "Zmień hasło",
        "en": "Change password",
        "de": "Passwort ändern",
        "tr": "Şifreyi değiştir"
    },
    "nav_logout": {
        "pl": "Wyloguj",
        "en": "Log out",
        "de": "Abmelden",
        "tr": "Çıkış yap"
    },

    # left menu
    "m_ban": {
        "pl": "Panel seban latino",
        "en": "Panel seban latino",
        "de": "Panel seban latino",
        "tr": "Panel seban latino"
    },
    "m_discord": {
        "pl": "Discord",
        "en": "Discord",
        "de": "Discord",
        "tr": "Discord"
    },
    "m_github": {
        "pl": "GitHub",
        "en": "GitHub",
        "de": "GitHub",
        "tr": "GitHub"
    },
    "m_map": {
        "pl": "Mapa na żywo",
        "en": "Live map",
        "de": "Live-Karte",
        "tr": "Canlı harita"
    },
    "m_adminpw": {
        "pl": "Hasło panelu admina",
        "en": "Admin panel password",
        "de": "Admin-Panel-Passwort",
        "tr": "Yönetici paneli şifresi"
    },
    "dl_title": {
        "pl": "Pobierz",
        "en": "Download",
        "de": "Download",
        "tr": "İndir"
    },

    # right column: login
    "login_title": {
        "pl": "Logowanie",
        "en": "Log in",
        "de": "Anmelden",
        "tr": "Giriş yap"
    },
    "login_user": {
        "pl": "Nazwa użytkownika:",
        "en": "Username:",
        "de": "Benutzername:",
        "tr": "Kullanıcı adı:"
    },
    "login_pw": {
        "pl": "Hasło:",
        "en": "Password:",
        "de": "Passwort:",
        "tr": "Şifre:"
    },
    "login_btn": {
        "pl": "Zaloguj",
        "en": "Log in",
        "de": "Einloggen",
        "tr": "Giriş yap"
    },
    "login_terms": {
        "pl": "Logując się akceptujesz",
        "en": "By logging in you accept the",
        "de": "Mit dem Login akzeptierst du die",
        "tr": "Giriş yaparak şunları kabul etmiş olursun:"
    },
    "terms": {
        "pl": "warunki korzystania",
        "en": "terms of use",
        "de": "Nutzungsbedingungen",
        "tr": "kullanım koşullarını"
    },
    "login_noacc": {
        "pl": "Nie masz konta? Zarejestruj się",
        "en": "Don't have an account? Register",
        "de": "Noch kein Konto? Registriere dich",
        "tr": "Hesabın yok mu? Kayıt ol"
    },
    "user_title": {
        "pl": "Konto",
        "en": "Account",
        "de": "Konto",
        "tr": "Hesap"
    },
    "user_hello": {
        "pl": "Witaj,",
        "en": "Welcome,",
        "de": "Willkommen,",
        "tr": "Hoş geldin,"
    },
    "user_chars": {
        "pl": "Postacie:",
        "en": "Characters:",
        "de": "Charaktere:",
        "tr": "Karakterler:"
    },
    "user_status": {
        "pl": "Status:",
        "en": "Status:",
        "de": "Status:",
        "tr": "Durum:"
    },

    # right column: ranking
    "rank_title": {
        "pl": "Ranking",
        "en": "Ranking",
        "de": "Rangliste",
        "tr": "Sıralama"
    },
    "rank_more": {
        "pl": "Top 100",
        "en": "Top 100",
        "de": "Top 100",
        "tr": "İlk 100"
    },
    "rank_empty": {
        "pl": "Brak danych.",
        "en": "No data yet.",
        "de": "Noch keine Daten.",
        "tr": "Henüz veri yok."
    },
    "rk_h2": {
        "pl": "Ranking graczy (Top 100)",
        "en": "Player ranking (Top 100)",
        "de": "Spieler-Rangliste (Top 100)",
        "tr": "Oyuncu sıralaması (İlk 100)"
    },
    "gr_h2": {
        "pl": "Ranking gildii (Top 100)",
        "en": "Guild ranking (Top 100)",
        "de": "Gilden-Rangliste (Top 100)",
        "tr": "Lonca sıralaması (İlk 100)"
    },
    "rk_pos": {"pl": "Miejsce", "en": "Rank", "de": "Platz", "tr": "Sıra"},
    "rk_name": {"pl": "Nazwa", "en": "Name", "de": "Name", "tr": "İsim"},
    "rk_level": {"pl": "Poziom", "en": "Level", "de": "Stufe", "tr": "Seviye"},
    "rk_exp": {"pl": "Exp", "en": "Exp", "de": "Exp", "tr": "Tecrübe"},
    "rk_empire": {"pl": "Królestwo", "en": "Empire", "de": "Reich", "tr": "İmparatorluk"},
    "gr_win": {"pl": "Zwycięstwa", "en": "Wins", "de": "Siege", "tr": "Galibiyet"},
    "gr_draw": {"pl": "Remisy", "en": "Draws", "de": "Unentschieden", "tr": "Beraberlik"},
    "gr_loss": {"pl": "Porażki", "en": "Losses", "de": "Niederlagen", "tr": "Mağlubiyet"},
    "gr_link": {
        "pl": "Ranking gildii",
        "en": "Guild ranking",
        "de": "Gilden-Rangliste",
        "tr": "Lonca sıralaması"
    },
    "rk_link": {
        "pl": "Ranking graczy",
        "en": "Player ranking",
        "de": "Spieler-Rangliste",
        "tr": "Oyuncu sıralaması"
    },
    "lv": {
        "pl": "Lv",
        "en": "Lv",
        "de": "Lv",
        "tr": "Sv."
    },

    # home
    "home_box1": {
        "pl": "Metin2 SinglePlayer",
        "en": "Metin2 SinglePlayer",
        "de": "Metin2 SinglePlayer",
        "tr": "Metin2 SinglePlayer"
    },
    "home_box2": {
        "pl": "Serwer",
        "en": "Server",
        "de": "Server",
        "tr": "Sunucu"
    },
    "home_welcome": {
        "pl": "Witaj w Metin2 SinglePlayer!",
        "en": "Welcome to Metin2 SinglePlayer!",
        "de": "Willkommen bei Metin2 SinglePlayer!",
        "tr": "Metin2 SinglePlayer'a hoş geldin!"
    },
    "srv_state": {
        "pl": "Stan serwera:",
        "en": "Server status:",
        "de": "Serverstatus:",
        "tr": "Sunucu durumu:"
    },
    "srv_on": {
        "pl": "online",
        "en": "online",
        "de": "online",
        "tr": "çevrimiçi"
    },
    "srv_off": {
        "pl": "offline",
        "en": "offline",
        "de": "offline",
        "tr": "çevrimdışı"
    },
    "srv_players": {
        "pl": "Graczy w grze:",
        "en": "Players in game:",
        "de": "Spieler im Spiel:",
        "tr": "Oyundaki oyuncular:"
    },
    "srv_map": {
        "pl": "Zobacz świat na mapie na żywo",
        "en": "See the world on the live map",
        "de": "Sieh dir die Welt auf der Live-Karte an",
        "tr": "Dünyayı canlı haritada gör"
    },
    "screens": {
        "pl": "Screenshoty",
        "en": "Screenshots",
        "de": "Screenshots",
        "tr": "Ekran görüntüleri"
    },

    "about_h2": {
        "pl": "Metin2 SinglePlayer — Co to jest?",
        "en": "Metin2 SinglePlayer — What is it?",
        "de": "Metin2 SinglePlayer — Was ist das?",
        "tr": "Metin2 SinglePlayer — Nedir?"
    },
    "about_lead": {
        "pl": "Lokalny świat Metin2 rozwijany jako hobbystyczne środowisko dla autonomicznych botów graczy.",
        "en": "A local Metin2 world developed as a hobby project and a living environment for autonomous player bots.",
        "de": "Eine lokale Metin2-Welt, die als Hobbyprojekt und lebendige Umgebung für autonome Spieler-Bots entwickelt wird.",
        "tr": "Otonom oyuncu botları için yaşayan bir ortam olarak geliştirilen yerel bir Metin2 dünyası ve hobi projesidir."
    },

    "about_features_h": {
        "pl": "Cechy",
        "en": "Features",
        "de": "Features",
        "tr": "Özellikler"
    },

    "about_f1": {
        "pl": "Odtwórz magię lat 2008–2010 bez toksyczności, bez pay-to-win i bez pośpiechu.",
        "en": "Relive the magic of 2008–2010 without toxicity, pay-to-win mechanics or the pressure to rush.",
        "de": "Erlebe die Magie der Jahre 2008–2010 erneut – ohne Toxizität, Pay-to-win und ohne Zeitdruck.",
        "tr": "2008–2010 yıllarının büyüsünü toksiklik, pay-to-win sistemleri ve acele olmadan yeniden yaşa."
    },

    "about_f2": {
        "pl": "Setki autonomicznych graczy-botów expią, ulepszają ekwipunek, handlują na straganach i polują na bossy w Twoim prywatnym świecie.",
        "en": "Hundreds of autonomous player bots gain experience, upgrade their equipment, trade at stalls and hunt bosses in your private world.",
        "de": "Hunderte autonome Spieler-Bots sammeln Erfahrung, verbessern ihre Ausrüstung, handeln an Ständen und jagen Bosse in deiner privaten Welt.",
        "tr": "Yüzlerce otonom oyuncu botu deneyim kazanır, ekipmanlarını geliştirir, pazarlarda ticaret yapar ve özel dünyanda boss avlar."
    },

    "about_f3": {
        "pl": "Zautomatyzowane Wojny Trzech Królestw z setkami botów",
        "en": "Automated Wars of the Three Kingdoms featuring hundreds of bots.",
        "de": "Automatisierte Kriege der Drei Reiche mit Hunderten von Bots.",
        "tr": "Yüzlerce botun katıldığı otomatikleştirilmiş Üç Krallık Savaşları."
    },

    "about_f4": {
        "pl": "Podgląd pozycji wszystkich botów w czasie rzeczywistym na mapie w przeglądarce.",
        "en": "Track the real-time positions of all bots on a live map directly in your browser.",
        "de": "Verfolge die Position aller Bots in Echtzeit auf einer Live-Karte direkt im Browser.",
        "tr": "Tüm botların konumlarını tarayıcıdaki canlı harita üzerinden gerçek zamanlı olarak takip et."
    },

    "about_f5": {
        "pl": "Wszystko czego potrzebujesz do uruchomienia gry – pobierasz jedną paczkę i grasz bez zbędnych komplikacji.",
        "en": "Everything you need to start playing — download a single package and play without unnecessary complications.",
        "de": "Alles, was du zum Spielen brauchst – lade ein einziges Paket herunter und spiele ohne unnötige Komplikationen.",
        "tr": "Oynamaya başlamak için ihtiyacın olan her şey burada — tek bir paket indir ve gereksiz komplikasyonlar olmadan oyna."
    },

    "about_p1": {
        "pl": "Wielu z nas doskonale pamięta nieprzespane noce w Dolinie Orków, na Pustyni czy pod Wieżą Demonów w 2009 roku. Niestety, dzisiejsze serwery MMORPG to najczęściej bezlitosny wyścig szczurów, agresywne mikropłatności Pay-to-Win oraz społeczność, w której trudno o relaks.",
        "en": "Many of us still remember the sleepless nights in the Valley of Seungryong, the Desert or beneath the Demon Tower back in 2009. Unfortunately, today's MMORPG servers are often a ruthless rat race, filled with aggressive pay-to-win microtransactions and communities where it is hard to simply relax.",
        "de": "Viele von uns erinnern sich noch gut an die schlaflosen Nächte im Orktal, in der Wüste oder unter dem Dämonenturm im Jahr 2009. Leider sind heutige MMORPG-Server oft ein erbarmungsloser Wettlauf, geprägt von aggressiven Pay-to-win-Mikrotransaktionen und einer Community, in der Entspannung kaum möglich ist.",
        "tr": "Birçoğumuz 2009 yılında Ork Vadisi'nde, Çöl'de veya Şeytan Kulesi'nin altında geçirilen uykusuz geceleri hâlâ çok iyi hatırlıyoruz. Ne yazık ki günümüz MMORPG sunucuları çoğunlukla acımasız bir rekabet, agresif pay-to-win mikro ödemeleri ve rahatlamanın zor olduğu topluluklar anlamına geliyor."
    },

    "about_p2": {
        "pl": "W dorosłym życiu, mając pracę i rodzinę, rzadko możemy pozwolić sobie na wielogodzinny, nieprzerwany grind. Metin2 Singleplayer powstał, by dać Ci dokładnie ten sam, ukochany świat – ale na Twoich własnych zasadach.",
        "en": "As adults with jobs and families, we rarely have time for hours of uninterrupted grinding. Metin2 SinglePlayer was created to give you that same beloved world — but on your own terms.",
        "de": "Als Erwachsene mit Arbeit und Familie haben wir nur selten die Zeit für stundenlanges, ununterbrochenes Grinden. Metin2 SinglePlayer wurde geschaffen, um dir dieselbe geliebte Welt zu geben – aber zu deinen eigenen Bedingungen.",
        "tr": "İş ve aile hayatı olan yetişkinler olarak saatlerce kesintisiz farm yapmaya nadiren zaman bulabiliyoruz. Metin2 SinglePlayer, sana aynı sevdiğin dünyayı sunmak için oluşturuldu — ama kendi kurallarınla."
    },

    "about_p3": {
        "pl": "✓Grasz kiedy chcesz, pauzujesz kiedy musisz ✓Zero mikropłatności, ItemShopu i sztucznego blokowania postępu ✓Idealna płynność i stabilność bez lagów sieciowych",
        "en": "✓ Play whenever you want, pause whenever you need ✓ Zero microtransactions, Item Shop or artificial progression barriers ✓ Smooth and stable gameplay without network lag",
        "de": "✓ Spiele, wann du möchtest, und pausiere, wann du musst ✓ Keine Mikrotransaktionen, kein Item-Shop und keine künstlichen Fortschrittsbarrieren ✓ Flüssiges und stabiles Gameplay ohne Netzwerk-Lags",
        "tr": "✓ İstediğin zaman oyna, gerektiğinde duraklat ✓ Sıfır mikro ödeme, Item Shop ve yapay ilerleme engelleri ✓ Ağ gecikmesi olmadan akıcı ve stabil oyun deneyimi"
    },

    # register page
    "reg_h2": {
        "pl": "Metin2 SinglePlayer - Rejestracja",
        "en": "Metin2 SinglePlayer - Registration",
        "de": "Metin2 SinglePlayer - Registrierung",
        "tr": "Metin2 SinglePlayer - Kayıt"
    },
    "reg_h3": {
        "pl": "Rejestracja",
        "en": "Registration",
        "de": "Registrierung",
        "tr": "Kayıt"
    },
    "reg_tologin": {
        "pl": "Logowanie",
        "en": "Log in",
        "de": "Anmelden",
        "tr": "Giriş yap"
    },
    "reg_user": {
        "pl": "Nazwa użytkownika:",
        "en": "Username:",
        "de": "Benutzername:",
        "tr": "Kullanıcı adı:"
    },
    "reg_pw": {
        "pl": "Hasło:",
        "en": "Password:",
        "de": "Passwort:",
        "tr": "Şifre:"
    },
    "reg_code": {
        "pl": "Kod usuwania postaci:",
        "en": "Character deletion code:",
        "de": "Charakter-Löschcode:",
        "tr": "Karakter silme kodu:"
    },
    "reg_btn": {
        "pl": "Zarejestruj",
        "en": "Register",
        "de": "Registrieren",
        "tr": "Kayıt ol"
    },
    "reg_legend": {
        "pl": "Wszystkie pola są wymagane!<br />Nazwa: 4–16 liter lub cyfr.<br />Hasło: min. 6 znaków.<br />Kod usuwania: dokładnie 7 cyfr.<br />Rejestrując się akceptujesz<br />",
        "en": "All fields are required!<br />Username: 4–16 letters or digits.<br />Password: at least 6 characters.<br />Deletion code: exactly 7 digits.<br />By registering you accept the<br />",
        "de": "Alle Felder sind Pflichtfelder!<br />Benutzername: 4–16 Buchstaben oder Ziffern.<br />Passwort: mindestens 6 Zeichen.<br />Löschcode: genau 7 Ziffern.<br />Mit der Registrierung akzeptierst du die<br />",
        "tr": "Tüm alanlar zorunludur!<br />Kullanıcı adı: 4–16 harf veya rakam.<br />Şifre: en az 6 karakter.<br />Silme kodu: tam 7 rakam.<br />Kayıt olarak şunları kabul etmiş olursun:<br />"
    },

    # account pages
    "acc_h2": {
        "pl": "Metin2 SinglePlayer - Moje konto",
        "en": "Metin2 SinglePlayer - My account",
        "de": "Metin2 SinglePlayer - Mein Konto",
        "tr": "Metin2 SinglePlayer - Hesabım"
    },
    "acc_chars": {
        "pl": "Twoje postacie",
        "en": "Your characters",
        "de": "Deine Charaktere",
        "tr": "Karakterlerin"
    },
    "acc_none": {
        "pl": "Nie masz jeszcze żadnej postaci. Zaloguj się do gry i stwórz pierwszą.",
        "en": "You don't have any characters yet. Log into the game and create your first one.",
        "de": "Du hast noch keine Charaktere. Melde dich im Spiel an und erstelle deinen ersten Charakter.",
        "tr": "Henüz hiç karakterin yok. Oyuna giriş yap ve ilk karakterini oluştur."
    },
    "col_name": {
        "pl": "Postać",
        "en": "Character",
        "de": "Charakter",
        "tr": "Karakter"
    },
    "col_lv": {
        "pl": "Poziom",
        "en": "Level",
        "de": "Level",
        "tr": "Seviye"
    },
    "col_gold": {
        "pl": "Yang",
        "en": "Yang",
        "de": "Yang",
        "tr": "Yang"
    },
    "acc_play": {
        "pl": "Graj w przeglądarce",
        "en": "Play in the browser",
        "de": "Im Browser spielen",
        "tr": "Tarayıcıda oyna"
    },
    "pw_h2": {
        "pl": "Metin2 SinglePlayer - Zmiana hasła",
        "en": "Metin2 SinglePlayer - Change password",
        "de": "Metin2 SinglePlayer - Passwort ändern",
        "tr": "Metin2 SinglePlayer - Şifreyi değiştir"
    },
    "pw_old": {
        "pl": "Obecne hasło:",
        "en": "Current password:",
        "de": "Aktuelles Passwort:",
        "tr": "Mevcut şifre:"
    },
    "pw_new": {
        "pl": "Nowe hasło:",
        "en": "New password:",
        "de": "Neues Passwort:",
        "tr": "Yeni şifre:"
    },
    "pw_new2": {
        "pl": "Nowe hasło ponownie:",
        "en": "New password again:",
        "de": "Neues Passwort wiederholen:",
        "tr": "Yeni şifre tekrar:"
    },
    "pw_btn": {
        "pl": "Zmień",
        "en": "Change",
        "de": "Ändern",
        "tr": "Değiştir"
    },
    "need_login": {
        "pl": "Zaloguj się w okienku po prawej, aby zobaczyć tę stronę.",
        "en": "Log in using the box on the right to view this page.",
        "de": "Melde dich über das Feld rechts an, um diese Seite zu sehen.",
        "tr": "Bu sayfayı görmek için sağdaki giriş kutusundan giriş yap."
    },

    # admin password page
    "adm_h2": {
        "pl": "Metin2 SinglePlayer - Panel admina",
        "en": "Metin2 SinglePlayer - Admin panel",
        "de": "Metin2 SinglePlayer - Admin-Panel",
        "tr": "Metin2 SinglePlayer - Yönetici paneli"
    },
    "adm_h3": {
        "pl": "Hasło panelu admina",
        "en": "Admin panel password",
        "de": "Admin-Panel-Passwort",
        "tr": "Yönetici paneli şifresi"
    },
    "adm_pw": {
        "pl": "Hasło panelu:",
        "en": "Panel password:",
        "de": "Panel-Passwort:",
        "tr": "Panel şifresi:"
    },
    "adm_btn": {
        "pl": "Wejdź",
        "en": "Enter",
        "de": "Öffnen",
        "tr": "Giriş yap"
    },
    "adm_open": {
        "pl": "Panel admina nie wymaga hasła na tej instalacji (tryb lokalny).",
        "en": "The admin panel does not require a password on this installation (local mode).",
        "de": "Das Admin-Panel benötigt auf dieser Installation kein Passwort (lokaler Modus).",
        "tr": "Bu kurulumda yönetici paneli şifre gerektirmiyor (yerel mod)."
    },
    "adm_in": {
        "pl": "Jesteś zalogowany do panelu admina.",
        "en": "You are logged into the admin panel.",
        "de": "Du bist im Admin-Panel angemeldet.",
        "tr": "Yönetici paneline giriş yaptın."
    },
    "adm_go": {
        "pl": "Otwórz panel admina",
        "en": "Open the admin panel",
        "de": "Admin-Panel öffnen",
        "tr": "Yönetici panelini aç"
    },
    "adm_note": {
        "pl": "Hasło panelu nie jest nigdzie zapisane jawnie — panel trzyma tylko jego odcisk (PBKDF2), więc nie da się go odczytać, można je tylko ustawić od nowa. Przy pierwszym starcie panel wypisuje je raz w logach kontenera (blok „ADMIN PANEL PASSWORD”). Aby ustawić nowe, na serwerze wykonaj:",
        "en": "The panel password is never stored in readable form — the panel only stores its fingerprint (PBKDF2), so it cannot be retrieved and can only be reset. On the first startup, the panel prints it once in the container logs (the “ADMIN PANEL PASSWORD” block). To set a new one, run this on the server:",
        "de": "Das Panel-Passwort wird niemals im Klartext gespeichert – das Panel speichert nur seinen Fingerabdruck (PBKDF2). Es kann daher nicht ausgelesen, sondern nur neu gesetzt werden. Beim ersten Start gibt das Panel das Passwort einmal in den Container-Logs aus (Block „ADMIN PANEL PASSWORD“). Um ein neues zu setzen, führe auf dem Server Folgendes aus:",
        "tr": "Panel şifresi hiçbir zaman okunabilir biçimde saklanmaz — panel yalnızca parmak izini (PBKDF2) saklar. Bu nedenle şifre okunamaz, yalnızca yeniden ayarlanabilir. Panel ilk kez başlatıldığında şifreyi konteyner günlüklerine bir kez yazar (“ADMIN PANEL PASSWORD” bölümü). Yeni bir şifre belirlemek için sunucuda şunu çalıştır:"
    },

    # messages
    "err_db": {
        "pl": "Baza danych jest chwilowo niedostępna. Spróbuj za moment.",
        "en": "The database is temporarily unavailable. Please try again in a moment.",
        "de": "Die Datenbank ist vorübergehend nicht verfügbar. Versuche es gleich noch einmal.",
        "tr": "Veritabanı geçici olarak kullanılamıyor. Lütfen birazdan tekrar dene."
    },
    "err_login": {
        "pl": "Błędna nazwa użytkownika lub hasło.",
        "en": "Incorrect username or password.",
        "de": "Falscher Benutzername oder falsches Passwort.",
        "tr": "Kullanıcı adı veya şifre hatalı."
    },
    "err_rate_login": {
        "pl": "Zbyt wiele prób logowania. Odczekaj chwilę.",
        "en": "Too many login attempts. Please wait a moment.",
        "de": "Zu viele Anmeldeversuche. Bitte warte einen Moment.",
        "tr": "Çok fazla giriş denemesi yapıldı. Lütfen biraz bekle."
    },
    "err_rate_reg": {
        "pl": "Z tego połączenia założono już kilka kont. Spróbuj później.",
        "en": "Several accounts have already been created from this connection. Please try again later.",
        "de": "Über diese Verbindung wurden bereits mehrere Konten erstellt. Versuche es später erneut.",
        "tr": "Bu bağlantıdan zaten birkaç hesap oluşturuldu. Lütfen daha sonra tekrar dene."
    },
    "err_name": {
        "pl": "Nazwa użytkownika musi mieć 4–16 znaków (tylko litery i cyfry).",
        "en": "The username must contain 4–16 characters (letters and digits only).",
        "de": "Der Benutzername muss 4–16 Zeichen lang sein (nur Buchstaben und Ziffern).",
        "tr": "Kullanıcı adı 4–16 karakterden oluşmalıdır (yalnızca harf ve rakam)."
    },
    "err_pw_short": {
        "pl": "Hasło musi mieć co najmniej 6 znaków.",
        "en": "The password must be at least 6 characters long.",
        "de": "Das Passwort muss mindestens 6 Zeichen lang sein.",
        "tr": "Şifre en az 6 karakter uzunluğunda olmalıdır."
    },
    "err_pw_long": {
        "pl": "Hasło może mieć najwyżej 16 znaków.",
        "en": "The password can be at most 16 characters long.",
        "de": "Das Passwort darf höchstens 16 Zeichen lang sein.",
        "tr": "Şifre en fazla 16 karakter uzunluğunda olabilir."
    },
    "err_code": {
        "pl": "Kod usuwania to dokładnie 7 cyfr (np. 1234567).",
        "en": "The deletion code must contain exactly 7 digits (e.g. 1234567).",
        "de": "Der Löschcode muss genau 7 Ziffern enthalten (z. B. 1234567).",
        "tr": "Silme kodu tam olarak 7 rakamdan oluşmalıdır (örn. 1234567)."
    },
    "err_taken": {
        "pl": "Ta nazwa użytkownika jest już zajęta — wybierz inną.",
        "en": "That username is already taken — please choose another one.",
        "de": "Dieser Benutzername ist bereits vergeben – wähle bitte einen anderen.",
        "tr": "Bu kullanıcı adı zaten alınmış — lütfen başka bir tane seç."
    },
    "err_create": {
        "pl": "Nie udało się teraz założyć konta. Spróbuj za chwilę.",
        "en": "The account could not be created right now. Please try again shortly.",
        "de": "Das Konto konnte gerade nicht erstellt werden. Versuche es gleich noch einmal.",
        "tr": "Hesap şu anda oluşturulamadı. Lütfen birazdan tekrar dene."
    },
    "ok_created": {
        "pl": "Konto <b>%s</b> zostało założone i jesteś już zalogowany. Działa od razu w grze.",
        "en": "The account <b>%s</b> has been created and you are now logged in. It works in the game immediately.",
        "de": "Das Konto <b>%s</b> wurde erstellt und du bist jetzt angemeldet. Es funktioniert sofort im Spiel.",
        "tr": "<b>%s</b> hesabı oluşturuldu ve artık giriş yaptın. Hesap oyunda hemen kullanılabilir."
    },
    "pw_ok": {
        "pl": "Hasło zostało zmienione. Użyj nowego przy następnym logowaniu do gry.",
        "en": "Your password has been changed. Use the new one the next time you log into the game.",
        "de": "Dein Passwort wurde geändert. Verwende das neue Passwort beim nächsten Login ins Spiel.",
        "tr": "Şifren değiştirildi. Oyuna bir sonraki girişinde yeni şifreni kullan."
    },
    "pw_bad": {
        "pl": "Obecne hasło jest nieprawidłowe.",
        "en": "The current password is incorrect.",
        "de": "Das aktuelle Passwort ist falsch.",
        "tr": "Mevcut şifre yanlış."
    },
    "pw_diff": {
        "pl": "Nowe hasła się różnią.",
        "en": "The two new passwords do not match.",
        "de": "Die beiden neuen Passwörter stimmen nicht überein.",
        "tr": "Yeni şifreler birbiriyle eşleşmiyor."
    },

    # footer
    "foot_on": {
        "pl": "Serwer online",
        "en": "Server online",
        "de": "Server online",
        "tr": "Sunucu çevrimiçi"
    },
    "foot_off": {
        "pl": "Serwer offline",
        "en": "Server offline",
        "de": "Server offline",
        "tr": "Sunucu çevrimdışı"
    },
    "foot_players": {
        "pl": "graczy w grze",
        "en": "players in game",
        "de": "Spieler im Spiel",
        "tr": "oyuncu oyunda"
    },
    "foot_hobby": {
        "pl": "Projekt hobbystyczny .",
        "en": "A hobby project ",
        "de": "Ein Hobbyprojekt ",
        "tr": "Bir hobi projesi "
    },
}


S.update({
    "reg_legend": {
        "pl": "Wszystkie pola są wymagane!<br />Nazwa: 4–16 liter A–Z lub cyfr 0–9.<br />Hasło: 6–16 znaków ASCII bez spacji.<br />Kod usuwania: dokładnie 7 cyfr 0–9.<br />Rejestrując się akceptujesz<br />",
        "en": "All fields are required!<br />Username: 4–16 letters A–Z or digits 0–9.<br />Password: 6–16 ASCII characters without spaces.<br />Deletion code: exactly 7 digits 0–9.<br />By registering you accept the<br />",
        "de": "Alle Felder sind Pflichtfelder!<br />Benutzername: 4–16 Buchstaben A–Z oder Ziffern 0–9.<br />Passwort: 6–16 ASCII-Zeichen ohne Leerzeichen.<br />Löschcode: genau 7 Ziffern 0–9.<br />Mit der Registrierung akzeptierst du die<br />",
        "tr": "Tüm alanlar zorunludur!<br />Kullanıcı adı: 4–16 A–Z harfi veya 0–9 rakamı.<br />Şifre: boşluksuz 6–16 ASCII karakteri.<br />Silme kodu: tam 7 adet 0–9 rakamı.<br />Kaydolarak şunları kabul etmiş olursun:<br />"},
    "adm_note": {
        "pl": "Ta strona nie wyświetla hasła administratora. Gdy go nie znasz, skontaktuj się z właścicielem serwera. Właściciel zarządza hasłem przez launcher lub konfigurację serwera.",
        "en": "This page never displays the administrator password. If you do not know it, contact the server owner. The owner manages it through the launcher or server configuration.",
        "de": "Diese Seite zeigt das Administratorpasswort niemals an. Wenn du es nicht kennst, wende dich an den Serverbetreiber. Er verwaltet es im Launcher oder in der Serverkonfiguration.",
        "tr": "Bu sayfa yönetici şifresini asla göstermez. Şifreyi bilmiyorsan sunucu sahibiyle iletişime geç. Sunucu sahibi şifreyi başlatıcı veya sunucu yapılandırması üzerinden yönetir."},
    "err_pw_chars": {
        "pl": "Hasło: 6–16 znaków ASCII bez spacji (litery, cyfry i symbole).",
        "en": "Password: 6–16 ASCII characters without spaces (letters, digits and symbols).",
        "de": "Passwort: 6–16 ASCII-Zeichen ohne Leerzeichen (Buchstaben, Ziffern und Symbole).",
        "tr": "Şifre: boşluksuz 6–16 ASCII karakteri (harfler, rakamlar ve simgeler)."},
    "cms_credit": {"pl": "Panel CMS", "en": "CMS panel", "de": "CMS-Panel", "tr": "CMS paneli"},
    "license_extra": {"pl": "z dodatkowymi zezwoleniami autora", "en": "with the author's additional permissions", "de": "mit zusätzlichen Genehmigungen des Autors", "tr": "yazarın ek izinleriyle"},
    "legal": {"pl": "Licencja i informacje", "en": "Licence and information", "de": "Lizenz und Informationen", "tr": "Lisans ve bilgiler"},
    "close": {"pl": "Zamknij", "en": "Close", "de": "Schließen", "tr": "Kapat"},
    "shot_alt": {"pl": "Zrzut ekranu %d", "en": "Screenshot %d", "de": "Bildschirmfoto %d", "tr": "Ekran görüntüsü %d"},
    "screens": {"pl": "Galeria szablonu — miejsca na własne zrzuty", "en": "Template gallery — slots for your screenshots", "de": "Vorlagengalerie — Plätze für eigene Bildschirmfotos", "tr": "Şablon galerisi — kendi ekran görüntülerin için yerler"},
    "about_p3": {
        "pl": "Grasz we własnym tempie. ItemShop korzysta z waluty zdobywanej w grze, bez zakupów za prawdziwe pieniądze. Możesz zaprosić znajomych do swojego świata przez COOP.",
        "en": "Play at your own pace. The Item Shop uses currency earned in game, without real-money purchases. Invite friends into your world through COOP.",
        "de": "Spiele in deinem eigenen Tempo. Der Item-Shop nutzt im Spiel verdiente Währung, ohne Käufe für echtes Geld. Lade Freunde über COOP in deine Welt ein.",
        "tr": "Kendi hızında oyna. Nesne Marketi gerçek para alışverişi olmadan, oyunda kazanılan para birimini kullanır. COOP ile arkadaşlarını dünyana davet et."},
})


def s(key, lang):
    row = S.get(key) or {}
    return row.get(lang) or row.get("pl") or key


def e(key, lang):
    """A text, escaped for HTML."""
    return str(escape(s(key, lang)))


def _csrf():
    return '<input type="hidden" name="_csrf" value="%s" />' % escape(panel.csrf_token())


def _u(page=None, **kw):
    """Link to a sub-page of the front page, the template's ?s= style."""
    if page and page != "home":
        kw["s"] = page
    return str(escape(url_for("front", **kw)))


# =============================================================================
#  Data
# =============================================================================
_RANK = {"ts": 0.0, "rows": []}
_RANK_LOCK = threading.Lock()


RANK_TOP = 100


def ranking(limit=10):
    """Top characters by level -- the same query as the Level tab on /map
    (/api/bot_rankings?type=level), plus the empire for the template's flag.
    The top 100 is fetched once and shared: the box on the right takes the
    first 10, ?s=rankings shows all of them, so the two can never disagree.
    Cached for a minute: this is the most visited page and must not query the
    database on every hit. Never raises."""
    return _ranking_all()[:limit]


def _ranking_all():
    now = time.time()
    if now - _RANK["ts"] < 60:
        return _RANK["rows"]
    with _RANK_LOCK:
        if now - _RANK["ts"] < 60:
            return _RANK["rows"]
        rows = []
        try:
            with panel.db() as c, c.cursor() as cur:
                cur.execute(panel.ranking_sql("""
                    SELECT id, name, level, exp, <<EMPIRE>> AS empire
                    FROM player.player
                    WHERE <<RANKED_2>>
                    ORDER BY level DESC, exp DESC, id ASC
                    LIMIT %s
                """), (RANK_TOP,))
                for r in cur.fetchall():
                    rows.append({"name": panel.log_text(r.get("name")),
                                 "level": int(r.get("level") or 0),
                                 "exp": int(r.get("exp") or 0),
                                 "empire": int(r.get("empire") or 0)})
        except Exception:
            # Keep the last good list rather than blanking the box; retry
            # sooner than a full minute.
            _RANK["ts"] = now - 45
            return _RANK["rows"]
        _RANK.update(ts=now, rows=rows)
        return rows


_GRANK = {"ts": 0.0, "rows": []}
_GRANK_LOCK = threading.Lock()


def guild_ranking():
    """Top 100 guilds by wins -- main/guildrank.php's query. Cached like the
    player ranking. Never raises."""
    now = time.time()
    if now - _GRANK["ts"] < 60:
        return _GRANK["rows"]
    with _GRANK_LOCK:
        if now - _GRANK["ts"] < 60:
            return _GRANK["rows"]
        rows = []
        try:
            with panel.db() as c, c.cursor() as cur:
                cur.execute("SELECT name, win, draw, loss FROM player.guild "
                            "ORDER BY win DESC, draw DESC, loss ASC, name ASC LIMIT %s", (RANK_TOP,))
                for r in cur.fetchall():
                    rows.append({"name": panel.log_text(r.get("name")),
                                 "win": int(r.get("win") or 0),
                                 "draw": int(r.get("draw") or 0),
                                 "loss": int(r.get("loss") or 0)})
        except Exception:
            _GRANK["ts"] = now - 45
            return _GRANK["rows"]
        _GRANK.update(ts=now, rows=rows)
        return rows


def server_state():
    try:
        st = panel.server_status() or {}
        return bool(st.get("up")), int(st.get("count") or 0)
    except Exception:
        return False, 0


def account_chars(name):
    try:
        with panel.db() as c, c.cursor() as cur:
            cur.execute("SELECT id FROM account.account WHERE login=%s", (name,))
            acc = cur.fetchone()
            if not acc:
                return []
            cur.execute("SELECT name, job, level, gold FROM player.player "
                        "WHERE account_id=%s ORDER BY level DESC", (acc["id"],))
            return list(cur.fetchall())
    except Exception:
        return None


def admin_is_open():
    try:
        return bool(session.get("auth")) or bool(panel.local_open())
    except Exception:
        return bool(session.get("auth"))


# =============================================================================
#  Page pieces (template markup)
# =============================================================================
def _msgs(lang, ctx, where="main"):
    """Errors/successes as the template shows them (.error-mini / .success-msg)."""
    out = []
    for kind, text in ctx.get("msgs", []):
        if kind.get("where", "main") != where:
            continue
        cls = "error-mini" if kind["type"] == "error" else "front-ok"
        out.append('<div class="%s">%s</div>' % (cls, text))
    return "".join(out)


def _header(lang, ctx):
    who = ctx.get("player")
    if who:
        return """
			<div class="center">
				<div id="userBox">
					<br />
					<ul class="header-box-nav-login" style="margin-left:15px;">
						<li class="stepdown"><a href="%s" class="nav-box-btn nav-box-btn-2">%s</a></li>
						<li class="stepdown"><a href="%s" class="nav-box-btn nav-box-btn-3">%s</a></li>
						<li class="stepdown"><a href="%s" class="nav-box-btn nav-box-btn-4">%s</a></li>
					</ul>
				</div>
			</div>""" % (_u("account"), e("nav_account", lang), _u("pwchange"), e("nav_pw", lang),
                       escape(url_for("account_logout")), e("nav_logout", lang))
    return """
			<div class="header-box">
				<div id="regBtn">
					<a id="toReg" href="%s" title="%s">%s</a>
					<div id="regSteps">
						<a href="%s"><span>%s</span></a>
					</div>
				</div>
			</div>""" % (_u("register"), e("reg_banner", lang), e("reg_banner", lang),
                       _u("register"), s("reg_steps", lang))


def _langs(lang):
    out = ['<div class="front-langs">']
    for code, label in panel.LANGS.items():
        out.append('<a href="%s"%s>%s</a>' % (
            escape(url_for("setlang", code=code)),
            ' class="on"' if code == lang else "", escape(label)))
    out.append("</div>")
    return "".join(out)


def _menu(lang, ctx):
    items = [
        ("m_ban", ban_panel_url(request.host), True, False),
        ("m_discord", panel.DISCORD_URL, True, False),
        ("m_github", GITHUB_URL, True, False),
        ("m_map", MAP_URL, False, False),
        ("m_adminpw", url_for("front", s="admin"), False, ctx["page"] == "admin"),
    ]
    out = []
    for key, href, ext, active in items:
        out.append('<li%s><a href="%s"%s>%s</a></li>' % (
            ' class="active"' if active else "", escape(href),
            ' target="_blank" rel="noopener noreferrer"' if ext else "", e(key, lang)))
    return "\n".join(out)


def _right_top(lang, ctx):
    who = ctx.get("player")
    if who:
        chars = ctx.get("chars")
        n = len(chars) if chars is not None else "–"
        return """
				<div class="modul-box">
					<div class="modul-box-bg">
						<div class="modul-box-bg-bottom">
							<h3>%s</h3>
							<center>
								<br /><b>%s</b> <span class="offset">%s</span><br />
								<br /><b>%s</b> <span class="offset">%s</span><br />
								<br /><b>%s</b> <span class="offset">OK</span><br />
								<br /><a href="%s" class="btn">%s</a>
								<br />
							</center>
						</div>
					</div>
				</div>""" % (e("user_title", lang), e("user_hello", lang), escape(who),
                           e("user_chars", lang), n, e("user_status", lang),
                           escape(url_for("account_logout")), e("nav_logout", lang))
    return """
				<div class="modul-box">
					<div class="modul-box-bg">
						<div class="modul-box-bg-bottom">
							<h3>%s</h3>
							<form action="%s" method="post" id="frontLogin">
								%s
								<input type="hidden" name="action" value="login" />
								<div class="form-login">
									%s
									<label for="loginUser">&nbsp;%s</label>
									<div class="input">
										<input type="text" id="loginUser" name="user" maxlength="16" value="%s" autocomplete="username" required />
									</div>
									<label for="loginPw">&nbsp;%s</label>
									<div class="input">
										<input type="password" id="loginPw" name="pw" maxlength="16" autocomplete="current-password" required />
									</div>
									<div>
										<input type="submit" class="button btn-login" value="%s" />
										<p class="agbok">%s <a href="%s" target="_blank"><strong>%s</strong></a>.
										<a href="%s" class="password">%s</a></p>
									</div>
								</div>
							</form>
						</div>
					</div>
				</div>""" % (
        e("login_title", lang), _u(ctx["page"]), _csrf(),
        _msgs(lang, ctx, "login"),
        e("login_user", lang), escape(ctx.get("login_name", "")),
        e("login_pw", lang), e("login_btn", lang),
        e("login_terms", lang), escape(url_for("imprint")), e("terms", lang),
        _u("register"), e("login_noacc", lang))


def _ranking_box(lang, ctx):
    rows = ranking()
    if rows:
        items = []
        for i, r in enumerate(rows, 1):
            emp = r["empire"] if r["empire"] in (1, 2, 3) else 0
            items.append(
                '<li%s><div class="%s" title="%s %s">'
                '<strong class="offset">%d</strong> - <span class="rk-name">%s</span>'
                '<span class="rk-lv">%s</span></div></li>' % (
                    ' class="light"' if i % 2 == 0 else "",
                    "empire%d" % emp if emp else "empire0",
                    escape(r["name"]), "(Lv %d)" % r["level"], i,
                    escape(r["name"]), r["level"]))
        body = "<div class='form-score'><div class='highscore-player'><ul>%s</ul></div></div>" % "".join(items)
    else:
        body = "<div class='form-score'><p class='rk-empty'>%s</p></div>" % e("rank_empty", lang)
    return """
				<div class="modul-box modul-box-2">
					<div class="modul-box-bg">
						<div class="modul-box-bg-bottom">
							<h3>%s</h3>
							%s
							<center>
								<a href="%s" class="btn">%s</a>
							</center>
							<br />
						</div>
					</div>
				</div>""" % (e("rank_title", lang), body, _u("rankings"), e("rank_more", lang))


# ---- col-2 pages -------------------------------------------------------------
def page_home(lang, ctx):
    up, count = server_state()
    shots = "".join(
        '<li%s><a href="/static/cms/img/screenshots/mmorpg-fantasy-metin2-screenshot%d.jpg">'
        '<img alt="%s" src="/static/cms/img/screenshots/mmorpg-fantasy-metin2-thumb%d.jpg" width="100" height="75" /></a></li>'
        % (' class="first"' if n in (1, 5) else "", n, escape(s("shot_alt", lang) % n), n) for n in range(1, 9))
    feats = "".join("<li>%s</li>" % e("about_f%d" % n, lang) for n in range(1, 6))
    state = ('<span class="srv-on">%s</span>' % e("srv_on", lang)) if up else (
        '<span class="srv-off">%s</span>' % e("srv_off", lang))
    return """
<div class="two-boxes">
	<div class="two-boxes-top">
		<div class="two-boxes-bottom">
			<div class="box">
				<h2>%(b1)s</h2>
				<div class="body">
					<p><b>%(welcome)s</b></p>
					<p>%(lead)s</p>
					<p>%(p1)s</p>
				</div>
			</div>
			<div class="box box-right">
				<h2>%(b2)s</h2>
				<div class="body front-status">
					<p>%(st_l)s %(state)s</p>
					<p>%(pl_l)s <b>%(count)s</b></p>
					<p><a href="%(map)s">&raquo; %(map_l)s</a></p>
					<p><a href="%(reg)s">&raquo; %(reg_l)s</a></p>
				</div>
			</div>
		</div>
	</div>
</div>
<div class="content">
	<div class="content-bg">
		<div class="content-bg-bottom">
			<h2>%(screens)s</h2>
			<ul class="screenshots">%(shots)s</ul>
		</div>
	</div>
</div>
<div class="shadow">&nbsp;</div>
<div class="content content-last">
	<div class="content-bg">
		<div class="content-bg-bottom">
			<h2>%(about)s</h2>
			<div class="inner-content">
				<p>%(lead)s</p>
				<h3>%(feat_h)s</h3>
				<ul style="padding-bottom: 0px">%(feats)s</ul>
				<p>%(p2)s</p>
				<p>%(p3)s</p>
			</div>
		</div>
	</div>
</div>
<div class="shadow">&nbsp;</div>""" % {
        "b1": e("home_box1", lang), "welcome": e("home_welcome", lang),
        "lead": e("about_lead", lang), "p1": e("about_p1", lang),
        "b2": e("home_box2", lang), "st_l": e("srv_state", lang), "state": state,
        "pl_l": e("srv_players", lang), "count": count if up else 0,
        "map": escape(MAP_URL), "map_l": e("srv_map", lang),
        "reg": _u("register"), "reg_l": e("reg_banner", lang),
        "screens": e("screens", lang), "shots": shots,
        "about": e("about_h2", lang), "feat_h": e("about_features_h", lang),
        "feats": feats, "p2": e("about_p2", lang), "p3": e("about_p3", lang)}


def _form_page(h2, inner):
    return """
<div id="register">
	<div class="content content-last">
		<div class="content-bg">
			<div class="content-bg-bottom">
				<h2>%s</h2>
				<div class="inner-form-border">
					<div class="inner-form-box">
%s
					</div>
				</div>
			</div>
		</div>
	</div>
</div>
<div class="shadow">&nbsp;</div>""" % (h2, inner)


def page_register(lang, ctx):
    inner = """
						<h3><a id="toLogin" href="#loginUser" title="%(tologin)s">%(tologin)s</a>%(h3)s</h3>
						<div class="trenner"></div>
						%(msgs)s
						<form id="form2" name="form2" method="post" action="%(action)s">
							%(csrf)s
							<input type="hidden" name="action" value="register" />
							<div class="center">
								<div class="form-item">
									<label for="UserID">%(l_user)s</label>
									<input name="user" type="text" id="UserID" minlength="4" maxlength="16" size="16" value="%(name)s" autocomplete="username" required />
								</div>
								<div class="form-item">
									<label for="Password">%(l_pw)s</label>
									<input name="pw" type="password" id="Password" minlength="6" maxlength="16" size="16" autocomplete="new-password" required />
								</div>
								<div class="form-item">
									<label for="DeleteCode">%(l_code)s</label>
									<input name="code" type="text" id="DeleteCode" minlength="7" maxlength="7" size="7" pattern="[0-9]{7}" inputmode="numeric" value="%(code)s" autocomplete="off" required />
								</div>
								<br />
								<input id="submitBtn" type="submit" value="%(btn)s" class="btn-big" />
							</div>
						</form>
						<p id="regLegend" align="left">%(legend)s<a href="%(terms_url)s" target="_blank"><strong>%(terms)s</strong></a>!</p>""" % {
        "tologin": e("reg_tologin", lang), "h3": e("reg_h3", lang),
        "msgs": _msgs(lang, ctx), "action": _u("register"), "csrf": _csrf(),
        "l_user": e("reg_user", lang), "name": escape(ctx.get("reg_name", "")),
        "l_pw": e("reg_pw", lang), "l_code": e("reg_code", lang),
        "code": escape(ctx.get("reg_code", "")),
        "btn": e("reg_btn", lang), "legend": s("reg_legend", lang),
        "terms_url": escape(url_for("imprint")), "terms": e("terms", lang)}
    return _form_page(e("reg_h2", lang), inner)


def _need_login(lang, ctx, h2):
    return _form_page(e(h2, lang), '<div class="trenner"></div>%s<p class="front-center">%s</p>'
                      % (_msgs(lang, ctx), e("need_login", lang)))


def page_account(lang, ctx):
    who = ctx.get("player")
    if not who:
        return _need_login(lang, ctx, "acc_h2")
    chars = ctx.get("chars")
    if chars is None:
        table = '<div class="error-mini">%s</div>' % e("err_db", lang)
    elif not chars:
        table = '<p class="front-center">%s</p>' % e("acc_none", lang)
    else:
        rows = []
        for i, ch in enumerate(chars):
            rows.append('<tr%s><td>%s %s</td><td>%s</td><td>%s</td></tr>' % (
                ' class="light"' if i % 2 else "",
                panel.JOB_EMOJI.get(ch.get("job"), ""),
                escape(panel.log_text(ch.get("name"))),
                int(ch.get("level") or 0),
                "{:,}".format(int(ch.get("gold") or 0)).replace(",", " ")))
        table = ('<table class="front-chars"><tr><th>%s</th><th>%s</th><th>%s</th></tr>%s</table>'
                 % (e("col_name", lang), e("col_lv", lang), e("col_gold", lang), "".join(rows)))
    play = ""
    try:
        if panel.browser_play_ready():
            play = ('<p class="front-btns"><a class="btn" href="%s" target="_blank" rel="noopener">%s</a></p>'
                    % (escape(panel.play_url()), e("acc_play", lang)))
    except Exception:
        play = ""
    inner = """
						<h3>%s</h3>
						<div class="trenner"></div>
						%s
						<h4 class="front-h4">%s</h4>
						%s
						%s
						<p class="front-btns"><a class="btn" href="%s">%s</a><a class="btn" href="%s">%s</a></p>""" % (
        escape(who), _msgs(lang, ctx), e("acc_chars", lang), table, play,
        _u("pwchange"), e("nav_pw", lang), escape(url_for("account_logout")), e("nav_logout", lang))
    return _form_page(e("acc_h2", lang), inner)


def page_pwchange(lang, ctx):
    if not ctx.get("player"):
        return _need_login(lang, ctx, "pw_h2")
    inner = """
						<div class="trenner"></div>
						%s
						<div class="center">
							<form action="%s" method="post">
								%s
								<input type="hidden" name="action" value="password" />
								<div class="form-item">
									<label for="pwOld">%s</label>
									<input type="password" id="pwOld" name="old" maxlength="16" size="16" autocomplete="current-password" required />
								</div>
								<div class="form-item">
									<label for="pwNew">%s</label>
									<input type="password" id="pwNew" name="new" minlength="6" maxlength="16" size="16" autocomplete="new-password" required />
								</div>
								<div class="form-item">
									<label for="pwNew2">%s</label>
									<input type="password" id="pwNew2" name="new2" minlength="6" maxlength="16" size="16" autocomplete="new-password" required /><br /><br />
								</div>
								<input id="submitBtn" class="btn-big" type="submit" value="%s" />
							</form>
						</div>""" % (_msgs(lang, ctx), _u("pwchange"), _csrf(),
                                     e("pw_old", lang), e("pw_new", lang), e("pw_new2", lang),
                                     e("pw_btn", lang))
    return _form_page(e("pw_h2", lang), inner)


def page_admin(lang, ctx):
    note = '<div class="front-note"><p>%s</p></div>' % e("adm_note", lang)
    if admin_is_open():
        text = e("adm_in", lang) if session.get("auth") else e("adm_open", lang)
        body = ('<p class="front-center">%s</p><br /><div class="center">'
                '<a class="btn-big front-btn-link" href="%s">%s</a></div>'
                % (text, escape(url_for("dash")), e("adm_go", lang)))
    else:
        body = """
						<div class="center">
							<form action="%s" method="post">
								%s
								<div class="form-item">
									<label for="admPw">%s</label>
									<input type="password" id="admPw" name="pw" size="16" autocomplete="current-password" required />
								</div>
								<br />
								<input id="submitBtn" class="btn-big" type="submit" value="%s" />
							</form>
						</div>""" % (escape(url_for("login")), _csrf(), e("adm_pw", lang), e("adm_btn", lang))
    inner = """
						<h3>%s</h3>
						<div class="trenner"></div>
						%s
						%s
						%s""" % (e("adm_h3", lang), _msgs(lang, ctx), body, note)
    return _form_page(e("adm_h2", lang), inner)


def _num(n):
    return "{:,}".format(int(n)).replace(",", " ")


def _rank_page(lang, h2, head, rows, other_page, other_label):
    """main/rankings.php and main/guildrank.php: one table, a button to the other."""
    if rows:
        table = '<table class="front-rank"><tr>%s</tr>%s</table>' % (
            "".join("<th>%s</th>" % h for h in head), "".join(rows))
    else:
        table = '<p class="front-center">%s</p>' % e("rank_empty", lang)
    return """
<div class="content content-last">
	<div class="content-bg">
		<div class="content-bg-bottom">
			<h2>%s</h2>
			<div id="ranking">
				<br />
				%s
				<br />
			</div>
			<center><strong><a class="btn" href="%s">%s</a></strong><br /></center>
			<br class="clearfloat" />
		</div>
	</div>
</div>
<div class="shadow">&nbsp;</div>""" % (h2, table, _u(other_page), other_label)


def page_rankings(lang, ctx):
    rows = []
    for i, r in enumerate(_ranking_all(), 1):
        emp = r["empire"] if r["empire"] in (1, 2, 3) else 0
        flag = ('<img src="/static/cms/img/%d_kl.jpg" alt="%d" />' % (emp, emp)) if emp else "&ndash;"
        rows.append('<tr%s><td>%d</td><td class="rk-n">%s</td><td>%d</td><td>%s</td><td>%s</td></tr>' % (
            ' class="light"' if i % 2 == 0 else "", i, escape(r["name"]),
            r["level"], _num(r["exp"]), flag))
    head = [e(k, lang) for k in ("rk_pos", "rk_name", "rk_level", "rk_exp", "rk_empire")]
    return _rank_page(lang, e("rk_h2", lang), head, rows, "guildrank", e("gr_link", lang))


def page_guildrank(lang, ctx):
    rows = []
    for i, g in enumerate(guild_ranking(), 1):
        rows.append('<tr%s><td>%d</td><td class="rk-n">%s</td><td>%d</td><td>%d</td><td>%d</td></tr>' % (
            ' class="light"' if i % 2 == 0 else "", i, escape(g["name"]),
            g["win"], g["draw"], g["loss"]))
    head = [e(k, lang) for k in ("rk_pos", "rk_name", "gr_win", "gr_draw", "gr_loss")]
    return _rank_page(lang, e("gr_h2", lang), head, rows, "rankings", e("rk_link", lang))


PAGE_FUNCS = {"home": page_home, "register": page_register, "account": page_account,
              "pwchange": page_pwchange, "admin": page_admin,
              "rankings": page_rankings, "guildrank": page_guildrank}


def _footer(lang):
    up, count = server_state()
    if up:
        state = '<b class="srv-on">%s</b> &nbsp;&bull;&nbsp; %d %s' % (e("foot_on", lang), count, e("foot_players", lang))
    else:
        state = '<b class="srv-off">%s</b>' % e("foot_off", lang)
    return """
<div class="footer-wrapper">
	<div id="footer">
		<ul>
			<li class="first">%s<br />%s &copy; Metin2 Playerbots — Tieru<br />%s: ĹŌŞƬĒĶ (l0st3k)<br />CC BY-NC-ND 4.0 — %s &nbsp;&bull;&nbsp; <a href="%s">%s</a></li>
		</ul>
	</div>
</div>
<dialog id="gallery"><button type="button" aria-label="%s">×</button><img alt="" /></dialog>""" % (
        state, e("foot_hobby", lang), e("cms_credit", lang), e("license_extra", lang),
        escape(url_for("imprint")), e("legal", lang), e("close", lang))


_HEAD = """<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
		<title>%(title)s</title>
		<meta name="description" content="%(title)s" />
		<link rel="shortcut icon" href="/favicon.ico" type="image/x-icon" />
		<link href="/static/cms/css/reset.css" rel="stylesheet" type="text/css" media="all" />
		<link href="/static/cms/css/all.css" rel="stylesheet" type="text/css" media="all" />
		<link href="/static/cms/css/plugins.css" rel="stylesheet" type="text/css" media="screen" />
		<link href="/static/cms/css/front.css?v=5" rel="stylesheet" type="text/css" media="all" />"""

_SCRIPT = """
<script type="text/javascript">
const gallery = document.getElementById('gallery');
if (gallery && typeof gallery.showModal === 'function') {
    document.querySelectorAll('ul.screenshots a').forEach(link => {
        link.addEventListener('click', event => {
            event.preventDefault();
            gallery.querySelector('img').src = link.href;
            gallery.querySelector('img').alt = link.querySelector('img').alt;
            gallery.showModal();
        });
    });
    gallery.querySelector('button').addEventListener('click', () => gallery.close());
}
const toLogin = document.getElementById('toLogin');
if (toLogin) toLogin.addEventListener('click', event => {
    const input = document.getElementById('loginUser');
    if (input) { event.preventDefault(); input.focus(); }
});
</script>"""


def render(lang, ctx):
    page = ctx["page"]
    centre = PAGE_FUNCS[page](lang, ctx)
    html = """<!DOCTYPE html>
<html lang="%(lang)s">
	<head>
		%(head)s
	</head>
	<body>
<div id="page">
	<div class="header-wrapper">
		<div id="header">
			<a class="logo" href="%(home)s"><strong>Metin2</strong></a>
			%(langs)s
			%(header)s
		</div>
	</div>
	<div class="container-wrapper">
		<div class="container">
			<!-- COL1 -->
			<div class="col-1">
				<div class="boxes-top">&nbsp;</div>
				<div class="modul-box">
					<div class="modul-box-bg">
						<div class="modul-box-bg-bottom">
							<ul class="main-nav">
%(menu)s
							</ul>
						</div>
					</div>
				</div>
				<div class="boxes-middle">&nbsp;</div>
				<div class="modul-box modul-box-2">
					<div class="modul-box-bg">
						<div class="modul-box-bg-bottom">
							<ul class="main-nav" style="padding-bottom: 0px;">
								<li><a href="%(dl)s">%(dl_t)s</a></li>
							</ul>
							<a href="%(dl)s" class="btn download-btn"></a>
						</div>
					</div>
				</div>
				<div class="boxes-bottom">&nbsp;</div>
			</div>
			<!-- COL2 -->
			<div class="col-2">
%(flash)s
%(centre)s
			</div>
			<!-- COL3 -->
			<div class="col-3">
				<div class="boxes-top">&nbsp;</div>
%(right_top)s
				<div class="boxes-middle">&nbsp;</div>
%(ranking)s
				<div class="boxes-bottom">&nbsp;</div>
			</div>
		</div>
	</div>
</div>
%(footer)s
%(script)s
	</body>
</html>""" % {
        "lang": escape(lang),
        "head": _HEAD % {"title": escape("%s — %s" % (s("title", lang), panel.BRAND))},
        "home": _u(),
        "langs": _langs(lang),
        "header": _header(lang, ctx),
        "menu": _menu(lang, ctx),
        "dl": escape(url_for("download")), "dl_t": e("dl_title", lang),
        "flash": _msgs(lang, ctx, "flash"),
        "centre": centre,
        "right_top": _right_top(lang, ctx),
        "ranking": _ranking_box(lang, ctx),
        "footer": _footer(lang),
        "script": _SCRIPT,
    }
    return html


# =============================================================================
#  Form handling
# =============================================================================
def _add(ctx, kind, html, where="main"):
    ctx["msgs"].append(({"type": kind, "where": where}, html))


def do_login(lang, ctx):
    """Same check as the panel's /account (m2_hash, same rate-limit bucket)."""
    name = str(request.form.get("user") or "").strip()
    pw = str(request.form.get("pw") or "")
    ctx["login_name"] = name
    if panel.rate_limited("acclogin", 8, 900):
        _add(ctx, "error", e("err_rate_login", lang), "login")
        return None
    try:
        with panel.db() as c, c.cursor() as cur:
            cur.execute("SELECT login, password FROM account.account WHERE login=%s", (name,))
            row = cur.fetchone()
    except Exception:
        _add(ctx, "error", e("err_db", lang), "login")
        return None
    if row and hmac.compare_digest(str(row["password"]), panel.m2_hash(pw)):
        return row["login"]
    time.sleep(1.0)
    _add(ctx, "error", e("err_login", lang), "login")
    return None


def do_register(lang, ctx):
    """Same rules and same INSERT as the panel's /register, minus the password
    confirmation; the delete code goes to social_id."""
    name = str(request.form.get("user") or "").strip()
    pw = str(request.form.get("pw") or "")
    code = str(request.form.get("code") or "").strip()
    ctx["reg_name"], ctx["reg_code"] = name, code
    if panel.rate_limited("register", 3, 3600):
        _add(ctx, "error", e("err_rate_reg", lang))
        return None
    if not panel.valid_account_login(name):
        _add(ctx, "error", e("err_name", lang))
        return None
    if len(pw) < 6:
        _add(ctx, "error", e("err_pw_short", lang))
        return None
    if len(pw) > 16:
        _add(ctx, "error", e("err_pw_long", lang))
        return None
    if not panel.valid_account_password(pw):
        _add(ctx, "error", e("err_pw_chars", lang))
        return None
    if not panel.valid_deletion_code(code):
        _add(ctx, "error", e("err_code", lang))
        return None
    try:
        with panel.db() as c, c.cursor() as cur:
            cur.execute("SELECT 1 FROM account.account WHERE login=%s", (name,))
            if cur.fetchone():
                _add(ctx, "error", e("err_taken", lang))
                return None
            cur.execute("INSERT INTO account.account (login,password,social_id,status) "
                        "VALUES (%s,%s,%s,'OK')", (name, panel.m2_hash(pw), code))
    except Exception:
        _add(ctx, "error", e("err_create", lang))
        return None
    return name


def do_password(lang, name):
    if panel.rate_limited("accpassword", 5, 900):
        return "error", e("err_rate_login", lang)
    old = str(request.form.get("old") or "")
    new = str(request.form.get("new") or "")
    new2 = str(request.form.get("new2") or "")
    if len(new) < 6:
        return "error", e("err_pw_short", lang)
    if len(new) > 16:
        return "error", e("err_pw_long", lang)
    if not panel.valid_account_password(new):
        return "error", e("err_pw_chars", lang)
    if new != new2:
        return "error", e("pw_diff", lang)
    try:
        with panel.db() as c, c.cursor() as cur:
            cur.execute("SELECT password FROM account.account WHERE login=%s", (name,))
            row = cur.fetchone()
            if row and hmac.compare_digest(str(row["password"]), panel.m2_hash(old)):
                cur.execute("UPDATE account.account SET password=%s WHERE login=%s",
                            (panel.m2_hash(new), name))
                return "ok", e("pw_ok", lang)
    except Exception:
        return "error", e("err_db", lang)
    time.sleep(1.0)
    return "error", e("pw_bad", lang)


def front():
    lang = panel.lang()
    page = request.args.get("s", "home")
    if page not in PAGES:
        page = "home"
    ctx = {"page": page, "msgs": [], "login_name": "", "reg_name": "", "reg_code": ""}

    if request.method == "POST":
        # csrf_protect() (before_request) has already refused a bad token.
        action = str(request.form.get("action") or "").lower()
        if action == "register":
            who = do_register(lang, ctx)
            if who:
                session["player"] = who
                session["front_note"] = ("ok", s("ok_created", lang) % escape(who))
                return redirect(url_for("front", s="account"))
            ctx["page"] = "register"
        elif action == "password":
            if session.get("player"):
                session["front_note"] = do_password(lang, session["player"])
                return redirect(url_for("front", s="pwchange"))
        elif action == "login":
            who = do_login(lang, ctx)
            if who:
                session["player"] = who
                return redirect(url_for("front", s="account"))

    note = session.pop("front_note", None)
    if note:
        _add(ctx, note[0], note[1])
    # Messages flashed by the rest of the panel (e.g. a wrong admin password,
    # a download that is not ready) land at the top of the centre column.
    for cat, msg in get_flashed_messages(with_categories=True):
        _add(ctx, "error" if cat == "error" else "ok", str(escape(msg)),
             "main" if ctx["page"] == "admin" else "flash")

    who = session.get("player")
    if who:
        ctx["player"] = who
        ctx["chars"] = account_chars(who)
    # Not render_template_string: the page is finished HTML and must not be
    # run through Jinja, where a "{{" in a character name would be code.
    resp = Response(render(lang, ctx), mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def imprint():
    return send_from_directory(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"),
                               "imprint.html")


class _PanelNamespace:
    """Read the live module namespace, including DB stubs used by tests."""
    def __init__(self, namespace):
        self.namespace = namespace

    def __getattr__(self, name):
        return self.namespace[name]


def init(module):
    """Called once from the bottom of admin_panel.py."""
    global panel
    panel = _PanelNamespace(module) if isinstance(module, dict) else module
    panel.app.add_url_rule("/", "front", front, methods=["GET", "POST"])
    panel.app.add_url_rule("/imprint", "imprint", imprint)
