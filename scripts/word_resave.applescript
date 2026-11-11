on run argv
	set p to item 1 of argv
	set q to item 2 of argv
	tell application "Microsoft Word"
		open (POSIX file p) without add to recent files
		delay 1
		set d to active document
		save as d file name q file format format document
		close d saving no
	end tell
	return "saved " & q
end run
