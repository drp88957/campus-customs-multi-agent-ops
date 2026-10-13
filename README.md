# Campus Customs Multi-Agent Operations

Campus Customs is a local operations desk for three shop tickets. A PydanticAI team (Boss, Inventory, Accounting, Facilities, and Customer Service) uses read-only MCP tools for shop facts. FastAPI serves the board and human approval routes; the React + Vite + TypeScript dashboard shows ticket work and cash.

Every agent uses `gpt-6-luna` through Portkey. Set `PORTKEY_API_KEY` in a project-root `.env` file before running agent tickets. `.env` is ignored by Git; never commit your real key.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- A Portkey API key for agent runs

## Install

From the repository root (`hw5/`), create a virtual environment and install the Python packages:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and replace its placeholder with your Portkey key. Install the frontend packages:

```powershell
cd frontend
npm ci
cd ..
```

The two committed databases are `data/campus_customs.db` (the clean original) and `data/campus_customs_new.db` (the agent working copy). To restore the working copy directly before starting the services:

```powershell
Copy-Item data\campus_customs.db data\campus_customs_new.db -Force
```

## Start the MCP server

The server uses MCP over standard input/output. Connect the project `.mcp.json` in your MCP-capable vibe coder; that config starts `mcp_server/server.py` with the project virtual environment. The FastAPI agent team also starts the same MCP server for each ticket run. It reads shop facts only from `data/campus_customs_new.db`.

For a manual stdio client, launch it from the repository root and let the MCP client own the process:

```powershell
.venv\Scripts\python.exe mcp_server\server.py
```

## Start the backend and dashboard

In one terminal, from the repository root:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:5173`. The backend is at `http://localhost:8000`; its CORS policy permits the Vite origin.

## Reset before a full ticket run

Before running tickets 101, 102, and 103 as a fresh full run, reset the working database from the clean original. With the backend running, use the reset route:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/reset `
  -ContentType 'application/json' -Body '{"confirm":true}'
```

The route restores `data/campus_customs_new.db` from `data/campus_customs.db`, recreates the working-only support table, and leaves the append-only audit log intact. The original file is not modified by ticket work. The reset response includes the restored checking balance; the initial balance is $3,400.

Then run tickets 101, 102, and 103 from the board. Agents prepare payment requests only; a person must approve each payment in the dashboard. The board does not send messages to customers or contact vendors.

## Submission artifacts

`output/` contains the table/tool/agent/API harness, ticket plans and reflections, design notes, smoke-call evidence, resolved ticket outcomes, the append-only audit trail, and the self-contained resolved board screenshot page. Screenshots also have PNG source copies in `output/board_screenshots/`. After publishing, `output/github_url.txt` records this repository's public URL.
