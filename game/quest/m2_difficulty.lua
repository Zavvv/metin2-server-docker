-- metin2-suite: the world's difficulty, as the quests read it.
--
-- The operator chooses easy, medium, hard or custom in .env (M2_DIFFICULTY,
-- M2_BIOLOGIST_WAIT_HOURS, M2_HORSE_WAIT_HOURS); the migrator (apply.sh)
-- turns that into event flags in seconds at every start, and this file -
-- dofile'd by _otherModuleLoader.lua after collect_data.lua - is the one
-- place the quests ask. An event flag is the package's own idiom for a
-- world-wide switch (beta_server in these same quests), it is loaded by the
-- db core at boot and pushed to every game core, and the panel can read it.
--
-- Nothing here touches the bots: their Biologist hand-in and their stable
-- keeper are the AI's own code. The hand-in keeps this file's Biologist wait
-- all the same since blipu's report of 18 October - the AI reads
-- m2_biologist_wait and writes collect_quest.wait as set_wait_time below does
-- (GetPlayerBotBiologistWaitLeft, playerbot_missions.h); keep the two alike.
m2_difficulty = {}

-- Seconds an event flag asks for; a missing or negative flag is no wait.
m2_difficulty.seconds = function(name)
	local v = game.get_event_flag(name)
	if v == nil or v < 0 then
		return 0
	end
	return v
end

-- The stable keeper's waits: "buy" (the pony), "upgrade" (each Horse Book),
-- "train" (levels 1-10, the medals), "train2" (levels 11-19). A plain global
-- rather than a dotted name, because qc only admits dotted calls it knows.
function m2_horse_wait(kind)
	if kind == "buy" then
		return m2_difficulty.seconds("m2_horse_buy_wait")
	elseif kind == "upgrade" then
		return m2_difficulty.seconds("m2_horse_upgrade_wait")
	elseif kind == "train2" then
		return m2_difficulty.seconds("m2_horse_train2_wait")
	end
	return m2_difficulty.seconds("m2_horse_train_wait")
end

-- The Biologist: every collect_quest_lv* asks collect_data.is_wait, which
-- asks these two. The package waited until the reset hour of the next day
-- (time_until_hour); the world's number replaces that, and zero means the
-- next specimen is taken at once - what 2.0.55 did for everybody.
collect_data.is_research_in_progress = function()
	if m2_difficulty.seconds("m2_biologist_wait") <= 0 then
		return false
	end
	return get_time() < pc.getf("collect_quest", "wait")
end

collect_data.set_wait_time = function()
	local t = m2_difficulty.seconds("m2_biologist_wait")
	if game.get_event_flag("beta_server") > 0 then
		t = 60
	end
	if t <= 0 then
		collect_data.reset_time()
		return
	end
	pc.setf("collect_quest", "wait", get_time() + t)
	collect_data.send_delay()
end

-- The Researcher's Elixir (Eliksir Poszukiwacza; Deranfan, 1fb7a43e, 16
-- October: "none of them get consumed while handing the branches to the
-- biologist"). The package's collect quests dropped the elixir's own handler
-- (`when 71035.use`, still in quest/_unused: drunk before a hand-in, it took
-- that hand-in from 60 to 90 or 95 in a hundred) and left nothing in its
-- place, so the elixir did nothing at all - the 76020 of the Master Chest III
-- (special_item_group.starter.txt) included. Every collect_quest_lv30..lv90
-- rolls through collect_data.take_chance, so the elixir is used here, at the
-- hand-in, the way the reporter expected: one from the bag (the chest's
-- untradeable 76020 first, then 71035 and 39023) for thirty points more,
-- never past certain, and none when the hand-in is certain already. The rest
-- is the package's take_chance unchanged. The bots' and the companions'
-- hand-ins are the AI's own and never come here.
m2_difficulty.RESEARCH_ELIXIRS = { 76020, 71035, 39023 }
m2_difficulty.RESEARCH_ELIXIR_POINTS = 30

-- The first elixir in the bag, or nil.
m2_difficulty.research_elixir = function()
	for i = 1, table.getn(m2_difficulty.RESEARCH_ELIXIRS) do
		local vnum = m2_difficulty.RESEARCH_ELIXIRS[i]
		if pc.count_item(vnum) > 0 then
			return vnum
		end
	end
	return nil
end

collect_data.take_chance = function(chance)
	chance = chance * (100+collect_data.get_chance_bonus()) / 100
	if chance < 100 then
		local elixir = m2_difficulty.research_elixir()
		if elixir ~= nil then
			pc.remove_item(elixir, 1)
			chance = math.min(100, chance + m2_difficulty.RESEARCH_ELIXIR_POINTS)
			if pc.getf("playerbot_lang", "en") == 1 then
				syschat(string.format("The Researcher's Elixir was used: the chance of this hand-in is %d%%.", math.floor(chance)))
			else
				syschat(string.format("Uzyto Eliksiru Poszukiwacza: szansa tego oddania to %d%%.", math.floor(chance)))
			end
		end
	end
	if number(1,100) <= chance then
		if collect_data.is_research_in_progress() then
			affect.remove_new(AFFECT_COLLECT_NO_TIME)
		end

		pc.setf("collect_quest", m2_difficulty.FAIL_WAIT_FLAG, 0)
		collect_data.set_wait_time()
		return true
	else
		-- The Quick Analysis Potion is spent only where it saves a wait: on a
		-- world whose Biologist keeps none (easy) it stays for the next one.
		if collect_data.is_no_time_on_fail() and m2_difficulty.biologist_waits() then
			affect.remove_new(AFFECT_COLLECT_NO_FAIL_TIME)
			pc.setf("collect_quest", m2_difficulty.FAIL_WAIT_FLAG, 0)
			m2_difficulty.say_quick_analysis("used")
		else
			-- Marked before set_wait_time, whose send_delay asks is_wait.
			pc.setf("collect_quest", m2_difficulty.FAIL_WAIT_FLAG, 1)
			collect_data.set_wait_time()
		end
	end
	return false
end

-- The Quick Analysis Potion (Mikstura Szybkiej Analizy, 51785; blipu, 17
-- October: "biolog spalil item po wypiciu mikstury, nie przyjmuje
-- kolejnego"). An ITEM_POTION the package's potion_system.lua drinks into
-- AFFECT_COLLECT_NO_FAIL_TIME (its value4) for good, and collect_data spent
-- it only at a failed hand-in made AFTER the drink - so a player who did
-- what the tooltip seems to say ("if you hand the Biologist a damaged item,
-- you can hand in the next one without waiting") and drank it once the
-- Biologist had burned a specimen kept the whole wait and the potion with
-- it, and nothing said why. The potion now does both: drunk before, the
-- next failed hand-in leaves no wait (the package's rule); drunk while the
-- wait of a failed hand-in runs, that wait ends at once - at the drink, or
-- at the Biologist or the letter's clock for a potion drunk before this
-- version. Only a failure's wait, marked in collect_quest.fail_wait by
-- take_chance above: a successful hand-in's wait is the day the package
-- wants between two specimens (AFFECT_COLLECT_NO_TIME's, which no item of
-- this world gives). A wait set before the mark existed is not lifted.
-- On a world without the Biologist's wait (easy) the potion is not drunk at
-- all and the player is told so. Players only: the bots' and companions'
-- hand-ins are the AI's own.
m2_difficulty.QUICK_ANALYSIS_POTION = 51785
m2_difficulty.FAIL_WAIT_FLAG = "fail_wait"

m2_difficulty.biologist_waits = function()
	return m2_difficulty.seconds("m2_biologist_wait") > 0 or game.get_event_flag("beta_server") > 0
end

m2_difficulty.say_quick_analysis = function(what)
	local en = pc.getf("playerbot_lang", "en") == 1
	local pl, eng
	if what == "used" then
		pl = "Mikstura Szybkiej Analizy: Biolog przyjmie nastepny przedmiot bez czekania."
		eng = "Quick Analysis Potion: the Biologist will take the next item without a wait."
	elseif what == "lifted" then
		pl = "Mikstura Szybkiej Analizy: koniec czekania, Biolog przyjmie nastepny przedmiot od razu."
		eng = "Quick Analysis Potion: the wait is over, the Biologist takes the next item at once."
	elseif what == "ready" then
		pl = "Mikstura Szybkiej Analizy dziala: jesli Biolog uzna nastepny przedmiot za uszkodzony, nie bedziesz czekac."
		eng = "Quick Analysis Potion is active: if the Biologist finds the next item damaged, you will not have to wait."
	else
		pl = "Na tym swiecie Biolog nie kaze czekac - Mikstura Szybkiej Analizy nie jest potrzebna."
		eng = "The Biologist keeps no wait in this world - the Quick Analysis Potion is not needed."
	end
	if en then
		syschat(eng)
	else
		syschat(pl)
	end
end

-- Ends the wait of a failed hand-in for a drunk potion; true when it did.
m2_difficulty.lift_failure_wait = function()
	if pc.getf("collect_quest", m2_difficulty.FAIL_WAIT_FLAG) ~= 1 then
		return false
	end
	if not collect_data.is_research_in_progress() then
		return false
	end
	if not collect_data.is_no_time_on_fail() then
		return false
	end
	affect.remove_new(AFFECT_COLLECT_NO_FAIL_TIME)
	collect_data.reset_time()
	m2_difficulty.say_quick_analysis("lifted")
	return true
end

collect_data.reset_time = function()
	pc.setf("collect_quest", "wait", 0)
	pc.setf("collect_quest", m2_difficulty.FAIL_WAIT_FLAG, 0)
	collect_data.send_delay()
end

-- The package's is_wait with the lift: every collect_quest_lv* asks it at
-- the hand-in, the letter's clock (send_delay) and the "still waiting" line.
collect_data.is_wait = function()
	if not collect_data.is_research_in_progress() then
		return false
	end
	if collect_data.is_no_time() then
		return false
	end
	if m2_difficulty.lift_failure_wait() then
		return false
	end
	return true
end

-- The drink itself goes through the package's potion_use quest (36.use_type)
-- into potion_system.use_potion, looked up at the call - so this wrapper is
-- what every ITEM_POTION runs, and it touches only the three of a custom
-- affect (value4, the potion system's own column: the Determination, the
-- Stagnation and the Quick Analysis Potion).
--
-- Those three met a second fault on the way: after testing their own affect
-- the package asks `pc.has_affect(CUSTOM_AFFECT_VALUE_INDEX)` - the column's
-- index, 4 - and a skill's affect is typed by the skill's vnum, so a Warrior
-- under Sword Aura (skill 4) was told "This effect is already activated."
-- and could drink none of them. The package's function runs unchanged with
-- that one question - affect 4, no point - answered no; the custom affect
-- itself was tested a line above it.
m2_difficulty.use_custom_potion = function()
	local has_affect = pc.has_affect
	pc.has_affect = function(t, p)
		if t == 4 and p == nil then
			return false
		end
		return has_affect(t, p)
	end
	local ok, err = pcall(m2_difficulty.stock_use_potion)
	pc.has_affect = has_affect
	if not ok then
		error(err)
	end
end

if potion_system ~= nil and potion_system.use_potion ~= nil then
	m2_difficulty.stock_use_potion = potion_system.use_potion
	potion_system.use_potion = function()
		local custom = item.get_value(4)
		if custom == nil or custom <= 0 then
			return m2_difficulty.stock_use_potion()
		end
		if custom ~= AFFECT_COLLECT_NO_FAIL_TIME then
			return m2_difficulty.use_custom_potion()
		end
		if not m2_difficulty.biologist_waits() then
			m2_difficulty.say_quick_analysis("none")
			return
		end
		local had = pc.has_affect(AFFECT_COLLECT_NO_FAIL_TIME)
		m2_difficulty.use_custom_potion()
		if m2_difficulty.lift_failure_wait() then
			return
		end
		if not had and pc.has_affect(AFFECT_COLLECT_NO_FAIL_TIME) then
			m2_difficulty.say_quick_analysis("ready")
		end
	end
end

-- The Cor Draconis a day at the Alchemist (Kuszaa and the operator, 1
-- October): the Power of the Dragon Eye a new day's talk gives, and one fewer
-- on the day of the first hand-in, whose own box is the first. The event flag
-- m2_ds_eyes_per_day - .env's M2_DS_EYES_PER_DAY through the migrator, or
-- the classic panel live - from 1 to the cap, and the package's ten for
-- anything else, the way questlib's drop_gamble_with_flag reads ds_drop. The
-- bots' talks read the same flag the same way (playerbot_dragon_soul_rules.h,
-- EyesPerDay - keep the two alike). A plain global for dragon_soul.quest.
m2_difficulty.DS_EYES_PER_DAY = 10
m2_difficulty.DS_EYES_CAP = 100

function m2_ds_eyes_per_day()
	local v = game.get_event_flag("m2_ds_eyes_per_day")
	if v == nil or v < 1 or v > m2_difficulty.DS_EYES_CAP then
		return m2_difficulty.DS_EYES_PER_DAY
	end
	return v
end

-- Extra drops of the Metin stones and the bosses (Jeremus-Sama, 1 October:
-- "quantity and quality depends on metin level and boss difficulty"). Two
-- event flags, the percent a person's kill rolls at - m2_extra_ds_drop for
-- the Dragon Stone Alchemy's material, m2_extra_coupon_drop for a Kupon SM -
-- which the migrator writes from .env (M2_EXTRA_DS_DROP, M2_EXTRA_COUPON_DROP;
-- 0, the default, is off) and the classic panel sets live. world_drops.quest
-- calls m2_world_drops_kill() at a kill while either is on. What drops:
--   * a Metin stone: 1 + level / 25 Dragon Stone Shards (1 at level 5, 3 at
--     50, 5 from 100), and a coupon of 50 coins under level 40, 100 under
--     75, 250 from 75;
--   * a boss (rank 4; a king, rank 5): a Cor Draconis, two from a king, and a
--     coupon a grade above a stone's of its level, a king's two (500 and
--     1000 at the top).
-- Each roll its own, each drop the killer's for five minutes at its feet, as
-- the package's own shard drops. The rough Cor Draconis is the one box this
-- world opens (special_item_group.starter.txt has no group for 50256-50259).
-- The Alchemy's material only while the Alchemy is on (m2_dragon_soul_off)
-- and for a killer of thirty and up; the coupon for anybody. Nothing for a
-- killer more than fifteen levels over the victim - the engine fades its own
-- drops by the level difference, and a stone's guaranteed book stops at the
-- same fifteen - nor from Pirate Tanaka, whose ear is his event's prize. And
-- never for a bot's kill: the setting is for the people who play; a
-- companion's kill is its owner's (GetSidekickKillCredit), and so is the drop.
m2_world_drops = {
	SHARD = 30270,
	BOX = 50255,
	-- Kupon SM 50, 100, 250, 500 and 1000 (charge_cash_by_voucher.quest).
	COUPONS = { 80017, 80014, 80018, 80015, 80016 },
	LEVEL_DELTA = 15,
	DS_MIN_LEVEL = 30,
	OWNERSHIP_SECONDS = 300,
	TYPE_MONSTER = 0,
	TYPE_STONE = 2,
	RANK_BOSS = 4,
	RANK_KING = 5,
	TANAKA = 5001,
}

-- A percent flag as the drops read it: 0 to 100.
function m2_world_drops_percent(flag)
	local v = game.get_event_flag(flag)
	if v == nil or v <= 0 then
		return 0
	end
	if v > 100 then
		return 100
	end
	return v
end

-- What the victim is to the drops: "stone", "boss" or nil.
m2_world_drops.kind = function(vtype, rank, vnum)
	local d = m2_world_drops
	if vnum == d.TANAKA then
		return nil
	end
	if vtype == d.TYPE_STONE then
		return "stone"
	end
	if vtype == d.TYPE_MONSTER and rank >= d.RANK_BOSS then
		return "boss"
	end
	return nil
end

-- The Alchemy's material of one kill: vnum, count - or nil.
m2_world_drops.ds_drop = function(kind, level, rank)
	local d = m2_world_drops
	if kind == "stone" then
		local n = 1 + math.floor(math.max(0, level) / 25)
		if n > 5 then
			n = 5
		end
		return d.SHARD, n
	elseif kind == "boss" then
		if rank >= d.RANK_KING then
			return d.BOX, 2
		end
		return d.BOX, 1
	end
	return nil
end

-- The coupon of one kill, by the victim's level and rank - or nil.
m2_world_drops.coupon = function(kind, level, rank)
	local d = m2_world_drops
	if kind ~= "stone" and kind ~= "boss" then
		return nil
	end
	local grade = 1
	if level >= 75 then
		grade = 3
	elseif level >= 40 then
		grade = 2
	end
	if kind == "boss" then
		grade = grade + 1
		if rank >= d.RANK_KING then
			grade = grade + 1
		end
	end
	if grade > table.getn(d.COUPONS) then
		grade = table.getn(d.COUPONS)
	end
	return d.COUPONS[grade]
end

-- Everything one kill drops, as { {vnum, count}, ... }: the victim, the
-- killer's level, whether the Alchemy is on, and the two rolls already made
-- (true when the roll came under its percent).
m2_world_drops.plan = function(vtype, rank, vnum, level, killer_level, alchemy_on, ds_won, coupon_won)
	local d = m2_world_drops
	local out = {}
	local kind = d.kind(vtype, rank, vnum)
	if kind == nil or killer_level > level + d.LEVEL_DELTA then
		return out
	end
	if ds_won and alchemy_on and killer_level >= d.DS_MIN_LEVEL then
		local v, n = d.ds_drop(kind, level, rank)
		if v ~= nil then
			if v == d.BOX then
				-- A Cor Draconis does not stack: a box a drop.
				local i
				for i = 1, n do
					table.insert(out, { v, 1 })
				end
			else
				table.insert(out, { v, n })
			end
		end
	end
	if coupon_won then
		local v = d.coupon(kind, level, rank)
		if v ~= nil then
			table.insert(out, { v, 1 })
		end
	end
	return out
end

-- world_drops.quest's kill: the rolls, the plan and the drops at the killer's
-- feet. A roll of a flag at 0 never wins.
function m2_world_drops_kill()
	if npc.is_pc() or pc.is_playerbot() then
		return
	end
	local d = m2_world_drops
	local ds_pct = m2_world_drops_percent("m2_extra_ds_drop")
	local coupon_pct = m2_world_drops_percent("m2_extra_coupon_drop")
	local ds_won = ds_pct > 0 and number(1, 100) <= ds_pct
	local coupon_won = coupon_pct > 0 and number(1, 100) <= coupon_pct
	if not ds_won and not coupon_won then
		return
	end
	local list = d.plan(npc.get_type(), npc.get_rank(), npc.get_race(), npc.get_level(), pc.get_level(),
			game.get_event_flag("m2_dragon_soul_off") == 0, ds_won, coupon_won)
	local i
	for i = 1, table.getn(list) do
		game.drop_item_with_ownership(list[i][1], list[i][2], d.OWNERSHIP_SECONDS)
	end
end

-- The item exchange's chances (libs/crafting/item_exchange.lua: soul stones
-- to Magiczny Pyl, skill books to Pergamin, upgrade items to Materialy
-- Rzemieslnicze) by the world's difficulty, one number for each of the
-- three (Tieru, 30 September, after blipu's and malina0172's "Procenty na
-- wytwarzanie": the package's dust and parchment never failed). Easy is the
-- package's 100, 100 and 55, medium 90, 45 and 55, hard 55, 40 and 55; custom
-- takes the migrator's m2_exchange_*_chance (.env's M2_EXCHANGE_*_CHANCE),
-- where zero is the package's number. A preset follows the level flag alone,
-- so the panel's difficulty card changes it at once. The bots' own dust
-- exchange rolls the same numbers (GetPlayerBotExchangeChance in
-- playerbot_town.h - keep the two tables alike).
m2_difficulty.EXCHANGE_PRESETS = {
	[0] = { 100, 100, 55 },
	[1] = { 90, 45, 55 },
	[2] = { 55, 40, 55 },
}
m2_difficulty.EXCHANGE_FLAGS = { "m2_exchange_dust_chance", "m2_exchange_parchment_chance", "m2_exchange_material_chance" }

-- kind is item_exchange's own number: 1 the dust, 2 the parchment, 3 the
-- materials; package_chance what its table said before anything changed it.
m2_difficulty.exchange_chance = function(kind, package_chance)
	local preset = m2_difficulty.EXCHANGE_PRESETS[game.get_event_flag("m2_difficulty")]
	if preset ~= nil and preset[kind] ~= nil then
		return preset[kind]
	end
	local flag = m2_difficulty.EXCHANGE_FLAGS[kind]
	local v = flag and game.get_event_flag(flag) or 0
	if v == nil or v <= 0 then
		return package_chance
	end
	if v > 100 then
		return 100
	end
	return v
end

-- The package keeps its table local to its file (EXCHANGE_BY_VNUM), which
-- both item_exchange.open (the window, which shows the chance) and
-- item_exchange.exchange (the rolls) read. It is found once as an upvalue of
-- the package's exchange function, and its chances are set before either
-- runs - the quest Lua opens the debug library (questlua.cpp, InitializeLua).
-- questlib.lua puts a function of its own under the name debug once the
-- libraries are loaded, so a reload of the quests finds that one there: the
-- library is kept aside the first time (M2_LUA_DEBUG). Without the table,
-- the package's own numbers stand.
if M2_LUA_DEBUG == nil and type(debug) == "table" then
	M2_LUA_DEBUG = debug
end
if item_exchange ~= nil and item_exchange.open ~= nil and item_exchange.exchange ~= nil then
	local m2_exchange_open = item_exchange.open
	local m2_exchange_run = item_exchange.exchange
	local m2_exchange_table = nil
	if type(M2_LUA_DEBUG) == "table" and type(M2_LUA_DEBUG.getupvalue) == "function" then
		local i = 1
		while true do
			local name, value = M2_LUA_DEBUG.getupvalue(m2_exchange_run, i)
			if name == nil then
				break
			end
			if name == "EXCHANGE_BY_VNUM" and type(value) == "table" then
				m2_exchange_table = value
				break
			end
			i = i + 1
		end
	end
	local m2_exchange_package = {}
	if m2_exchange_table ~= nil then
		local k
		for k = 1, 3 do
			if m2_exchange_table[k] ~= nil then
				m2_exchange_package[k] = m2_exchange_table[k].chance
			end
		end
	end
	m2_difficulty.apply_exchange_chances = function()
		if m2_exchange_table == nil then
			return
		end
		local k
		for k = 1, 3 do
			if m2_exchange_table[k] ~= nil and m2_exchange_package[k] ~= nil then
				m2_exchange_table[k].chance = m2_difficulty.exchange_chance(k, m2_exchange_package[k])
			end
		end
	end
	item_exchange.open = function(vnum)
		m2_difficulty.apply_exchange_chances()
		return m2_exchange_open(vnum)
	end
	item_exchange.exchange = function(inventory_slots)
		m2_difficulty.apply_exchange_chances()
		return m2_exchange_run(inventory_slots)
	end
end
