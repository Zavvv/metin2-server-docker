-- metin2-suite: the NPC crafting windows from the database (Iwakura x Tyrion
-- Patch 19, point 10).
--
-- The package lists each window's recipes in libs/crafting/crafting_data.lua,
-- a file of the image: a recipe added there by hand was gone at the next
-- update. The list is world.crafting_window now (mariadb/playerbot/
-- crafting_windows.sql, which seeds it once with the package's own lists, and
-- the panel's editor, /editsql/crafting/windows). This file is dofile'd by
-- _craftingModuleLoader.lua right after crafting_data.lua, when a core loads
-- its quests - its database connection is up by then (config.cpp connects
-- before the quest manager) - and puts each window the table owns in place
-- of the file's, in the table's order, leaving out a recipe crafting_proto
-- lacks.
--
-- The table owns a window it has a row for, and every window
-- world.crafting_window_name names (the seed names all of the package's), so
-- a window the operator emptied stays empty. A window the table does not own
-- keeps the file's list; a table that is missing, empty or unreadable changes
-- nothing, so the windows are never emptied by accident.
--
-- One thing of the file still counts in a window the table owns: a number the
-- operator wrote into crafting_data.lua by hand - one that is not on that
-- window's list in the package (PACKAGE below) - goes at the end of the
-- window, once, when crafting_proto has the recipe. That is how a window was
-- changed before Patch 19 (Adijhos, 14 October: two recipes of his own in
-- Heuk-Young's list did not show), and it keeps working; the panel cannot see
-- the file, so it says so, and the table is where such a number belongs, as
-- an update may put the package's file back. A package number the operator
-- took out of a window in the table stays out whatever the file says.
--
-- A change takes effect at the next start of the cores.
do
	-- The package's own lists, as its crafting_data.lua ships them and as
	-- crafting_windows.sql seeds the table (tests/crafting_windows_lists_test.py
	-- holds the three, and the editor's modules.CRAFTING_WINDOWS, to one list).
	local PACKAGE = {
		[101] = { 1, 2, 3, 4, 5, 6 },
		[102] = {
			11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
			23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
			35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46,
			47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 67,
			68, 71, 72, 73, 74, 78, 79, 80, 81, 82, 83, 84,
			85, 86, 87, 88, 92, 93, 94, 95,
		},
		[103] = { 90, 91 },
		[104] = { 100, 101, 102, 103 },
		[105] = { 151, 152 },
		[106] = { 8001, 8002, 8003, 8004, 8005 },
		[107] = { 201, 202, 203, 204 },
		[108] = { 301, 302, 303 },
		[109] = { 351, 352, 353, 354, 355, 356, 357, 358, 359, 360, 361, 362 },
		[110] = { 221 },
		[20060] = { 50621 },
		[20062] = { 50623 },
		[20063] = { 50624 },
		[20064] = { 50625 },
		[20065] = { 50626 },
		[20066] = { 50627 },
		[20067] = { 50628 },
		[20068] = { 50629 },
		[20069] = { 50630 },
		[20070] = { 50631 },
		[20071] = { 50632 },
		[20072] = { 50633 },
	}

	-- The rows of a query, or nil when it failed.
	local function rows_of(query)
		local ok, affected, rows = pcall(mysql_direct_query, query)
		if ok and type(rows) == "table" then
			return rows
		end
		return nil
	end

	local function has(list, n)
		if type(list) ~= "table" then
			return false
		end
		local i
		for i = 1, table.getn(list) do
			if list[i] == n then
				return true
			end
		end
		return false
	end

	local rows = rows_of("SELECT window_id, recipe_id FROM world.crafting_window " ..
		"ORDER BY window_id, sort_order, recipe_id")
	local proto = nil
	if rows ~= nil and table.getn(rows) > 0 and type(crafting_data) == "table" then
		proto = rows_of("SELECT vnum FROM world.crafting_proto")
	end
	-- No recipe at all is a failed read (mysql_direct_query reports an error
	-- as no rows), not a world that wants every window empty.
	if proto ~= nil and table.getn(proto) > 0 then
		local present = {}
		local i
		for i = 1, table.getn(proto) do
			local r = proto[i]
			local v = type(r) == "table" and tonumber(r.vnum) or nil
			if v ~= nil then
				present[v] = true
			end
		end
		local windows, owned = {}, {}
		for i = 1, table.getn(rows) do
			local r = rows[i]
			local w = type(r) == "table" and tonumber(r.window_id) or nil
			local id = type(r) == "table" and tonumber(r.recipe_id) or nil
			if w ~= nil and id ~= nil and w > 0 and id > 0 then
				owned[w] = true
				if windows[w] == nil then
					windows[w] = {}
				end
				if present[id] then
					table.insert(windows[w], id)
				end
			end
		end
		local names = rows_of("SELECT window_id FROM world.crafting_window_name")
		if names ~= nil then
			for i = 1, table.getn(names) do
				local r = names[i]
				local w = type(r) == "table" and tonumber(r.window_id) or nil
				if w ~= nil and w > 0 then
					owned[w] = true
				end
			end
		end
		local count, recipes, from_file = 0, 0, 0
		local w
		for w in pairs(owned) do
			local list = windows[w] or {}
			local file = crafting_data[w]
			if type(file) == "table" then
				for i = 1, table.getn(file) do
					local n = tonumber(file[i])
					if n ~= nil and present[n] and not has(PACKAGE[w], n) and not has(list, n) then
						table.insert(list, n)
						from_file = from_file + 1
					end
				end
			end
			crafting_data[w] = list
			count = count + 1
			recipes = recipes + table.getn(list)
		end
		-- No log line: the quests' sys_log says nothing without a character.
		m2_crafting_windows = { source = "table", windows = count, recipes = recipes,
			from_file = from_file }
	else
		m2_crafting_windows = { source = "file", windows = 0, recipes = 0, from_file = 0 }
	end
end
