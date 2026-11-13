-- Drives JobRadar through the accessibility interface (probe branch only).
--   osascript ui.applescript windows
--   osascript ui.applescript dump
--   osascript ui.applescript press AXButton "Save"        (accessibility action)
--   osascript ui.applescript click AXStaticText "Inbox"   (mouse click in the middle of the element)
--   osascript ui.applescript has "The model works"        (text that contains this)
--   osascript ui.applescript scroll 1.0                   (scroll bars of the front window, 0 to 1)

on textOf(x)
	if x is missing value then return ""
	try
		return x as text
	on error
		return ""
	end try
end textOf

on describe(e)
	set r to ""
	set n to ""
	set d to ""
	set v to ""
	set p to ""
	set en to ""
	tell application "System Events"
		try
			set r to my textOf(role of e)
		end try
		try
			set n to my textOf(name of e)
		end try
		try
			set d to my textOf(description of e)
		end try
		try
			set v to my textOf(value of e)
		end try
		try
			set pos to position of e
			set sz to size of e
			set p to ((item 1 of pos) as text) & "," & ((item 2 of pos) as text) & "," & ((item 1 of sz) as text) & "," & ((item 2 of sz) as text)
		end try
		try
			set en to my textOf(enabled of e)
		end try
	end tell
	if (length of v) > 160 then set v to (text 1 thru 160 of v) & "…"
	if (length of n) > 160 then set n to (text 1 thru 160 of n) & "…"
	return r & " | " & n & " | " & d & " | " & v & " | " & p & " | " & en
end describe

on listWindows()
	set out to ""
	tell application "System Events" to tell process "JobRadar"
		repeat with w in windows
			set out to out & my describe(w) & linefeed
		end repeat
	end tell
	return out
end listWindows

on dumpAll()
	set out to ""
	tell application "System Events" to tell process "JobRadar"
		repeat with w in windows
			set out to out & "WINDOW " & my describe(w) & linefeed
			set els to entire contents of w
			repeat with e in els
				set out to out & my describe(e) & linefeed
			end repeat
		end repeat
	end tell
	return out
end dumpAll

on matches(e, theRole, theName)
	tell application "System Events"
		try
			if (role of e) is not theRole then return false
		on error
			return false
		end try
		try
			if my textOf(name of e) is theName then return true
		end try
		try
			if my textOf(description of e) is theName then return true
		end try
		try
			if my textOf(title of e) is theName then return true
		end try
		try
			if my textOf(value of e) is theName then return true
		end try
	end tell
	return false
end matches

on act(theRole, theName, how)
	tell application "System Events" to tell process "JobRadar"
		repeat with w in windows
			set els to entire contents of w
			repeat with e in els
				if my matches(e, theRole, theName) then
					set info to my describe(e)
					if how is "press" then
						perform action "AXPress" of e
					else
						set pos to position of e
						set sz to size of e
						set cx to (item 1 of pos) + ((item 1 of sz) div 2)
						set cy to (item 2 of pos) + ((item 2 of sz) div 2)
						click at {cx, cy}
					end if
					return "ok: " & info
				end if
			end repeat
		end repeat
	end tell
	return "not found: " & theRole & " " & theName
end act

on hasText(needle)
	tell application "System Events" to tell process "JobRadar"
		repeat with w in windows
			set els to entire contents of w
			repeat with e in els
				try
					if (role of e) is "AXStaticText" then
						set v to my textOf(value of e)
						if v is "" then set v to my textOf(name of e)
						if v contains needle then return "yes: " & v
					end if
				end try
			end repeat
		end repeat
	end tell
	return "no"
end hasText

on scrollTo(fraction)
	set n to 0
	tell application "System Events" to tell process "JobRadar"
		set els to entire contents of window 1
		repeat with e in els
			try
				if (role of e) is "AXScrollBar" then
					if (value of attribute "AXOrientation" of e) is "AXVerticalOrientation" then
						set value of e to fraction
						set n to n + 1
					end if
				end if
			end try
		end repeat
	end tell
	return "scrolled " & n & " bars"
end scrollTo

on run argv
	set cmd to item 1 of argv
	if cmd is "windows" then
		return my listWindows()
	else if cmd is "dump" then
		return my dumpAll()
	else if cmd is "press" then
		return my act(item 2 of argv, item 3 of argv, "press")
	else if cmd is "click" then
		return my act(item 2 of argv, item 3 of argv, "click")
	else if cmd is "has" then
		return my hasText(item 2 of argv)
	else if cmd is "scroll" then
		return my scrollTo((item 2 of argv) as real)
	end if
	return "unknown command " & cmd
end run
