"""FastAPI routes for the Campus Customs dashboard and human approvals."""

from __future__ import annotations

import base64
import binascii
from contextlib import asynccontextmanager, closing
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import sys
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

# Support both `uvicorn backend.main:app` from the project root and the
# assignment's `uvicorn main:app` command from the backend directory.
if __package__:
    from .agent_team import AgentTeam
    from .audit import AuditTrail
    from .models import TicketRunResult
else:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from backend.agent_team import AgentTeam
    from backend.audit import AuditTrail
    from backend.models import TicketRunResult


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("CAMPUS_CUSTOMS_STATE_DIR", PROJECT_ROOT / "data")).resolve()
DATABASE_PATH = STATE_DIR / "campus_customs_new.db"
ORIGINAL_DATABASE_PATH = PROJECT_ROOT / "data" / "campus_customs.db"
AUDIT_PATH = Path(
    os.environ.get(
        "CAMPUS_CUSTOMS_AUDIT_PATH",
        PROJECT_ROOT / "output" / "audit_trail.jsonl",
    )
).resolve()
audit_trail = AuditTrail(AUDIT_PATH)


class ResetCommand(BaseModel):
    confirm: Literal[True]


class ApprovalCommand(BaseModel):
    ticket_id: int = Field(gt=0)
    kind: Literal["payment", "purchase_order"]
    approved_by: str = Field(min_length=1, max_length=120)
    confirm: Literal[True]
    # Payments for recorded invoices or rent derive their amount from the DB.
    # A purchase order requires an explicitly approved vendor quote amount.
    approved_amount: Decimal | None = Field(default=None, gt=0)
    vendor_id: int | None = Field(default=None, gt=0)
    confirmed_sku_fit: bool = False


def _connect(*, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        uri = f"{DATABASE_PATH.as_uri()}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=10)
    return sqlite3.connect(DATABASE_PATH, timeout=10)


def _initialize_working_copy() -> None:
    """Seed a new runtime state directory from the clean original database."""
    if DATABASE_PATH.is_file():
        return
    if not ORIGINAL_DATABASE_PATH.is_file():
        raise RuntimeError("The original Campus Customs database was not found.")
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ORIGINAL_DATABASE_PATH, timeout=10)) as source:
        with closing(sqlite3.connect(DATABASE_PATH, timeout=10)) as destination:
            source.backup(destination)


def _ensure_support_schema(connection: sqlite3.Connection) -> None:
    """Keep human-approved purchase details in the working DB only."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id),
            vendor_id INTEGER NOT NULL REFERENCES vendors(id),
            sku TEXT NOT NULL,
            size TEXT NOT NULL,
            qty INTEGER NOT NULL CHECK (qty > 0),
            amount REAL NOT NULL CHECK (amount > 0),
            status TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            approved_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _initialize_working_copy()
    with closing(_connect()) as connection:
        _ensure_support_schema(connection)
    team = AgentTeam.from_environment()
    app.state.agent_team = team
    try:
        yield
    finally:
        await team.close()


app = FastAPI(
    title="Campus Customs Agent Backend",
    description="Coordinates ticket work, shows the agent trail, and records human approvals.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def protect_deployed_api(request: Request, call_next):
    """Require shared Basic credentials for data and write APIs when configured."""
    path = request.url.path
    api_request = (
        path == "/tickets"
        or path.startswith("/tickets/")
        or path in {"/events", "/cash", "/vendors", "/approvals", "/reset"}
    )
    if not api_request:
        return await call_next(request)

    expected_user = os.getenv("CAMPUS_CUSTOMS_ACCESS_USERNAME", "")
    expected_password = os.getenv("CAMPUS_CUSTOMS_ACCESS_PASSWORD", "")
    if not expected_user and not expected_password:
        return await call_next(request)
    if not expected_user or not expected_password:
        return JSONResponse({"detail": "Deployment access is not configured."}, status_code=503)

    authorization = request.headers.get("authorization", "")
    try:
        scheme, encoded = authorization.split(" ", 1)
        if scheme.lower() != "basic":
            raise ValueError("Unsupported authorization scheme")
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        supplied_user, supplied_password = decoded.split(":", 1)
        valid = secrets.compare_digest(supplied_user, expected_user) and secrets.compare_digest(
            supplied_password, expected_password
        )
    except (ValueError, UnicodeDecodeError, binascii.Error):
        valid = False

    if not valid:
        return JSONResponse(
            {"detail": "Sign in to use the operations desk."},
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/tickets")
async def get_tickets() -> dict[str, list[dict[str, Any]]]:
    """Return each ticket and its current open/resolved state."""
    try:
        with closing(_connect(read_only=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, type, requester, subject, sku, size, qty,
                       lease_id, invoice_id, status, notes, created_at
                FROM tickets ORDER BY id
                """
            ).fetchall()
            tickets = []
            for row in rows:
                ticket = dict(row)
                ticket["is_open"] = ticket["status"].lower() == "open"
                ticket["is_resolved"] = ticket["status"].lower() in {
                    "resolved", "closed", "complete", "completed"
                }
                tickets.append(ticket)
            return {"tickets": tickets}
    except sqlite3.Error as exc:
        logger.error("Could not read tickets (%s).", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not read the ticket board.") from exc


@app.get("/vendors")
async def get_vendors() -> dict[str, list[dict[str, Any]]]:
    """Return vendor choices and their open-invoice shipping eligibility."""
    try:
        with closing(_connect(read_only=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT v.id, v.name, v.specialty, v.lead_days,
                       group_concat(CASE WHEN lower(i.status) = 'open' THEN i.id END) AS open_invoice_ids
                FROM vendors AS v
                LEFT JOIN invoices AS i ON i.vendor_id = v.id
                GROUP BY v.id, v.name, v.specialty, v.lead_days
                ORDER BY v.id
                """
            ).fetchall()
        vendors = []
        for row in rows:
            vendor = dict(row)
            raw_ids = vendor.pop("open_invoice_ids")
            vendor["open_invoice_ids"] = (
                [int(invoice_id) for invoice_id in raw_ids.split(",")]
                if raw_ids
                else []
            )
            vendor["can_ship"] = not vendor["open_invoice_ids"]
            vendors.append(vendor)
        return {"vendors": vendors}
    except sqlite3.Error as exc:
        logger.error("Could not read vendors (%s).", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not read vendor choices.") from exc


@app.post("/tickets/{ticket_id}/run", response_model=TicketRunResult)
async def run_ticket(ticket_id: int, request: Request) -> TicketRunResult:
    with closing(_connect(read_only=True)) as connection:
        exists = connection.execute(
            "SELECT status FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} was not found.")
    if str(exists[0]).lower() != "open":
        raise HTTPException(status_code=409, detail="Only open tickets can be run.")

    team: AgentTeam = request.app.state.agent_team
    try:
        result = await team.run_ticket(ticket_id)
        with closing(_connect()) as connection:
            connection.execute(
                "UPDATE tickets SET status = 'resolved' WHERE id = ? AND lower(status) = 'open'",
                (ticket_id,),
            )
            connection.commit()
        audit_trail.append(
            {
                "event": "ticket_marked_resolved",
                "run_id": result.run_id,
                "ticket_id": ticket_id,
                "agent_status": result.status,
                "note": "The agent run finished; human approval requests may still be pending.",
            }
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Ticket %s agent run failed (%s).", ticket_id, type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="The agent run failed. Review the append-only audit trail.",
        ) from exc


def _tool_calls(value: Any) -> list[dict[str, Any]]:
    """Collect tool call names and arguments from serialized agent messages."""
    found: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            part_kind = str(item.get("part_kind", "")).lower().replace("_", "-")
            name = item.get("tool_name") or item.get("name")
            if name and ("tool-call" in part_kind or "tool_call" in part_kind):
                found.append(
                    {
                        "name": str(name),
                        "arguments": item.get("args", item.get("arguments")),
                    }
                )
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for call in found:
        key = json.dumps(call, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(call)
    return unique


@app.get("/events")
async def get_recent_events(
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return recent agent outputs and tool calls from the append-only trail."""
    if not AUDIT_PATH.exists():
        return {"events": [], "count": 0}

    records: list[dict[str, Any]] = []
    try:
        with AUDIT_PATH.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = record.get("event", "")
                if kind.startswith("agent_step_") or kind in {
                    "human_approval_completed", "database_reset", "ticket_marked_resolved"
                }:
                    records.append(record)
    except OSError as exc:
        logger.error("Could not read audit trail (%s).", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not read recent events.") from exc

    selected = records[-limit:]
    events: list[dict[str, Any]] = []
    for record in reversed(selected):
        output = record.get("output")
        calls = _tool_calls(record.get("messages", []))
        event = {
            "event": record.get("event"),
            "logged_at": record.get("logged_at"),
            "run_id": record.get("run_id"),
            "step_number": record.get("step_number"),
            "ticket_id": record.get("ticket_id"),
            "agent_role": record.get("agent_role"),
            "parent_role": record.get("parent_role"),
            "depth": record.get("depth"),
            "task": record.get("task"),
            "said": output.get("summary") if isinstance(output, dict) else None,
            "output": output,
            "tools": calls,
            "usage": record.get("usage"),
        }
        if record.get("reason"):
            event["reason"] = record["reason"]
        if record.get("error_type"):
            event["error_type"] = record["error_type"]
        if record.get("approval"):
            event["approval"] = record["approval"]
        events.append(event)
    return {"events": events, "count": len(events)}


@app.get("/cash")
async def get_checking_balance() -> dict[str, Any]:
    """Return the current checking balance from cash_accounts."""
    try:
        with closing(_connect(read_only=True)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT name, balance, date FROM cash_accounts WHERE name = ?",
                ("checking",),
            ).fetchone()
    except sqlite3.Error as exc:
        logger.error("Could not read checking balance (%s).", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not read the cash balance.") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="The checking account was not found.")
    return {"account": row["name"], "balance": row["balance"], "date": row["date"]}


def _approve_payment(
    connection: sqlite3.Connection,
    command: ApprovalCommand,
    ticket: sqlite3.Row,
    shop_date: str,
) -> dict[str, Any]:
    if command.vendor_id is not None:
        raise HTTPException(status_code=422, detail="A vendor is only selected for purchase orders.")

    if ticket["invoice_id"] is not None:
        reference_kind = "invoice"
        reference_id = int(ticket["invoice_id"])
        record = connection.execute(
            "SELECT id, amount, status FROM invoices WHERE id = ?", (reference_id,)
        ).fetchone()
        if record is None:
            raise HTTPException(status_code=409, detail="The linked invoice was not found.")
        if str(record["status"]).lower() != "open":
            raise HTTPException(status_code=409, detail="The linked invoice is not open and unpaid.")
        amount = Decimal(str(record["amount"]))
        payment_kind = "invoice"
    elif ticket["lease_id"] is not None:
        reference_kind = "lease"
        reference_id = int(ticket["lease_id"])
        record = connection.execute(
            "SELECT id, monthly_rent AS amount FROM leases WHERE id = ?", (reference_id,)
        ).fetchone()
        if record is None:
            raise HTTPException(status_code=409, detail="The linked lease was not found.")
        amount = Decimal(str(record["amount"]))
        payment_kind = "rent"
    else:
        raise HTTPException(
            status_code=409,
            detail="This ticket has no recorded invoice or rent obligation to pay.",
        )

    if command.approved_amount is not None and command.approved_amount != amount:
        raise HTTPException(
            status_code=409,
            detail=f"Approval amount must match the recorded {reference_kind} amount ({amount}).",
        )
    existing = connection.execute(
        "SELECT id FROM payments WHERE kind = ? AND ref_id = ? LIMIT 1",
        (payment_kind, reference_id),
    ).fetchone()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A payment is already recorded for this obligation.")

    account = connection.execute(
        "SELECT balance FROM cash_accounts WHERE name = ?", ("checking",)
    ).fetchone()
    if account is None:
        raise HTTPException(status_code=409, detail="The checking account is missing.")
    balance = Decimal(str(account["balance"]))
    if amount <= 0:
        raise HTTPException(status_code=409, detail="A payment must be greater than zero.")
    if amount > balance:
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient checking cash: {balance} is available for a {amount} payment.",
        )

    connection.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (payment_kind, reference_id, float(amount), "checking", shop_date, command.approved_by.strip()),
    )
    connection.execute(
        "UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?",
        (float(balance - amount), shop_date, "checking"),
    )
    if reference_kind == "invoice":
        connection.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (reference_id,))
        # Paying the vendor bill permits shipment but does not fulfill the customer order.
    else:
        connection.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket["id"],))

    return {
        "kind": payment_kind,
        "reference_table": reference_kind,
        "reference_id": reference_id,
        "amount": float(amount),
        "account": "checking",
        "balance_after": float(balance - amount),
        "paid_at": shop_date,
    }


def _approve_purchase(
    connection: sqlite3.Connection,
    command: ApprovalCommand,
    ticket: sqlite3.Row,
    shop_date: str,
) -> dict[str, Any]:
    if ticket["type"] not in {"customer_order", "price_override"} or not ticket["sku"] or not ticket["size"] or not ticket["qty"]:
        raise HTTPException(status_code=409, detail="This ticket does not describe a product purchase.")
    if command.vendor_id is None:
        raise HTTPException(status_code=422, detail="Choose a recorded vendor before approving a purchase.")
    if command.approved_amount is None:
        raise HTTPException(status_code=422, detail="A human-approved vendor quote amount is required.")
    if not command.confirmed_sku_fit:
        raise HTTPException(
            status_code=422,
            detail="Confirm that the selected vendor quoted the exact requested SKU and size.",
        )

    vendor = connection.execute(
        "SELECT id, name FROM vendors WHERE id = ?", (command.vendor_id,)
    ).fetchone()
    if vendor is None:
        raise HTTPException(status_code=404, detail="The selected vendor was not found.")
    open_invoice = connection.execute(
        "SELECT id FROM invoices WHERE vendor_id = ? AND lower(status) = 'open' LIMIT 1",
        (command.vendor_id,),
    ).fetchone()
    if open_invoice is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Vendor {vendor['name']} has open unpaid invoice {open_invoice['id']} and cannot ship.",
        )
    stock = connection.execute(
        "SELECT qty FROM inventory WHERE sku = ? AND size = ?",
        (ticket["sku"], ticket["size"]),
    ).fetchone()
    if stock is None:
        raise HTTPException(status_code=409, detail="Matching inventory is not recorded.")
    purchase_qty = int(ticket["qty"]) - int(stock["qty"])
    if purchase_qty <= 0:
        raise HTTPException(status_code=409, detail="Recorded stock already covers the ticket quantity.")
    prior = connection.execute(
        "SELECT id FROM purchase_orders WHERE ticket_id = ? AND status = 'approved' LIMIT 1",
        (ticket["id"],),
    ).fetchone()
    if prior is not None:
        raise HTTPException(status_code=409, detail="A purchase order is already recorded for this ticket.")

    balance_row = connection.execute(
        "SELECT balance FROM cash_accounts WHERE name = ?", ("checking",)
    ).fetchone()
    if balance_row is None:
        raise HTTPException(status_code=409, detail="The checking account is missing.")
    balance = Decimal(str(balance_row["balance"]))
    amount = command.approved_amount
    if amount != amount.quantize(Decimal("0.01")):
        raise HTTPException(status_code=422, detail="Purchase amounts must be in cents.")
    if amount <= 0:
        raise HTTPException(status_code=422, detail="A purchase amount must be greater than zero.")
    if amount > balance:
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient checking cash: {balance} is available for a {amount} purchase.",
        )

    cursor = connection.execute(
        """
        INSERT INTO purchase_orders
            (ticket_id, vendor_id, sku, size, qty, amount, status, approved_by, approved_at)
        VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, ?)
        """,
        (
            ticket["id"], command.vendor_id, ticket["sku"], ticket["size"], purchase_qty,
            float(amount), command.approved_by.strip(), shop_date,
        ),
    )
    purchase_order_id = int(cursor.lastrowid)
    connection.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("purchase_order", purchase_order_id, float(amount), "checking", shop_date, command.approved_by.strip()),
    )
    connection.execute(
        "UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?",
        (float(balance - amount), shop_date, "checking"),
    )
    # Inventory and ticket status stay unchanged until receipt and fulfillment are recorded.
    return {
        "kind": "purchase_order",
        "purchase_order_id": purchase_order_id,
        "ticket_id": int(ticket["id"]),
        "vendor_id": int(vendor["id"]),
        "vendor_name": vendor["name"],
        "sku": ticket["sku"],
        "size": ticket["size"],
        "qty": purchase_qty,
        "amount": float(amount),
        "account": "checking",
        "balance_after": float(balance - amount),
        "approved_at": shop_date,
        "status": "approved; order not placed and stock not received",
    }


@app.post("/approvals")
async def approve_payment_or_purchase(command: ApprovalCommand) -> dict[str, Any]:
    """Record a human-approved payment or purchase and deduct checking cash."""
    if not command.approved_by.strip():
        raise HTTPException(status_code=422, detail="approved_by must name the human approver.")

    with closing(_connect()) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            ticket = connection.execute(
                "SELECT * FROM tickets WHERE id = ?", (command.ticket_id,)
            ).fetchone()
            if ticket is None:
                raise HTTPException(status_code=404, detail="The ticket was not found.")
            desk = connection.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
            if desk is None:
                raise HTTPException(status_code=409, detail="The shop date is not recorded.")
            shop_date = str(desk["date_today"])

            if command.kind == "payment":
                approval = _approve_payment(connection, command, ticket, shop_date)
            else:
                approval = _approve_purchase(connection, command, ticket, shop_date)
            connection.commit()
        except HTTPException:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            logger.error("Approval transaction failed (%s).", type(exc).__name__)
            raise HTTPException(status_code=500, detail="Could not record the approved action.") from exc

    audit_trail.append(
        {
            "event": "human_approval_completed",
            "ticket_id": command.ticket_id,
            "approved_by": command.approved_by.strip(),
            "approval": approval,
        }
    )
    return {"approved": True, "approval": approval}


@app.post("/reset")
async def reset_database(command: ResetCommand) -> dict[str, Any]:
    """Restore the working copy from the untouched original database."""
    if not ORIGINAL_DATABASE_PATH.is_file():
        raise HTTPException(status_code=500, detail="The original database copy was not found.")
    try:
        with closing(sqlite3.connect(ORIGINAL_DATABASE_PATH, timeout=10)) as source:
            with closing(sqlite3.connect(DATABASE_PATH, timeout=10)) as destination:
                source.backup(destination)
        with closing(_connect()) as connection:
            _ensure_support_schema(connection)
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT name, balance, date FROM cash_accounts WHERE name = ?", ("checking",)
            ).fetchone()
            count = connection.execute("SELECT count(*) FROM tickets").fetchone()[0]
    except sqlite3.Error as exc:
        logger.error("Database reset failed (%s).", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not restore the working database.") from exc

    audit_trail.append(
        {
            "event": "database_reset",
            "source": str(ORIGINAL_DATABASE_PATH.relative_to(PROJECT_ROOT)),
            "tickets_restored": count,
        }
    )
    return {
        "reset": True,
        "tickets_restored": count,
        "checking": dict(row) if row is not None else None,
        "audit_trail_preserved": True,
    }


FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
