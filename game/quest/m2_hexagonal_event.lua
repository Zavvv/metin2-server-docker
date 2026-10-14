-- The Hexagonal Chest event (Kiciamol, 14 October): while it runs, a Metin
-- stone a person breaks may drop the hexagonal chest of the map it was
-- broken on, and opening one gives a single refine material of that map
-- (special_item_group.hexagonal.txt, appended to the share by the image).
-- The panel's /events page runs it - "activate now", the weekly windows and
-- its own chance (files/hexagonal_events.py) - through one file of the spool,
-- hexagonal_event.tsv, which this reads at most every five seconds:
--
--   M2HEX1
--   chance<TAB><permille 0..1000>
--   now<TAB><until epoch>
--   weekly<TAB><days 1..7,...><TAB><from minute><TAB><to minute>
--
-- (1 = Monday; a window whose end is not after its start runs over midnight.)
-- A missing, cut or malformed file is a chance of nothing: no old odds are
-- kept. Each core answers with hexagonal_event_status.tsv in its own
-- directory (M2HEX1, now, active, permille, kills counted, chests dropped),
-- which the panel reads beside the core's playerbot_status.tsv.
--
-- The chest is chosen by the map of the kill (pc.get_map_index() in the kill
-- handler), never by the stone's vnum or level: one vnum stands on several
-- maps (8005 on M1 and M2, 8008 and 8009 in the valley and the desert). A
-- dungeon's private instance (base * 10000 + n) is its base map's. A bot's
-- kill drops nothing, as the world's other Metin drops (m2_world_drops): the
-- event is for the people who play; a companion's kill is its owner's.
--
-- hexagonal_event.quest calls start_clock() at a login and kill() at a
-- stone's death (the quest_functions entries are the image's, Dockerfile).

-- BEGIN map table (port/shareify.py renders it from files/hexagonal_catalog.json)
M2_HEX_CHESTS = {
	[1] = 50037,
	[3] = 55000,
	[4] = 55001,
	[21] = 50037,
	[23] = 55000,
	[24] = 55001,
	[41] = 50037,
	[43] = 55000,
	[44] = 55001,
	[61] = 55002,
	[62] = 55003,
	[63] = 55004,
	[64] = 55005,
	[65] = 55006,
	[66] = 55007,
	[67] = 55008,
	[68] = 55009,
	[71] = 55010,
	[72] = 55011,
	[73] = 55012,
	[108] = 55013,
	[109] = 55014,
	[208] = 55015,
	[301] = 55016,
	[302] = 55017,
	[303] = 55018,
	[304] = 55019,
	[351] = 55020,
}
-- END map table

m2_hex_event = {
	STATE_FILE = "/opt/m2spool/hexagonal_event.tsv",
	STATUS_FILE = "hexagonal_event_status.tsv",
	READ_EVERY = 5,
	TYPE_STONE = 2,
	-- The killer's, at its feet, as long as the world's other Metin drops.
	OWNERSHIP_SECONDS = 300,
	MAX_BYTES = 65536,
	MAX_LINES = 128,
	next_read = 0, permille = 0, until_time = 0, windows = {},
	kills = 0, drops = 0, clock_started = false,
}

function m2_hex_event.split(line)
	local result = {}
	local at = 1
	while true do
		local first, last = string.find(line, "\t", at, true)
		if first == nil then
			table.insert(result, string.sub(line, at))
			return result
		end
		table.insert(result, string.sub(line, at, first - 1))
		at = last + 1
	end
end

-- Whether the event runs at `now`: an "activate now" line still open, or a
-- weekly window of today, or yesterday's over midnight.
function m2_hex_event.active(now)
	local e = m2_hex_event
	if e.until_time > now then
		return true
	end
	local current = os.date("*t", now)
	-- os.date's wday is 1 on Sunday; the file's day 1 is Monday.
	local day = math.mod(current.wday + 5, 7) + 1
	local previous = math.mod(day + 5, 7) + 1
	local minute = current.hour * 60 + current.min
	local i
	for i = 1, table.getn(e.windows) do
		local w = e.windows[i]
		if w.finish > w.start then
			if w.days[day] and minute >= w.start and minute < w.finish then
				return true
			end
		elseif (w.days[day] and minute >= w.start) or (w.days[previous] and minute < w.finish) then
			return true
		end
	end
	return false
end

-- The file, read again when it is due (or at once with force), and this
-- core's answer written.
function m2_hex_event.refresh(force)
	local e = m2_hex_event
	local now = get_time()
	if not force and now < e.next_read then
		return
	end
	e.next_read = now + e.READ_EVERY
	e.permille = 0
	e.until_time = 0
	e.windows = {}
	local input = io.open(e.STATE_FILE, "r")
	if input ~= nil then
		local text = input:read(e.MAX_BYTES + 1)
		input:close()
		if text ~= nil and string.len(text) <= e.MAX_BYTES then
			local iterator = string.gfind or string.gmatch
			local header = false
			local valid = true
			local chance_seen = false
			local count = 0
			for line in iterator(text, "([^\n]+)") do
				line = string.gsub(line, "\r$", "")
				count = count + 1
				if count > e.MAX_LINES then
					valid = false
					break
				end
				if not header then
					header = line == "M2HEX1"
					if not header then
						valid = false
						break
					end
				else
					local f = e.split(line)
					if f[1] == "chance" then
						local value = tonumber(f[2])
						if chance_seen or value == nil or value ~= math.floor(value) or value < 0 or value > 1000 then
							valid = false
							break
						end
						e.permille = value
						chance_seen = true
					elseif f[1] == "now" then
						local value = tonumber(f[2])
						if value == nil or value < 0 or value ~= math.floor(value) then
							valid = false
							break
						end
						e.until_time = math.max(e.until_time, value)
					elseif f[1] == "weekly" then
						local start = tonumber(f[3])
						local finish = tonumber(f[4])
						if start == nil or finish == nil or start < 0 or start >= 1440 or finish < 0 or finish > 1440
								or start ~= math.floor(start) or finish ~= math.floor(finish) then
							valid = false
							break
						end
						if f[2] == nil or f[2] == "" or string.find(f[2], "[^1-7,]") ~= nil then
							valid = false
							break
						end
						local days = {}
						local digit
						for digit in iterator(f[2], "[1-7]") do
							days[tonumber(digit)] = true
						end
						table.insert(e.windows, { start = start, finish = finish, days = days })
					else
						valid = false
						break
					end
				end
			end
			if not header or not valid or not chance_seen then
				e.permille = 0
				e.until_time = 0
				e.windows = {}
			end
		end
	end
	local output = io.open(e.STATUS_FILE, "w")
	if output ~= nil then
		local on = 0
		if e.active(now) then
			on = 1
		end
		output:write(string.format("M2HEX1\t%d\t%d\t%d\t%d\t%d\n", now, on, e.permille, e.kills, e.drops))
		output:close()
	end
end

-- The chest of a map, a private instance's by its base map; nil for a map
-- whose monsters drop no refine material.
function m2_hex_event.map_chest(map_index)
	local base = map_index
	if base >= 10000 then
		base = math.floor(base / 10000)
	end
	return M2_HEX_CHESTS[base]
end

-- hexagonal_event.quest's kill of a Metin stone.
function m2_hex_event.kill()
	local e = m2_hex_event
	if npc.is_pc() or npc.get_type() ~= e.TYPE_STONE or pc.is_playerbot() then
		return
	end
	e.refresh(false)
	if e.permille <= 0 or not e.active(get_time()) then
		return
	end
	local chest = e.map_chest(pc.get_map_index())
	if chest == nil then
		return
	end
	e.kills = e.kills + 1
	if number(1, 1000) <= e.permille then
		game.drop_item_with_ownership(chest, 1, e.OWNERSHIP_SECONDS)
		e.drops = e.drops + 1
	end
end

-- The core's clock: one server timer a core, so the answer is written while
-- nobody breaks a stone.
function m2_hex_event.start_clock()
	if not m2_hex_event.clock_started then
		server_loop_timer("hexagonal_event_tick", m2_hex_event.READ_EVERY)
		m2_hex_event.clock_started = true
	end
	m2_hex_event.refresh(false)
end
