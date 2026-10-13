# Campus Customs operations harness

`data/campus_customs.db` is the canonical original and reset source. The provided populated baseline was found at `data/data/campus_customs.db`; its original ticket rows, $3,400 checking balance, open invoice 501, and empty payments table were verified, then copied to the canonical path. The nested baseline copy remains intact. The reset route reads the canonical original, and agents use only `data/campus_customs_new.db`.

The shop's current date is `2026-08-31`, from `desk.date_today`. Use it when deciding whether obligations are overdue.

## Tables and fields

### `cash_accounts`

- `name` (TEXT, primary key)
- `balance` (REAL)
- `date` (TEXT)

Tracks available cash and the balance date so Accounting can check affordability before proposing payments.

### `desk`

- `date_today` (TEXT)
- `notes` (TEXT)

Provides the shop's current date, which agents use to assess due dates and overdue items.

### `inventory`

- `sku` (TEXT, part of composite primary key with `size`)
- `name` (TEXT)
- `size` (TEXT, part of composite primary key with `sku`)
- `qty` (INTEGER)
- `location` (TEXT)

Shows on-hand quantities by product and size so Inventory can check orders and identify shortages.

### `invoices`

- `id` (INTEGER, primary key)
- `vendor_id` (INTEGER, references `vendors.id`)
- `amount` (REAL)
- `due_date` (TEXT)
- `status` (TEXT)
- `description` (TEXT)

Tracks vendor bills; Accounting uses it for due dates and payments, and an unpaid open invoice blocks that vendor from shipping.

### `leases`

- `id` (INTEGER, primary key)
- `space_name` (TEXT)
- `landlord` (TEXT)
- `monthly_rent` (REAL)
- `next_due` (TEXT)
- `notes` (TEXT)

Holds rent and property details for Facilities to review rent notices and due dates.

### `payments`

- `id` (INTEGER, primary key)
- `kind` (TEXT)
- `ref_id` (INTEGER)
- `amount` (REAL)
- `account` (TEXT)
- `paid_at` (TEXT)
- `approved_by` (TEXT)

Records completed cash outflows and their approval, reference, and account for Accounting's audit trail.

### `pricing`

- `sku` (TEXT, primary key)
- `unit_cost` (REAL)
- `list_price` (REAL)

Gives Accounting and the Boss the cost and list price needed to assess margins and discount requests.

### `tickets`

- `id` (INTEGER, primary key)
- `type` (TEXT)
- `requester` (TEXT)
- `subject` (TEXT)
- `sku` (TEXT)
- `size` (TEXT)
- `qty` (INTEGER)
- `lease_id` (INTEGER, references `leases.id`)
- `invoice_id` (INTEGER, references `invoices.id`)
- `status` (TEXT)
- `notes` (TEXT)
- `created_at` (TEXT)

Is the work queue: the Boss routes tickets, and the optional product, lease, and invoice identifiers connect agents to related records.

### `vendors`

- `id` (INTEGER, primary key)
- `name` (TEXT)
- `specialty` (TEXT)
- `lead_days` (INTEGER)

Lets Inventory find a supplier for a shortage and estimate restock lead time; Accounting checks vendor invoices before shipment.

### `purchase_orders` (backend-created in the working copy)

- `id` (INTEGER, primary key)
- `ticket_id` (INTEGER, references `tickets.id`)
- `vendor_id` (INTEGER, references `vendors.id`)
- `sku` (TEXT)
- `size` (TEXT)
- `qty` (INTEGER)
- `amount` (REAL)
- `status` (TEXT)
- `approved_by` (TEXT)
- `approved_at` (TEXT)

Stores product purchase details after a human approval. The backend creates this table in `campus_customs_new.db`; it is not added to the untouched original database. A purchase records a cash outflow but does not change inventory or resolve a ticket before receipt and fulfillment.

## Open tickets and their links

All three rows in `tickets` have `status = open`.

- **101 - Bulldog tee:** Customer order for one `CC-TEE-WHITE`, size S. Its `invoice_id = 501` links to an open $840 invoice due 2026-08-28; invoice 501 has `vendor_id = 1`, which links to Bulldog Print Co (five-day lead time). The matching inventory row has zero size S tees. Relative to the shop date of 2026-08-31, invoice 501 is overdue. The invoice's open status also means its vendor will not ship new product until the bill is paid.
- **102 - Rent due:** Rent notice links through `lease_id = 1` to the Chapel Street shop lease with Elm City Properties. The monthly rent is $2,400 and `next_due = 2026-09-02`, two days after the shop date. The ticket has no invoice link.
- **103 - Bulk hoodie discount:** Yale AI Club requests 20 `CC-HOOD-NAVY` hoodies, size M, at a bulk discount. There are 8 in stock in that SKU/size row; the pricing row lists unit cost $22 and list price $58. The ticket has no lease or invoice link.

## MCP tools

All shop facts are read through the FastMCP server in `mcp_server/server.py`, which reads `data/campus_customs_new.db`. The tools below are read-only; proposals and drafts go into the agent response and audit trail.

### `list_open_tickets()`

- **Tables read:** `desk`, `tickets`
- **Tickets supported:** 101, 102, 103
- **Why this tool:** It gives Boss the open work queue and authoritative shop date before routing work.

### `get_customer_order_context(ticket_id)`

- **Tables read:** `tickets`, `desk`, `inventory`, `invoices`, `vendors`
- **Ticket supported:** 101
- **Why this tool:** It returns the requested SKU and size, on-hand stock, and linked invoice and vendor details needed to assess the stockout and restock dependency.

### `get_rent_notice_context(ticket_id)`

- **Tables read:** `tickets`, `desk`, `leases`
- **Ticket supported:** 102
- **Why this tool:** It follows the rent notice's lease link to return the rent amount, space, landlord, and due date Facilities needs to review.

### `get_bulk_discount_context(ticket_id)`

- **Tables read:** `tickets`, `desk`, `inventory`, `pricing`
- **Ticket supported:** 103
- **Why this tool:** It combines the requested quantity with matching stock and recorded unit cost and list price for evaluating the bulk discount request.

### `get_accounting_context(ticket_id)`

- **Tables read:** `tickets`, `desk`, `cash_accounts`, `invoices`, `vendors`, `leases`, `payments`
- **Tickets supported:** 101, 102, 103
- **Why this tool:** It gives Accounting the database date, current balances, linked obligation, related vendor, and payment history needed to prepare an affordable approval request.

### `get_restock_context(ticket_id)`

- **Tables read:** `tickets`, `desk`, `inventory`, `vendors`, `invoices`
- **Tickets supported:** 101, 103
- **Why this tool:** It shows the product shortfall alongside vendor specialties, lead times, and invoice statuses so Inventory can identify candidates while respecting shipping blocks.

## Agent team

All five PydanticAI agents use only `gpt-6-luna` through Portkey with `PORTKEY_API_KEY` loaded from the project-root `.env`. Their detailed instructions are in `backend/prompts/`. Every role has the `delegate_to_agent` tool and can ask any other role for help; self-delegation, excess depth, repeated loops, model requests, and tool calls are bounded in `backend/agent_team.py`.

- **Boss** (`backend/prompts/boss.md`): checks the open board, routes relevant subtasks, reconciles specialist findings, and returns a final recommendation for human review.
- **Inventory** (`backend/prompts/inventory.md`): checks SKU/size stock, shortages, vendor specialties, lead times, and open-invoice shipping blocks.
- **Accounting** (`backend/prompts/accounting.md`): checks cash, dates, invoices, payments, and margins, then prepares payment or purchase-order approval requests.
- **Facilities** (`backend/prompts/facilities.md`): reviews rent notices against lease terms and `desk.date_today`.
- **Customer Service** (`backend/prompts/customer_service.md`): drafts fact-grounded customer messages that remain unsent.

MCP tool visibility is filtered by role to keep each agent's input focused: Boss gets `list_open_tickets`; Inventory gets both product-context tools and `get_restock_context`; Accounting gets `get_accounting_context` and `get_bulk_discount_context`; Facilities gets `get_rent_notice_context`; Customer Service gets the ticket-specific customer context tools. Delegation remains available across all five roles.

Each agent invocation appends start, completion, failure, or limit records to `output/audit_trail.jsonl`. Completion records include the run and step IDs, ticket, role, parent/delegation depth, task, model, structured output, conversation/tool messages, and reported token usage. The logger opens the file in append mode and never truncates earlier runs.

## Safety and usage limits

- Before a real deployment, require authenticated and role-limited access to the API and dashboard, protect `.env`, encrypt and restrict access to audit records, and keep a human approval gate for every payment and other consequential business action.
- The agents cannot execute payments, alter cash or inventory, mark invoices paid, close tickets, place orders, approve discounts, email customers, or call vendors. Agent proposals use recorded amounts; if a purchase quote is missing, its amount stays unset. Drafts and approval requests require a person to act.
- `POST /approvals` requires `confirm: true` and an approver name. Recorded invoice and rent payments use the database amount; product purchases require a human-entered quote, an exact-SKU-fit confirmation, and an eligible vendor. A transaction checks available cash, blocks duplicate or unaffordable payments, writes `payments` (and purchase details when applicable), and updates checking without allowing a negative balance. This local demo records the supplied approver name but does not authenticate it; production use needs authenticated approval and idempotency controls.
- The agents treat MCP as the only shop-data source, cite source rows, distinguish facts from recommendations, and flag missing values instead of inventing them. Vendor specialty alone does not prove a specific SKU can be supplied.
- Token use is bounded to at most 10 agent steps per ticket and delegation depth 3. Specialists are limited to 4 model requests, 6 tool calls, 5,000 input tokens, and 1,000 output tokens per step. Boss is limited to 8 requests, 6 tool calls, 14,000 input tokens, and 1,200 output tokens so it can reconcile bounded delegated reports. Keep delegations targeted and stop for human review when a limit or missing fact prevents a grounded decision.

## Backend routes

- `GET http://localhost:8000/health` — confirms that the FastAPI service is running.
- `GET http://localhost:8000/tickets` — returns the three tickets, their stored status, and open/resolved flags.
- `POST http://localhost:8000/tickets/{ticket_id}/run` — runs the PydanticAI team for one open ticket, returns the final report, and marks the ticket resolved when the run finishes (approval requests may still be pending).
- `GET http://localhost:8000/vendors` — returns recorded vendor choices and flags vendors blocked by open invoices for the purchase-approval form.
- `GET http://localhost:8000/events?limit=50` — returns recent agent outputs, delegated/tool calls, token use, failures, and recorded human-approval/reset events.
- `GET http://localhost:8000/cash` — returns the checking balance and balance date from `cash_accounts`.
- `POST http://localhost:8000/approvals` — records a human-approved invoice/rent payment or quoted product purchase, updates `payments` and checking cash, and refuses unaffordable or vendor-blocked purchases.
- `POST http://localhost:8000/reset` — restores the working database from `data/campus_customs.db`; the append-only audit trail is retained.

The approval route requires an explicit `confirm: true` and approver name. Invoice and rent payment amounts must match their recorded database obligations. A product purchase also requires a human-entered quote, a recorded vendor with no open invoice, and confirmation that the quoted vendor can supply the exact SKU and size; its details are stored in the working-copy `purchase_orders` table. The route does not contact vendors or record stock as received. A completed analysis marks the board ticket resolved while any proposed payment or purchase still waits for the human approval route.

## Dashboard

The React + Vite + TypeScript desk is in `frontend/` and runs at `http://localhost:5173`. It reads the board, ticket run results, live event summaries, and checking balance from the FastAPI routes above; it refreshes status and cash after a run or human approval. Ticket cards show open/resolved state, selected-ticket detail, agent summaries and tool calls, and any pending human approval control. Its role colors, cash tile, and chronological field-note feed are described in `output/design.md`.

## Problem 9 run record

- The working copy was reset from the valid source copy before the final run; checking started at **$3,400** on `2026-08-31`.
- Ticket 101: approved payment of invoice 501 for **$840**, leaving **$2,560**. The invoice is now recorded as paid. The board ticket is resolved, but an exact-SKU vendor fit and fulfillment were not verified or placed.
- Ticket 102: approved rent payment for lease 1 of **$2,400**, leaving **$160**. The rent was scheduled for `2026-09-02` and paid on the shop date, `2026-08-31`.
- Ticket 103: **$0** outflow. No discount amount, vendor quote, or exact supply confirmation was recorded, so no payment or purchase was made. The backend marks the completed agent run resolved while its result remains `needs_human_review`.
- Ending checking is **$160**, matching `cash_accounts`; the two payments total **$3,240**. Approver: Deep. Ticket summaries and approvals are in `output/resolved_tickets.json`; the cash tab and Actual sections are in `output/desk_tickets.html`; board evidence is in `output/resolved_board.html`, which embeds three actual browser captures of the React board (with PNG source copies in `output/board_screenshots/`). All real and failed attempt records remain appended to `output/audit_trail.jsonl`.
