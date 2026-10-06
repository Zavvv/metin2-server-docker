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
-- keeper are the AI's own code and never kept a wait.
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
