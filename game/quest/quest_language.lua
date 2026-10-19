-- The package's quests in the language each player reads.
--
-- The stock quests speak through three tables the cores load at boot: the
-- share's translate.lua (`gameforge.<quest>.<key>`), quest/locale.lua (the
-- `locale` table, made of gameforge.locale.* when it loads) and
-- quest/libs/translate/translate.lua (the package's own `translate`). A quest
-- looks its text up while it runs - `say(gameforge.arena_manager._30_say)`, an
-- NPC's option when the NPC is clicked (NPC::OnChat runs the .arg file's
-- expression then) - so a table whose fields answer each reader in its own
-- language is a quest in each reader's language, and not one quest has to be
-- compiled again.
--
-- The English is quest_texts_en.lua, rendered by
-- tools/generate_quest_english.py: Gameforge's English wherever this world's
-- Polish is Gameforge's Polish, and the hand translations of
-- data/quest_texts_untranslated.tsv. Each text names the Polish it translates
-- (its length and MySQL's PASSWORD() hash of it, which the engine computes as
-- mysql_password), and a text whose Polish has changed since is left out: that
-- key is Polish again rather than an English of something else.
--
-- The image runs this at the end of quest/locale.lua (port/shareify.py), the
-- last file the cores load before the quests, so every table is there. Then:
--   * gameforge and translate get an English twin of every table the English
--     reaches into, which falls back to the Polish table for everything else;
--   * locale.lua runs a second time with the English gameforge in place, and
--     that is the English locale;
--   * every top-level field of the three that differs between the two
--     languages leaves its table and is answered by the table's __index: the
--     Polish, or the English for a character whose client reads English -
--     pc.getf("playerbot_lang", "en"), the flag playerbot_lang.quest's
--     question leaves (playerbot_language.h). A field that does not differ is
--     where it was, so nothing without an English text changes at all.
-- A quest running for nobody (a server timer runs for the character "0", and
-- nothing runs at boot) reads Polish, and so does a bot. A field is asked who
-- reads it only while a quest runs, which is when the engine keeps its current
-- character: the monsters' chatter (CHARACTER::MonsterChat evaluates
-- locale.monster_chat outside any quest, for everybody around) is the same
-- table in both languages and stays a plain field, and its English twin is the
-- plain field locale.monster_chat_en beside it, which the engine reads for a
-- viewer who reads English (playerbotify.py, apply_monster_chat_in).
--
-- A quest also says things to other people than the one it runs for, and a
-- Polish reader must never be handed English because an English reader set
-- it off. The broadcasts are wrapped for that: notice_all and big_notice_all
-- go out as two notices, a half per language behind the marks every core
-- hands each player its own of (CPlayerBotManager::ShowsNoticeTo), and
-- d.notice as d.notice_in, the engine's dungeon notice in each member's own
-- language (playerbotify.py, apply_dungeon_notice_in). A broadcast the engine
-- cannot split - a map's notice, a party's chat, an NPC saying something
-- aloud - is said in Polish. The text is found again by what it is: the one
-- key's Polish or English as it is, or through string.format around the same
-- values; a text that is neither (a name, one of our own lines) goes out as
-- it came.
--
-- And a quest's picture of an item is captioned in its reader's language:
-- say_item_vnum's caption is the proto's Polish (get_item_name), so a reader
-- of English is given the item's official English name (get_item_name_en).
--
-- Anything that goes wrong in here leaves the tables as the package made
-- them: every table is built aside first and put in place last, and the hook
-- in locale.lua calls this through pcall.
--
-- Turkish (tr-build, the Turkish overlay): quest_texts_tr.lua, the same
-- layout as the English file, holds Gameforge's official Turkish of the stock
-- quests, a hand translation of the rest and of the package's own translate
-- table, and the official Turkish item names for say_item_vnum. A reader
-- whose client names Turkish - pc.getf("playerbot_lang", "code") == 6, the
-- fourth word "langtr" of /playerbot_lang - reads a third twin, made over the
-- English twin, so a text without Turkish is the English one and a text
-- without either is the Polish. The broadcasts give a Turkish text back its
-- Polish and English halves; the engine hands a Turkish reader the English
-- half (it knows two). A missing or broken quest_texts_tr.lua, or anything
-- going wrong while the Turkish twin is built, leaves the English as it was.
-- Each core writes what it loaded to quest_language_status.tsv in its folder.

quest_language = {
	loaded = false,
	-- English texts in force, and those left out for a Polish changed since.
	english = 0,
	stale = 0,
	-- Top-level fields that answer in the reader's language.
	fields = 0,
	-- The same for Turkish, and the item captions it has.
	turkish = 0,
	turkish_stale = 0,
	turkish_items = 0,
}

local QL = quest_language
local MARK_POLISH = string.char(1)
local MARK_ENGLISH = string.char(2)

-- pc.getf gives nothing at all while no character is current, and so the
-- answer is Polish then.
local getf = pc.getf

-- playerbot_engine_text::EReaderLanguage: 0 pl, 1 en, 2 de, 3 fr, 4 pt, 5 ro,
-- 6 tr, 7 es, 8 it. The quests know three: Polish, English (every code past
-- Polish but Turkish) and Turkish.
local TURKISH = 6

-- The boot's self-test pretends a reader here (0, 1 or TURKISH); nil the rest
-- of the time.
local TEST_READER = nil

local function reader_code()
	if TEST_READER ~= nil then
		return TEST_READER
	end
	if getf("playerbot_lang", "en") ~= 1 then
		return 0
	end
	if getf("playerbot_lang", "code") == TURKISH then
		return TURKISH
	end
	return 1
end

local function reads_english()
	return reader_code() ~= 0
end
QL.reads_english = reads_english

local function reads_turkish()
	return reader_code() == TURKISH
end
QL.reads_turkish = reads_turkish

-- Our own quests' texts in the languages past English (Tyrion, 16 October):
-- quest/playerbot_quest_texts.lua is his table of the English of every
-- t(pl, en) of our quests with its de, fr, pt and ro. A quest's t() answers a
-- reader of English with playerbot_quest_text(en): the English's translation
-- in the language the reader's client named - pc.getf("playerbot_lang",
-- "code"), playerbot_engine_text::EReaderLanguage (playerbot_language.h) -
-- and the English itself for every other reader, every text the table lacks
-- and every core that could not read the table. Here, beside the English
-- switch, because this file is what the cores load before the quests; the
-- table is read through pcall, so a broken file leaves the English.
local QUEST_TEXT_LANGUAGES = { [2] = "de", [3] = "fr", [4] = "pt", [5] = "ro", [6] = "tr" }

function playerbot_quest_text(en)
	local texts = playerbot_quest_texts
	local row = texts ~= nil and texts[en] or nil
	if row == nil then
		return en
	end
	local language = QUEST_TEXT_LANGUAGES[getf("playerbot_lang", "code")]
	if language == nil or row[language] == nil then
		return en
	end
	return row[language]
end

if playerbot_quest_texts == nil then
	pcall(dofile, LIBDIR .. "other/playerbot_quest_texts.lua")
end

-- ------------------------------------------------------------------ the data

-- Whether a Polish text is still the one an English text was made for:
-- "<bytes>:<the first eight hex digits after the '*' of PASSWORD()>". Without
-- the engine's hash (a core built without it) the length decides alone.
local function same_polish(text, sig)
	local _, _, len, digest = string.find(sig, "^(%d+):(%x*)$")
	if len == nil or string.len(text) ~= tonumber(len) then
		return false
	end
	if digest == "" or type(mysql_password) ~= "function" then
		return true
	end
	local h = mysql_password(text)
	return type(h) == "string" and string.sub(h, 2, 9) == digest
end

local function split_path(path)
	local parts = {}
	for part in string.gfind(path, "[^%.]+") do
		if string.find(part, "^%d+$") then
			part = tonumber(part)
		end
		table.insert(parts, part)
	end
	return parts
end

-- An English twin: its own fields are English, anything else is the Polish
-- table's. A list keeps its Polish items as its own too: Lua 5.0's
-- table.getn, ipairs and unpack read a table raw, and a twin with English for
-- its second item alone would count as empty (a select_table of options, a
-- random line of an NPC's). build() writes over the items it has English for.
local function twin(polish)
	local t = {}
	for i = 1, table.getn(polish) do
		t[i] = rawget(polish, i)
	end
	setmetatable(t, { __index = polish })
	return t
end

-- ------------------------------------------------------ finding a text again

local EN_TO_PL = {}
local PL_TO_EN = {}
local FORMAT_SOURCES = {}
local FORMATS = nil

local function add_pair(pl, en, broadcast)
	if pl == en then
		return
	end
	if EN_TO_PL[en] == nil then
		EN_TO_PL[en] = pl
	end
	if PL_TO_EN[pl] == nil then
		PL_TO_EN[pl] = en
	end
	if string.find(pl, "%", 1, true) then
		table.insert(FORMAT_SOURCES, { pl, en, broadcast })
	end
end

-- The same for the Turkish twin: a Turkish text finds its Polish, and the
-- Polish its English (PL_TO_EN) for the English half of a broadcast.
local TR_TO_PL = {}
local TR_FORMAT_SOURCES = {}
local TR_FORMATS = nil

local function add_pair_tr(pl, tr, broadcast)
	if pl == tr then
		return
	end
	if TR_TO_PL[tr] == nil then
		TR_TO_PL[tr] = pl
	end
	if string.find(pl, "%", 1, true) then
		table.insert(TR_FORMAT_SOURCES, { pl, tr, broadcast })
	end
end

local function escape(text)
	return (string.gsub(text, "([%^%$%(%)%%%.%[%]%*%+%-%?])", "%%%1"))
end

-- A format string as Lua 5.0's string.format reads it: the literal pieces
-- around its conversions and a pattern that finds the values again; nil for a
-- text string.format would refuse, which no quest formats.
local function template(fmt)
	local lits, pat, lit = {}, "^", ""
	local i, n, conversions = 1, string.len(fmt), 0
	while i <= n do
		local p = string.find(fmt, "%", i, true)
		if p == nil then
			lit = lit .. string.sub(fmt, i)
			break
		end
		lit = lit .. string.sub(fmt, i, p - 1)
		if string.sub(fmt, p + 1, p + 1) == "%" then
			lit = lit .. "%"
			i = p + 2
		else
			local _, e, spec = string.find(fmt, "^%%[%-%+ #0]*%d?%d?%.?%d?%d?([cdiouxXeEfgGqs])", p)
			if e == nil then
				return nil
			end
			table.insert(lits, lit)
			if spec == "d" or spec == "i" then
				pat = pat .. escape(lit) .. "(%-?%d+)"
			else
				pat = pat .. escape(lit) .. "(.-)"
			end
			lit = ""
			conversions = conversions + 1
			i = e + 1
		end
	end
	table.insert(lits, lit)
	return lits, pat .. escape(lit) .. "$", conversions
end

-- A template of nothing but a value finds everything; it takes some words.
local function worded(lits)
	return string.len(string.gsub(table.concat(lits, ""), "%s", "")) >= 4
end

local function formats()
	if FORMATS ~= nil then
		return FORMATS
	end
	FORMATS = {}
	local later = {}
	for i = 1, table.getn(FORMAT_SOURCES) do
		local src = FORMAT_SOURCES[i]
		local pl_lits, pl_pat, pl_n = template(src[1])
		local en_lits, en_pat, en_n = template(src[2])
		if pl_lits ~= nil and en_lits ~= nil and pl_n > 0 and pl_n == en_n
				and worded(pl_lits) and worded(en_lits) then
			local f = { pl_lits = pl_lits, pl_pat = pl_pat, en_lits = en_lits, en_pat = en_pat }
			-- The texts the quests broadcast first; the rest behind them.
			if src[3] then
				table.insert(FORMATS, f)
			else
				table.insert(later, f)
			end
		end
	end
	for i = 1, table.getn(later) do
		table.insert(FORMATS, later[i])
	end
	return FORMATS
end

-- The Turkish templates, each with the English template of its Polish (the
-- first one formats() keeps, as PL_TO_EN keeps the first English), so a
-- Turkish text's values go into its Polish and its English half.
local function tr_formats()
	if TR_FORMATS ~= nil then
		return TR_FORMATS
	end
	local english = {}
	for i = 1, table.getn(FORMAT_SOURCES) do
		local src = FORMAT_SOURCES[i]
		if english[src[1]] == nil then
			local en_lits, en_pat, en_n = template(src[2])
			if en_lits ~= nil then
				english[src[1]] = { en_lits, en_n }
			end
		end
	end
	TR_FORMATS = {}
	local later = {}
	for i = 1, table.getn(TR_FORMAT_SOURCES) do
		local src = TR_FORMAT_SOURCES[i]
		local pl_lits, pl_pat, pl_n = template(src[1])
		local tr_lits, tr_pat, tr_n = template(src[2])
		if pl_lits ~= nil and tr_lits ~= nil and pl_n > 0 and pl_n == tr_n
				and worded(pl_lits) and worded(tr_lits) then
			local f = { pl_lits = pl_lits, tr_lits = tr_lits, tr_pat = tr_pat }
			local en = english[src[1]]
			if en ~= nil and en[2] == pl_n then
				f.en_lits = en[1]
			end
			if src[3] then
				table.insert(TR_FORMATS, f)
			else
				table.insert(later, f)
			end
		end
	end
	for i = 1, table.getn(later) do
		table.insert(TR_FORMATS, later[i])
	end
	return TR_FORMATS
end

local function fill(lits, found)
	local out = lits[1]
	for i = 2, table.getn(lits) do
		out = out .. found[i + 1] .. lits[i]
	end
	return out
end

-- A text in both languages - the Polish and the English of the one key it
-- was made of, as it is or through string.format - or nil. What the quest
-- made is in the language of the character it runs for, and only that
-- language is looked for: a Polish reader's text is never taken for the
-- English of something else, which could hand the Polish readers other words.
local function both_of(text)
	if type(text) ~= "string" or text == "" then
		return nil
	end
	local first = string.sub(text, 1, 1)
	if first == MARK_POLISH or first == MARK_ENGLISH then
		return nil
	end
	local code = reader_code()
	if code == TURKISH then
		-- A Turkish reader's text: its Turkish first, then (a text it read in
		-- English, for want of Turkish) the English below.
		local pl = TR_TO_PL[text]
		if pl ~= nil then
			return pl, PL_TO_EN[pl] or pl
		end
		local list = tr_formats()
		for i = 1, table.getn(list) do
			local f = list[i]
			local found = { string.find(text, f.tr_pat) }
			if found[1] ~= nil then
				local pl_text = fill(f.pl_lits, found)
				if f.en_lits ~= nil then
					return pl_text, fill(f.en_lits, found)
				end
				return pl_text, pl_text
			end
		end
	end
	local english = code ~= 0
	if english then
		local pl = EN_TO_PL[text]
		if pl ~= nil then
			return pl, text
		end
	else
		local en = PL_TO_EN[text]
		if en ~= nil then
			return text, en
		end
	end
	local list = formats()
	for i = 1, table.getn(list) do
		local f = list[i]
		if english then
			local found = { string.find(text, f.en_pat) }
			if found[1] ~= nil then
				return fill(f.pl_lits, found), text
			end
		else
			local found = { string.find(text, f.pl_pat) }
			if found[1] ~= nil then
				return text, fill(f.en_lits, found)
			end
		end
	end
	return nil
end
QL.both_of = both_of

-- ------------------------------------------------------------- the twins

-- The English twin of one table of the data's namespace, and the top-level
-- fields it touches.
local function build(root, entries)
	local en_root = nil
	local touched = {}
	local applied, stale = 0, 0
	for i = 1, table.getn(entries) do
		local e = entries[i]
		local parts = split_path(e[1])
		local n = table.getn(parts)
		local node = root
		for j = 1, n - 1 do
			if type(node) ~= "table" then
				break
			end
			node = rawget(node, parts[j])
		end
		local polish = nil
		if type(node) == "table" then
			polish = rawget(node, parts[n])
		end
		if type(polish) == "string" and type(e[3]) == "string" and same_polish(polish, e[2]) then
			if en_root == nil then
				en_root = twin(root)
			end
			local en_node, pl_node = en_root, root
			for j = 1, n - 1 do
				pl_node = rawget(pl_node, parts[j])
				local child = rawget(en_node, parts[j])
				-- A list's item copied from the Polish is the Polish table
				-- itself: it gets a twin of its own, never an English field.
				if child == nil or child == pl_node then
					child = twin(pl_node)
					rawset(en_node, parts[j], child)
				end
				en_node = child
			end
			rawset(en_node, parts[n], e[3])
			touched[parts[1]] = true
			applied = applied + 1
			add_pair(polish, e[3], e[4] == "b")
		else
			stale = stale + 1
		end
	end
	return en_root, touched, applied, stale
end

-- The Turkish twin: the Polish is looked up (and checked against the entry's
-- signature) in pl_root, the twin is made over base_root - the English twin
-- where there is one - so whatever has no Turkish is answered by the English,
-- and what has no English either by the Polish.
local function build_over(pl_root, base_root, entries, register)
	local out_root = nil
	local touched = {}
	local applied, stale = 0, 0
	for i = 1, table.getn(entries) do
		local e = entries[i]
		local parts = split_path(e[1])
		local n = table.getn(parts)
		local node = pl_root
		for j = 1, n - 1 do
			if type(node) ~= "table" then
				break
			end
			node = rawget(node, parts[j])
		end
		local polish = nil
		if type(node) == "table" then
			polish = rawget(node, parts[n])
		end
		if type(polish) == "string" and type(e[3]) == "string" and same_polish(polish, e[2]) then
			if out_root == nil then
				out_root = twin(base_root)
			end
			local out_node, base_node = out_root, base_root
			local ok = true
			for j = 1, n - 1 do
				local base_child = base_node[parts[j]]
				if type(base_child) ~= "table" then
					ok = false
					break
				end
				local child = rawget(out_node, parts[j])
				-- As in build(): an item copied from the base list is the base's
				-- own table and gets a twin of its own.
				if child == nil or child == base_child then
					child = twin(base_child)
					rawset(out_node, parts[j], child)
				end
				out_node = child
				base_node = base_child
			end
			if ok then
				rawset(out_node, parts[n], e[3])
				touched[parts[1]] = true
				applied = applied + 1
				register(polish, e[3], e[4] == "b")
			else
				stale = stale + 1
			end
		else
			stale = stale + 1
		end
	end
	return out_root, touched, applied, stale
end

local function same(a, b, depth)
	if a == b then
		return true
	end
	if type(a) ~= "table" or type(b) ~= "table" or depth > 32 then
		return false
	end
	for k, v in pairs(a) do
		if not same(v, rawget(b, k), depth + 1) then
			return false
		end
	end
	for k in pairs(b) do
		if rawget(a, k) == nil then
			return false
		end
	end
	return true
end

local function collect_pairs(pl, en, depth, register)
	register = register or add_pair
	if type(pl) == "string" and type(en) == "string" then
		register(pl, en, false)
	elseif type(pl) == "table" and type(en) == "table" and depth <= 32 then
		for k, v in pairs(pl) do
			collect_pairs(v, rawget(en, k), depth + 1, register)
		end
	end
end

-- The plan for one table: its fields that differ between the languages, each
-- with its Polish, its English and its Turkish value { pl, en, tr }. A field
-- the English did not touch is the Polish in English; one the Turkish did not
-- touch is the English in Turkish.
local function plan(root, en_root, fields, tr_root, tr_fields)
	local chosen = {}
	local count = 0
	local names = {}
	if en_root ~= nil and fields ~= nil then
		for name in pairs(fields) do
			names[name] = true
		end
	end
	if tr_root ~= nil and tr_fields ~= nil then
		for name in pairs(tr_fields) do
			names[name] = true
		end
	end
	for name in pairs(names) do
		local pl = rawget(root, name)
		local en = pl
		if en_root ~= nil and fields ~= nil and fields[name] then
			en = rawget(en_root, name)
		end
		local tr = en
		if tr_root ~= nil and tr_fields ~= nil and tr_fields[name] then
			tr = rawget(tr_root, name)
		end
		if pl ~= nil and en ~= nil and tr ~= nil and (not same(pl, en, 0) or not same(pl, tr, 0)) then
			chosen[name] = { pl, en, tr }
			count = count + 1
		end
	end
	return chosen, count
end

-- Puts a plan in place: the fields leave the table, and its __index answers
-- them by who reads. A table that has a metatable of its own is left alone.
local function install(root, chosen)
	if getmetatable(root) ~= nil then
		return 0
	end
	local count = 0
	for name in pairs(chosen) do
		rawset(root, name, nil)
		count = count + 1
	end
	setmetatable(root, {
		__index = function(t, k)
			local pair = chosen[k]
			if pair == nil then
				return nil
			end
			local code = reader_code()
			if code == TURKISH then
				return pair[3]
			end
			if code ~= 0 then
				return pair[2]
			end
			return pair[1]
		end,
	})
	return count
end

-- The mission book library copies these strings while locale.lua loads,
-- before translate can answer by reader. Keep each row and its numeric data
-- in place, but let its three cached text fields answer just like translate.
-- Only exact, signature-checked pairs from this book's table may replace them.
-- Some missions use nested package keys, and identical Polish stories have
-- different English keys. Re-evaluate the original data in a private
-- environment to retain those relationships, without replacing any globals.
local function mission_books_in(translated)
	local chunk = assert(loadfile(LIBDIR .. "quest_book/quest_book_data.lua"))
	local env = { translate = translated }
	setmetatable(env, { __index = getfenv(0) })
	setfenv(chunk, env)
	chunk()
	return env.quest_book_data.QUEST_LIST
end

-- en and tr are the English and the Turkish twin of translate (either may be
-- nil); a Turkish that cannot be read leaves the books' English as it is.
local function plan_mission_books(pl, en, plans, tr)
	if type(quest_book_data) ~= "table" or type(quest_book_data.QUEST_LIST) ~= "table"
			or type(pl) ~= "table" or (type(en) ~= "table" and type(tr) ~= "table") then
		return
	end
	local english = nil
	if type(en) == "table" then
		english = mission_books_in(en)
	end
	local turkish = nil
	if type(tr) == "table" then
		local ok, list = pcall(mission_books_in, tr)
		if ok and type(list) == "table" then
			turkish = list
		end
	end
	for index, row in pairs(quest_book_data.QUEST_LIST) do
		local chosen = {}
		for _, name in ipairs({ "title", "desc", "what" }) do
			local text = rawget(row, name)
			if type(text) == "string" then
				local e = english and english[index] and english[index][name]
				if type(e) ~= "string" then
					e = text
				end
				local t = turkish and turkish[index] and turkish[index][name]
				if type(t) ~= "string" then
					t = e
				end
				if e ~= text or t ~= text then
					chosen[name] = { text, e, t }
				end
			end
		end
		if next(chosen) ~= nil then
			table.insert(plans, { row, chosen })
		end
	end
end

-- -------------------------------------------------------- the broadcasts

local HALVES = {}
local POLISH = {}

-- notice_all, big_notice_all: a half per language behind its mark, relayed
-- to every core the way the notice itself is.
local function wrap_marked(tbl, name)
	local raw = rawget(tbl, name)
	if type(raw) ~= "function" then
		return
	end
	local wrapper = function(...)
		if arg.n == 1 then
			local pl, en = both_of(arg[1])
			if pl ~= nil and pl ~= en then
				raw(MARK_POLISH .. pl)
				return raw(MARK_ENGLISH .. en)
			end
			-- A text with no English half goes out as its Polish (a Turkish
			-- reader's text is not the Polish; anybody else's already is).
			if pl ~= nil then
				return raw(pl)
			end
		end
		return raw(unpack(arg))
	end
	rawset(tbl, name, wrapper)
	HALVES[wrapper] = {
		polish = function(line) raw(MARK_POLISH .. line) end,
		english = function(line) raw(MARK_ENGLISH .. line) end,
	}
end

-- What the engine cannot split goes out in Polish: an English reader's text
-- is given back its Polish.
local function wrap_polish(tbl, name, index)
	local raw = rawget(tbl, name)
	if type(raw) ~= "function" then
		return
	end
	local wrapper = function(...)
		if type(arg[index]) == "string" and reads_english() then
			local pl = both_of(arg[index])
			if pl ~= nil then
				arg[index] = pl
			end
		end
		return raw(unpack(arg))
	end
	rawset(tbl, name, wrapper)
	POLISH[wrapper] = raw
end

-- d.notice: each member of the dungeon in its own language, when the engine
-- has d.notice_in; in Polish when it does not.
local function wrap_dungeon()
	if type(d) ~= "table" then
		return
	end
	local raw, notice_in = rawget(d, "notice"), rawget(d, "notice_in")
	if type(raw) ~= "function" then
		return
	end
	if type(notice_in) ~= "function" then
		wrap_polish(d, "notice", 1)
		return
	end
	local wrapper = function(...)
		local pl, en = both_of(arg[1])
		if pl ~= nil and pl ~= en then
			return notice_in(pl, en, arg[2])
		end
		if pl ~= nil then
			arg[1] = pl
		end
		return raw(unpack(arg))
	end
	rawset(d, "notice", wrapper)
	HALVES[wrapper] = {
		polish = function(line) notice_in(line, nil) end,
		english = function(line) notice_in(nil, line) end,
	}
end

-- notice_multiline(text, func) cuts a text at its [ENTER]s and hands func one
-- line at a time; a line alone is no key's text, so the text is split here,
-- and each language's lines go to its own readers.
local function wrap_multiline()
	local raw = notice_multiline
	if type(raw) ~= "function" then
		return
	end
	notice_multiline = function(str, func)
		local halves = HALVES[func]
		if halves ~= nil then
			local pl, en = both_of(str)
			if pl ~= nil and pl ~= en then
				raw(pl, halves.polish)
				raw(en, halves.english)
				return
			end
			if pl ~= nil then
				return raw(pl, func)
			end
		elseif POLISH[func] ~= nil and type(str) == "string" and reads_english() then
			local pl = both_of(str)
			if pl ~= nil then
				return raw(pl, func)
			end
		end
		return raw(str, func)
	end
end

-- say_item_vnum(vnum) captions an item's picture with get_item_name, the
-- proto's Polish, and the quest window prints the caption it is sent: a
-- reader of English is given the item's official English name instead
-- (get_item_name_en, the engine's: playerbot_names_en.tsv, the proto's own
-- where there is none). An engine without it keeps the package's caption.
-- A reader of Turkish is given the official Turkish name (quest_texts_tr.lua's
-- items, only where Gameforge's English of the vnum is this world's), else
-- the English one.
local function wrap_item_captions(names_tr)
	local raw = say_item_vnum
	if type(raw) ~= "function" or type(say_item) ~= "function" then
		return
	end
	local has_en = type(get_item_name_en) == "function"
	if not has_en and names_tr == nil then
		return
	end
	say_item_vnum = function(vnum)
		local code = reader_code()
		if code == TURKISH and names_tr ~= nil then
			local name = names_tr[tonumber(vnum) or vnum]
			if name ~= nil then
				return say_item(name, vnum, "")
			end
		end
		if code ~= 0 and has_en then
			return say_item(get_item_name_en(vnum), vnum, "")
		end
		return raw(vnum)
	end
end

local function wrap_broadcasts()
	local globals = getfenv(0)
	wrap_marked(globals, "notice_all")
	wrap_marked(globals, "big_notice_all")
	wrap_dungeon()
	wrap_polish(globals, "notice_in_map", 1)
	wrap_polish(globals, "big_notice_in_map", 1)
	wrap_polish(globals, "say_in_map", 2)
	for _, name in ipairs({ "chat_in_map", "syschat_in_map", "cmdchat_in_map",
			"chat_in_map0", "syschat_in_map0", "cmdchat_in_map0" }) do
		wrap_polish(globals, name, 2)
	end
	if type(party) == "table" then
		wrap_polish(party, "chat", 1)
		wrap_polish(party, "syschat", 1)
	end
	if type(npc) == "table" then
		wrap_polish(npc, "say", 2)
	end
	wrap_multiline()
end

-- -------------------------------------------------------------- the run

local function run()
	if type(gameforge) ~= "table" or type(locale) ~= "table" then
		error("gameforge or locale is not loaded")
	end
	quest_texts_en = nil
	dofile(LIBDIR .. "other/quest_texts_en.lua")
	local data = quest_texts_en
	quest_texts_en = nil
	if type(data) ~= "table" then
		error("quest_texts_en.lua gave no table")
	end

	local gf_pl = gameforge
	local gf_en, gf_fields, applied, stale = build(gf_pl, data.gameforge or {})
	local tr_pl, tr_en, tr_fields = translate, nil, nil
	if type(tr_pl) == "table" then
		local a, s
		tr_en, tr_fields, a, s = build(tr_pl, data.translate or {})
		applied, stale = applied + a, stale + s
	end
	QL.english, QL.stale = applied, stale

	-- The Turkish twins, made over the English ones. Anything going wrong here
	-- forgets the Turkish and leaves the English as it was.
	local gf_tur, gf_tur_fields, tl_tur, tl_tur_fields, names_tr = nil, nil, nil, nil, nil
	local data_tr = nil
	quest_texts_tr = nil
	local tr_loaded, tr_err = pcall(dofile, LIBDIR .. "other/quest_texts_tr.lua")
	if tr_loaded and type(quest_texts_tr) == "table" then
		data_tr = quest_texts_tr
	elseif not tr_loaded then
		QL.turkish_error = tostring(tr_err)
	end
	quest_texts_tr = nil
	if data_tr ~= nil then
		local tur_ok, tur_err = pcall(function()
			local a, s
			gf_tur, gf_tur_fields, a, s = build_over(gf_pl, gf_en or gf_pl, data_tr.gameforge or {}, add_pair_tr)
			QL.turkish, QL.turkish_stale = a, s
			if type(tr_pl) == "table" then
				tl_tur, tl_tur_fields, a, s = build_over(tr_pl, tr_en or tr_pl, data_tr.translate or {}, add_pair_tr)
				QL.turkish, QL.turkish_stale = QL.turkish + a, QL.turkish_stale + s
			end
			if type(data_tr.items) == "table" then
				names_tr = data_tr.items
				local n = 0
				for _ in pairs(names_tr) do
					n = n + 1
				end
				QL.turkish_items = n
			end
		end)
		if not tur_ok then
			QL.turkish_error = tostring(tur_err)
			gf_tur, gf_tur_fields, tl_tur, tl_tur_fields, names_tr = nil, nil, nil, nil, nil
			QL.turkish, QL.turkish_stale, QL.turkish_items = 0, 0, 0
			TR_TO_PL, TR_FORMAT_SOURCES, TR_FORMATS = {}, {}, nil
		end
	end

	if gf_en == nil and tr_en == nil and gf_tur == nil and tl_tur == nil then
		QL.loaded = true
		return
	end

	-- The English locale: locale.lua again, with the English gameforge in
	-- place; whatever it does, the world is put back as it was. The same with
	-- the Turkish gameforge for the Turkish locale.
	local locale_pl = locale
	local questscroll = special and special.questscroll
	local function locale_with(gf)
		local result = nil
		gameforge = gf
		local ok = pcall(dofile, get_locale_base_path() .. "/quest/locale.lua")
		if ok and type(locale) == "table" and locale ~= locale_pl then
			result = locale
		end
		gameforge = gf_pl
		locale = locale_pl
		if special ~= nil then
			special.questscroll = questscroll
		end
		return result
	end
	local locale_en = nil
	if gf_en ~= nil then
		locale_en = locale_with(gf_en)
	end
	local locale_tur = nil
	if gf_tur ~= nil then
		locale_tur = locale_with(gf_tur)
	end

	local plans = {}
	if gf_en ~= nil or gf_tur ~= nil then
		table.insert(plans, { gf_pl, (plan(gf_pl, gf_en, gf_fields, gf_tur, gf_tur_fields)) })
	end
	if tr_en ~= nil or tl_tur ~= nil then
		table.insert(plans, { tr_pl, (plan(tr_pl, tr_en, tr_fields, tl_tur, tl_tur_fields)) })
		-- A mission book that cannot be read keeps its Polish; every other
		-- table still gets its English.
		local books_ok, books_err = pcall(plan_mission_books, tr_pl, tr_en, plans, tl_tur)
		if not books_ok then
			print("QUEST_LANGUAGE: the mission books stay Polish: " .. tostring(books_err))
		end
	end
	local chatter_en = nil
	if locale_en ~= nil or locale_tur ~= nil then
		-- The monsters' chatter is said outside any quest, to everybody around
		-- (CHARACTER::MonsterChat), so it is no field that answers by reader:
		-- locale.monster_chat stays the Polish, and its English twin goes
		-- beside it as locale.monster_chat_en, from which the engine sends a
		-- viewer who reads English its line (playerbotify.py,
		-- apply_monster_chat_in). The engine has no Turkish of it: a Turkish
		-- viewer gets the English.
		if locale_en ~= nil then
			chatter_en = rawget(locale_en, "monster_chat")
			locale_en.monster_chat = rawget(locale_pl, "monster_chat")
		end
		if locale_tur ~= nil then
			locale_tur.monster_chat = rawget(locale_pl, "monster_chat")
		end
		local fields = {}
		for name in pairs(locale_pl) do
			fields[name] = true
		end
		local tur_fields = nil
		if locale_tur ~= nil then
			tur_fields = fields
		end
		local chosen = plan(locale_pl, locale_en, fields, locale_tur, tur_fields)
		chosen.monster_chat = nil
		for name, pair in pairs(chosen) do
			collect_pairs(pair[1], pair[2], 0)
			if locale_tur ~= nil then
				collect_pairs(pair[1], pair[3], 0, add_pair_tr)
			end
		end
		table.insert(plans, { locale_pl, chosen })
	end

	-- Everything is ready. The broadcasts first: no English is in force
	-- before a broadcast can give a Polish reader its Polish. Then the tables.
	wrap_broadcasts()
	wrap_item_captions(names_tr)
	local fields = 0
	for i = 1, table.getn(plans) do
		fields = fields + install(plans[i][1], plans[i][2])
	end
	if type(chatter_en) == "table" and not same(chatter_en, rawget(locale_pl, "monster_chat"), 0) then
		rawset(locale_pl, "monster_chat_en", chatter_en)
	end
	QL.fields = fields
	QL.loaded = true
	QL.data_tr = data_tr
end

-- ------------------------------------------------------------ the self-test

-- Reads one text of the Turkish file back as each reader would, through the
-- installed tables: the Polish reader must get the Polish the entry names,
-- the Turkish reader the Turkish. Run once at boot, pretending the reader
-- (TEST_READER); nothing is said to anybody.
local function resolve(root, path)
	local node = root
	local parts = split_path(path)
	for j = 1, table.getn(parts) do
		if type(node) ~= "table" then
			return nil
		end
		node = node[parts[j]]
	end
	return node
end

local function self_test()
	local data = QL.data_tr
	QL.data_tr = nil
	if type(data) ~= "table" then
		return "no_turkish"
	end
	local results = {}
	local function probe(label, root, entries)
		if type(root) ~= "table" or type(entries) ~= "table" then
			table.insert(results, label .. "=skip")
			return
		end
		for i = 1, table.getn(entries) do
			local e = entries[i]
			TEST_READER = 0
			local pl = resolve(root, e[1])
			if type(pl) == "string" and same_polish(pl, e[2]) then
				TEST_READER = TURKISH
				local tr = resolve(root, e[1])
				TEST_READER = 1
				local en = resolve(root, e[1])
				local bp, be = nil, nil
				TEST_READER = TURKISH
				if type(tr) == "string" then
					bp, be = both_of(tr)
				end
				TEST_READER = nil
				local ok = tr == e[3] and type(en) == "string" and bp == pl
				table.insert(results, label .. (ok and "=ok" or "=FAIL") .. "(" .. e[1] .. ")")
				return
			end
		end
		TEST_READER = nil
		table.insert(results, label .. "=none")
	end
	local ok, err = pcall(function()
		probe("gameforge", gameforge, data.gameforge)
		probe("translate", translate, data.translate)
	end)
	TEST_READER = nil
	if not ok then
		return "error:" .. tostring(err)
	end
	return table.concat(results, " ")
end

local ok, err = pcall(run)
local selftest = "not_run"
if ok then
	local st_ok, st = pcall(self_test)
	selftest = st_ok and tostring(st) or ("error:" .. tostring(st))
	print(string.format("QUEST_LANGUAGE: english=%d stale=%d fields=%d turkish=%d turkish_stale=%d", QL.english, QL.stale, QL.fields, QL.turkish, QL.turkish_stale))
else
	QL.error = tostring(err)
	print("QUEST_LANGUAGE: the quests stay Polish: " .. QL.error)
end
QL.selftest = selftest
TEST_READER = nil

-- What this core loaded, for the operator (print() goes to a buffered stdout).
pcall(function()
	if type(io) ~= "table" or type(io.open) ~= "function" then
		return
	end
	local out = io.open("quest_language_status.tsv", "w")
	if out == nil then
		return
	end
	local function clean(s)
		return (string.gsub(tostring(s or ""), "[\t\r\n]", " "))
	end
	out:write("QL2\tloaded\tenglish\tstale\tfields\tturkish\tturkish_stale\tturkish_items\tselftest\terror\tturkish_error\n")
	out:write(string.format("QL2\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%s\t%s\t%s\n",
		tostring(QL.loaded), QL.english, QL.stale, QL.fields, QL.turkish, QL.turkish_stale,
		QL.turkish_items, clean(selftest), clean(QL.error), clean(QL.turkish_error)))
	out:close()
end)
