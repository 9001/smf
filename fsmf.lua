#!/usr/bin/env luajit
--#!/usr/bin/env lua5.3


printf = function(s, ...)
    return io.write(s:format(...))
end


-- https://gist.github.com/tylerneylon/81333721109155b2d244
-- simplified, no metatables or circular references
function dcopy(obj)
    if type(obj) ~= 'table' then
        return obj
    end

    local ret = {}
    for k, v in pairs(obj) do
        ret[dcopy(k)] = dcopy(v)
    end
    return ret
end


-- http://lua-users.org/wiki/TableSerialization
-- Print anything - including nested tables
function tprint (tt, indent, done)
    done = done or {}
    indent = indent or 0
    if type(tt) == "table" then
        for key, value in pairs (tt) do
            io.write(string.rep (" ", indent)) -- indent it
            if type (value) == "table" and not done [value] then
                done [value] = true
                io.write(string.format("[%s] => table\n", tostring (key)));
                io.write(string.rep (" ", indent+4)) -- indent it
                io.write("(\n");
                tprint (value, indent + 7, done)
                io.write(string.rep (" ", indent+4)) -- indent it
                io.write(")\n");
            else
                io.write(string.format("[%s] => %s\n",
                    tostring (key), tostring(value)))
            end
        end
    else
        io.write(tt .. "\n")
    end
end


-- https://stackoverflow.com/questions/40454472/lua-iterate-over-table-sorted-by-values
function sort_by_member(tab, member, desc)
    local keys = {}
    for k in pairs(tab) do
        keys[#keys + 1] = k
    end
    if member == nil then
        if desc then
            table.sort(keys, function(a, b)
                return tab[a] > tab[b]
            end)
        else
            table.sort(keys, function(a, b)
                return tab[a] < tab[b]
            end)
        end
    else
        if desc then
            table.sort(keys, function(a, b)
                return tab[a][member] > tab[b][member]
            end)
        else
            table.sort(keys, function(a, b)
                return tab[a][member] < tab[b][member]
            end)
        end
    end

    local j = 0
    return
        function()
            j = j + 1
            local k = keys[j]
            if k ~= nil then
                return k, tab[k]
            end
        end
end


function main()
	local folders = {}
    while true do
		local sp = io.read()
		if sp == "eof" then break end
		if string.sub(sp, 1, 2) ~= "p " then
			error(sp)
		end
		sp = string.sub(sp, 3)
		
		local sf = io.read()
		if string.sub(sf, 1, 2) ~= "f " then
			error(sf)
		end
		sf = string.sub(sf, 3)
		
		-- io.write(sp)
		local files = {}
		for x in string.gmatch(sf, "([^%s]+)") do
			files[#files + 1] = x
		end
		folders[#folders + 1] = {["p"]=sp, ["f"]=files}
		-- tprint(folders[#folders])
    end
	local dupes = {}
	local remains = #folders
	--io.write(remains)
	for n1 = 1, #folders do
		local fld1 = folders[n1]
		if n1 % 10 == 0 then
			printf('%d / %d\n', n1, remains)
		end
		
		local sum_fld1 = 0
		--tprint(fld1)
		for nf = 1, #fld1.f do
			sum_fld1 = sum_fld1 + fld1.f[nf]
		end
		
		local mnt = string.sub(fld1.p, 1, 8)
		
		for n2 = n1 + 1, #folders do
			local fld2 = folders[n2]
			if string.sub(fld2.p, 1, 8) == mnt then goto c1 end
			
			--| # hits = each file size that matched,
			--| # rhs = the remaining files in folder2 to check
			--| # (to deal w/ multiple files of same size in one folder)
			--| hits = []
			--| rhs = folder2.files[:]
			--| for sz in folder1.files:
			--| 	if sz in rhs:
			--| 		hits.append(sz)
			--| 		rhs.remove(sz)

			local hits = {}
			--local rhs = dcopy(fld2.f)
			local rhs = fld2.f
			for n1f = 1, #fld1.f do
				local sz1 = fld1.f[n1f]
				for n2f = 1, #rhs do
					local sz2 = rhs[n2f]
					if sz1 == sz2 then
						if #hits == 0 then
							rhs = dcopy(fld2.f)
						end
						rhs[n2f] = 0
						hits[#hits + 1] = sz1
					end
				end
			end
			
			local sum_hits = 0
			for nh = 1, #hits do
				sum_hits = sum_hits + hits[nh]
			end
			
			-- sufficiently large hits skip all the checks
			if sum_hits < 600 * 1024 * 1024 then
				
				local score = (#hits * 2.0) / (#fld1.f + #fld2.f)
			
				local sum_fld2 = 0
				for nf = 1, #fld2.f do
					sum_fld2 = sum_fld2 + fld2.f[nf]
				end
				
				-- must be 20% or more files with identical size
				if score < 0.2 then goto c1 end
				printf("s1 %d, s2 %d, score %f\n", sum_fld1, sum_fld2, score)
				
				--| # total disk consumption must be <= 30% different
				--| a = sum(folder1.files)
				--| b = sum(folder2.files)
				--| if min(a,b) * 1.0 / max(a,b) < 0.7:
				--| 	continue
				--| 
				--| # matched files must amount to >= 20% of bytes
				--| if sum(hits) < a * 0.2 \
				--| and sum(hits) < b * 0.2:
				--| 	continue

				-- total disk consumption must be <= 30% different
				local min_sum = math.min(sum_fld1, sum_fld2)
				local max_sum = math.max(sum_fld1, sum_fld2)
				if min_sum * 1.0 / max_sum < 0.7 then goto c1 end
				
				-- matched files must amount to >= 20% of bytes
				if sum_hits < sum_fld1 * 0.2
				and sum_hits < sum_fld2 * 0.2 then goto c1 end
			
			end
			
			dupes[#dupes + 1] = {["1"]=score, ["2"]=folder1, ["3"]=folder2}
			
			::c1::
		end
	end
	printf("%d dupes", #dupes)
end


main()
