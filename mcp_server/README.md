# Campus Customs MCP server

The FastMCP server is the only shop-data interface for the agent team. It reads the working copy at `data/campus_customs_new.db` relative to the `hw5` project folder. All current tools are read-only; the team produces recommendations, approval requests, and drafts without changing records.

## Setup and launch

From the project root, install the combined Python dependencies with `python -m pip install -r requirements.txt`. The project `.mcp.json` registers this stdio server for an MCP-capable IDE. The backend also launches this server as a child process for each ticket run. For a manual stdio client, run `.venv\Scripts\python.exe mcp_server\server.py` from the project root and let that MCP client own the process.

The server reads shop data from `data/campus_customs_new.db`. The backend uses the root `.env` `PORTKEY_API_KEY` for model calls; `.env` is git-ignored, and the key is never written to prompts, tool responses, or the audit trail.

Start the API from the project root with `.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000` and the Vite board with `cd frontend; npm run dev`.

## Tools

| Tool | Tables read | Used for |
|---|---|---|
| `list_open_tickets()` | `desk`, `tickets` | Boss checks the open queue and shop date. |
| `get_customer_order_context(ticket_id)` | `tickets`, `desk`, `inventory`, `invoices`, `vendors` | Ticket 101: requested item, stock, linked bill, vendor specialty, and lead time. |
| `get_rent_notice_context(ticket_id)` | `tickets`, `desk`, `leases` | Ticket 102: rent notice, shop date, and linked lease terms. |
| `get_bulk_discount_context(ticket_id)` | `tickets`, `desk`, `inventory`, `pricing` | Ticket 103: requested quantity, stock, unit cost, and list price. |
| `get_accounting_context(ticket_id)` | `tickets`, `desk`, `cash_accounts`, `invoices`, `vendors`, `leases`, `payments` | Accounting checks affordability, due dates, related obligations, and payment history. |
| `get_restock_context(ticket_id)` | `tickets`, `desk`, `inventory`, `vendors`, `invoices` | Inventory compares shortfalls with recorded vendor specialties, lead times, and invoice statuses. |

The MCP SDK is constrained to the FastMCP-compatible 1.x line in `requirements.txt`. Further mutation tools require explicit approval and database safeguards before they are added.
