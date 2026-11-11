on run argv
	set p to item 1 of argv
	tell application "Microsoft Word"
		open (POSIX file p) without add to recent files
		delay 1
		set d to active document
		set nc to count of Word comments of d
		set nr to count of revisions of d
		set out to "comments=" & nc & " revisions=" & nr & linefeed
		repeat with i from 1 to nc
			set c to Word comment i of d
			set out to out & "  comment by " & (author of c) & ": " & (content of comment text of c) & " | done=" & (done of c) & linefeed
		end repeat
		set out to out & (content of text object of d)
		close d saving no
	end tell
	return out
end run
