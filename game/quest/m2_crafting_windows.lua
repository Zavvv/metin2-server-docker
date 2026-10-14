-- metin2-suite: the NPC crafting windows from the database (Iwakura x Tyrion
-- Patch 19, point 10).
--
-- The package lists each window's recipes in libs/crafting/crafting_data.lua,
-- a file of the image: a recipe added there by hand was gone at the next
-- update. The list is world.crafting_window now (mariadb/playerbot/
-- crafting_windows.sql, which seeds it once with the package's own lists, and
-- the panel's editor). This file is dofile'd by _craftingModuleLoader.lua
-- right after crafting_data.lua, when a core loads its quests - its database
-- connection is up by then (config.cpp connects before the quest manager) -
-- and puts each window the table names in place of the file's, in the
-- table's order, leaving out a recipe crafting_proto lacks. A window the table
-- does not name keeps the file's list; a table that is missing, empty or
-- unreadable changes nothing, so the windows are never emptied by accident.
-- A change takes effect at the next start of the cores.
do
	local ok, affected, rows = pcall(mysql_direct_query,
		"SELECT w.window_id, w.recipe_id FROM world.crafting_window w " ..
		"JOIN world.crafting_proto p ON p.vnum = w.recipe_id " ..
		"ORDER BY w.window_id, w.sort_order, w.recipe_id")
	if ok and type(rows) == "table" and table.getn(rows) > 0 and type(crafting_data) == "table" then
		local windows = {}
		local recipes = 0
		local i
		for i = 1, table.getn(rows) do
			local r = rows[i]
			local w = type(r) == "table" and tonumber(r.window_id) or nil
			local id = type(r) == "table" and tonumber(r.recipe_id) or nil
			if w ~= nil and id ~= nil and w > 0 and id > 0 then
				if windows[w] == nil then
					windows[w] = {}
				end
				table.insert(windows[w], id)
				recipes = recipes + 1
			end
		end
		local count = 0
		local w, list
		for w, list in pairs(windows) do
			crafting_data[w] = list
			count = count + 1
		end
		-- No log line: the quests' sys_log says nothing without a character.
		m2_crafting_windows = { source = "table", windows = count, recipes = recipes }
	else
		m2_crafting_windows = { source = "file", windows = 0, recipes = 0 }
	end
end
