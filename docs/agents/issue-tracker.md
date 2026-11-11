# Issue tracker

The tracker is GitHub Issues in `jekozyra/spsync`. Use the `gh` CLI for every operation. No tracker MCP server is configured. Create tickets with `gh issue create --template Ticket` so the body follows [`.github/ISSUE_TEMPLATE/ticket.md`](../../.github/ISSUE_TEMPLATE/ticket.md).

## Wayfinding operations (GitHub Issues)

- **Map**: a GitHub issue whose title starts with `map: `. Its body holds `## Destination`, `## Decisions so far`, `## Not yet specified`, and `## Out of scope` sections.
- **Tickets**: GitHub issues created from the ticket template. Each ticket body contains a `Part of #<map>` line and a `**Type:** research | prototype | grilling | task` line. The map body lists each ticket as a `- [ ] #<ticket>` task-list item.
- **Blocking**: `Blocked by #NN` lines in the ticket's `## Blocked by` section, as the ticket template defines. A ticket is unblocked when every issue that it lists is closed.
- **Frontier**: list the map's open, unassigned tickets with `gh issue list -R jekozyra/spsync --state open --search "no:assignee \"Part of #<map>\""`. Keep the tickets whose `Blocked by` issues are all closed. Check an issue state with `gh issue view <NN> -R jekozyra/spsync --json state`.
- **Claim**: assign the ticket with `gh issue edit <NN> -R jekozyra/spsync --add-assignee @me`. The assignee is the claim.
- **Resolution**: post the answer with `gh issue comment`, close the issue with `gh issue close`, and add the one-line gist to the map issue's `## Decisions so far` section with `gh issue edit --body-file`.
