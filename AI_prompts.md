# Vibe coder prompt log

## Problem 1: Vibe coder prompts

**Prompt typed:** Create `AI_prompts.md` at the start of the assignment and keep it updated as we work through the problems. Use it as a log of the prompts I give you, phrased in my own words as much as possible. Add a section for each problem with its number and title, at least one prompt, and, if I needed a follow-up, the follow-up prompt and one sentence explaining what the first prompt was missing.

**Follow-up:** None needed.

## Problem 2: Study the Campus Customs database

**Prompt typed:** Inspect `data/campus_customs.db`, document every table and field, and understand how each of the three open tickets connects to the other records. Copy the original database to `data/campus_customs_new.db` for future work, leaving the original untouched. Start `output/harness.md` with each table's fields and a short note about why it matters to the agents; keep expanding that harness in later problems.

**Follow-up:** None needed.

## Problem 3: Build the MCP server

**Prompt typed:** Create a FastMCP server in `mcp_server/` that uses `data/campus_customs_new.db`, with three clearly named tools to retrieve database facts needed to work on the current tickets. Do not connect to or run the server yet, and do not make up any data. Add each tool to `output/harness.md` with its source tables, the ticket it supports, and why it fits. Add a short README describing the server, its database, and its tools.

**Follow-up:** None needed.

## Problem 4: Add the MCP server to vibe coder and test each tool

**Prompt typed:** Connect this project's vibe coder to the local MCP server using its project-level MCP config (`.mcp.json` or the client's equivalent). Then call all three tools through the connection, one for each relevant ticket, and save the prompts, tool names, and full outputs in `output/mcp_smoke.json` so the returned values can be checked against the working database.

**Follow-up prompt:** Can you please fix the Codex home issue so the project MCP connection can be verified?

**What was lacking after the first prompt:** The shell did not provide `CODEX_HOME`, so `codex mcp list` could not resolve the Codex configuration.

## Problem 5: Build the agent team and grow the MCP tools

**Prompt typed:** Build the five Campus Customs roles with PydanticAI, detailed per-agent prompts, and bounded loops where every role can delegate to any other. Route all model calls through the root `.env` Portkey credential and use only `gpt-6-luna`. Keep shop facts behind the MCP server, add the extra database tools the roles need, and make each agent-loop step append an auditable JSONL record without clearing earlier entries. Expand the harness with agents, tools and their source tables, and business safety and token limits; update the MCP README to match.

**Follow-up:** None needed.

## Problem 6: Plan the three tickets

**Prompt typed:** Before running the backend, make a standalone `output/desk_tickets.html` with tabs for tickets 101, 102, 103, Cash, and Reflection. For each ticket, write only an Expected plan: which role Boss should ask first and why, the specific delegation chain, and the MCP tools that chain should use. Keep an empty Actual area for after the agent run, and leave Cash and Reflection blank or marked as coming later.

**Follow-up:** None needed.

## Problem 7: Backend routes

**Prompt typed:** Extend `backend/main.py` with FastAPI routes for the ticket board, running a ticket, recent agent outputs and tool calls, current checking balance, human-approved payments and purchases, and resetting the working database from the untouched original. Keep payments approval-gated, prevent overdrafts, update the relevant records, and list every route with a one-line description in `output/harness.md`. Start the backend from `backend/` on port 8000.

**Follow-up:** None needed.

## Problem 8: Agent dashboard

**Prompt typed:** Build a React, Vite, and TypeScript dashboard in `frontend/` that talks to the FastAPI server at `http://localhost:8000`. Show the three tickets, let a person run the agents on one ticket, poll the activity feed so the team’s work appears live, summarize each role, mark a finished run resolved, and show the current cash with human approval controls for proposed payments and purchases. Make the desk feel thoughtful and inviting, enable the Vite origin in backend CORS, start `npm run dev`, and write `output/design.md` to explain the visual choices.

**Follow-up:** None needed.

## Problem 9: Resolve the tickets

**Prompt typed:** Reset the working database from its clean source and record the starting checking balance. Run tickets 101, 102, and 103 through the agent board one at a time, using the recorded facts and only `gpt-6-luna`. Keep the audit log append-only, use human approval only for recorded affordable obligations, and do not invent a vendor quote or contact customers or vendors. Fill the Actual sections in `output/desk_tickets.html`, itemize the cash from reset to ending balance, save each ticket's status, outcome, agent work, and approvals to `output/resolved_tickets.json`, capture the resolved dashboard views in `output/resolved_board.html`, and finish the harness.

**Follow-up prompt:** Fix the bounded agent-loop limits that prevented the Boss report and one specialist report from completing, then rerun the affected tickets and use the completed runs for the final record.

**What was lacking after the first prompt:** The Boss hit its request, input, and output caps on multi-delegation tickets, and Accounting's ticket 103 report exceeded the specialist output cap, so those runs needed a bounded retry after filtering each role's MCP tools.

**Additional follow-up prompt:** Fix the two remaining Problem 9 evidence issues: restore a populated pristine database at the assignment's canonical `data/campus_customs.db` path and point the reset route there; then replace the illustrated board views with actual browser captures of the live React dashboard for tickets 101, 102, and 103. Keep the resolved working database and its cash records intact.

**What was still lacking after the initial Problem 9 request:** The canonical original path was empty, so reset used a nested baseline, and the saved board evidence was reconstructed artwork instead of captures of the running dashboard.

## Problem 10: Reflection

**Prompt typed:** Fill the Reflection tab in `output/desk_tickets.html` with a detailed reflection in my own voice. Evaluate how the team handled tickets 101, 102, and 103, compare each Actual delegation and tool use with its Expected plan, explain where one agent with tools would be simpler, and give three new problems the current toolset could help with plus three it could not finish. Tie every point to this run, the ticket tabs, and the Cash tab, including the approvals and balance changes.

**Follow-up:** None needed.

## Problem 11: Submit to GitHub

**Prompt typed:** Prepare this `hw5` assignment as its own public GitHub repository. Keep any real `.env` and credential out of Git, include the original and working SQLite databases, add a root README with dependency setup, MCP/backend/dashboard launch steps and the clean-reset workflow, then record the public repository URL in `output/github_url.txt` and submit that URL to Canvas.
