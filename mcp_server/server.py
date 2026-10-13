"""Read-only MCP tools for the open Campus Customs tickets."""

from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any

from mcp.server.fastmcp import FastMCP


DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "campus_customs_new.db"
mcp = FastMCP("Campus Customs")


def _fetch_one(query: str, values: tuple[Any, ...]) -> dict[str, Any] | None:
    """Run a parameterized read query and return one row as a dictionary."""
    database_uri = f"{DATABASE_PATH.as_uri()}?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(query, values).fetchone()
        return dict(row) if row is not None else None


def _fetch_all(query: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a parameterized read query and return all rows as dictionaries."""
    database_uri = f"{DATABASE_PATH.as_uri()}?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(query, values).fetchall()]


@mcp.tool()
def list_open_tickets() -> dict[str, Any]:
    """List the open work-board tickets and the shop's database date."""
    desk = _fetch_one("SELECT date_today FROM desk LIMIT 1", ())
    tickets = _fetch_all(
        """
        SELECT id, type, requester, subject, sku, size, qty, lease_id,
               invoice_id, status, notes, created_at
        FROM tickets
        WHERE status = 'open'
        ORDER BY id
        """
    )
    return {"shop_date": desk["date_today"] if desk else None, "tickets": tickets}


@mcp.tool()
def get_customer_order_context(ticket_id: int) -> dict[str, Any]:
    """Read the order's stock, linked vendor invoice, and vendor lead time."""
    row = _fetch_one(
        """
        SELECT
            t.id AS ticket_id,
            t.type AS ticket_type,
            t.requester,
            t.subject,
            t.sku,
            t.size,
            t.qty AS requested_qty,
            t.status AS ticket_status,
            t.notes AS ticket_notes,
            d.date_today AS shop_date,
            inv.qty AS stock_qty,
            inv.location AS stock_location,
            i.id AS invoice_id,
            i.amount AS invoice_amount,
            i.due_date AS invoice_due_date,
            i.status AS invoice_status,
            v.id AS vendor_id,
            v.name AS vendor_name,
            v.specialty AS vendor_specialty,
            v.lead_days AS vendor_lead_days
        FROM tickets AS t
        LEFT JOIN desk AS d ON 1 = 1
        LEFT JOIN inventory AS inv
            ON inv.sku = t.sku AND inv.size = t.size
        LEFT JOIN invoices AS i ON i.id = t.invoice_id
        LEFT JOIN vendors AS v ON v.id = i.vendor_id
        WHERE t.id = ?
        """,
        (ticket_id,),
    )
    if row is None:
        return {"error": f"Ticket {ticket_id} was not found."}
    if row["ticket_type"] != "customer_order":
        return {"error": f"Ticket {ticket_id} is not a customer order."}
    return row


@mcp.tool()
def get_rent_notice_context(ticket_id: int) -> dict[str, Any]:
    """Read a rent notice and the lease record it references."""
    row = _fetch_one(
        """
        SELECT
            t.id AS ticket_id,
            t.type AS ticket_type,
            t.requester,
            t.subject,
            t.status AS ticket_status,
            t.notes AS ticket_notes,
            d.date_today AS shop_date,
            l.id AS lease_id,
            l.space_name,
            l.landlord,
            l.monthly_rent,
            l.next_due,
            l.notes AS lease_notes
        FROM tickets AS t
        LEFT JOIN desk AS d ON 1 = 1
        LEFT JOIN leases AS l ON l.id = t.lease_id
        WHERE t.id = ?
        """,
        (ticket_id,),
    )
    if row is None:
        return {"error": f"Ticket {ticket_id} was not found."}
    if row["ticket_type"] != "rent_notice":
        return {"error": f"Ticket {ticket_id} is not a rent notice."}
    return row


@mcp.tool()
def get_bulk_discount_context(ticket_id: int) -> dict[str, Any]:
    """Read a bulk order's requested quantity, stock, and recorded prices."""
    row = _fetch_one(
        """
        SELECT
            t.id AS ticket_id,
            t.type AS ticket_type,
            t.requester,
            t.subject,
            t.sku,
            t.size,
            t.qty AS requested_qty,
            t.status AS ticket_status,
            t.notes AS ticket_notes,
            d.date_today AS shop_date,
            inv.qty AS stock_qty,
            inv.location AS stock_location,
            p.unit_cost,
            p.list_price
        FROM tickets AS t
        LEFT JOIN desk AS d ON 1 = 1
        LEFT JOIN inventory AS inv
            ON inv.sku = t.sku AND inv.size = t.size
        LEFT JOIN pricing AS p ON p.sku = t.sku
        WHERE t.id = ?
        """,
        (ticket_id,),
    )
    if row is None:
        return {"error": f"Ticket {ticket_id} was not found."}
    if row["ticket_type"] != "price_override":
        return {"error": f"Ticket {ticket_id} is not a price override request."}
    return row


@mcp.tool()
def get_accounting_context(ticket_id: int) -> dict[str, Any]:
    """Read cash, dates, payments, and the invoice or lease linked to a ticket."""
    ticket = _fetch_one(
        """
        SELECT id, type, requester, subject, sku, size, qty,
               lease_id, invoice_id, status, notes, created_at
        FROM tickets WHERE id = ?
        """,
        (ticket_id,),
    )
    if ticket is None:
        return {"error": f"Ticket {ticket_id} was not found."}

    desk = _fetch_one("SELECT date_today FROM desk LIMIT 1", ())
    cash_accounts = _fetch_all(
        "SELECT name, balance, date FROM cash_accounts ORDER BY name"
    )
    payments = _fetch_all(
        """
        SELECT id, kind, ref_id, amount, account, paid_at, approved_by
        FROM payments ORDER BY id
        """
    )
    invoice = (
        _fetch_one(
            """
            SELECT id, vendor_id, amount, due_date, status, description
            FROM invoices WHERE id = ?
            """,
            (ticket["invoice_id"],),
        )
        if ticket["invoice_id"] is not None
        else None
    )
    invoice_vendor = (
        _fetch_one(
            "SELECT id, name, specialty, lead_days FROM vendors WHERE id = ?",
            (invoice["vendor_id"],),
        )
        if invoice is not None and invoice["vendor_id"] is not None
        else None
    )
    lease = (
        _fetch_one(
            """
            SELECT id, space_name, landlord, monthly_rent, next_due, notes
            FROM leases WHERE id = ?
            """,
            (ticket["lease_id"],),
        )
        if ticket["lease_id"] is not None
        else None
    )
    return {
        "ticket": ticket,
        "shop_date": desk["date_today"] if desk else None,
        "cash_accounts": cash_accounts,
        "invoice": invoice,
        "invoice_vendor": invoice_vendor,
        "lease": lease,
        "payments": payments,
    }


@mcp.tool()
def get_restock_context(ticket_id: int) -> dict[str, Any]:
    """Read requested stock, inventory, vendor lead times, and vendor invoices."""
    ticket = _fetch_one(
        """
        SELECT id, type, requester, subject, sku, size, qty, status, notes
        FROM tickets WHERE id = ?
        """,
        (ticket_id,),
    )
    if ticket is None:
        return {"error": f"Ticket {ticket_id} was not found."}

    inventory = None
    if ticket["sku"] is not None and ticket["size"] is not None:
        inventory = _fetch_one(
            """
            SELECT sku, name, size, qty, location
            FROM inventory WHERE sku = ? AND size = ?
            """,
            (ticket["sku"], ticket["size"]),
        )
    desk = _fetch_one("SELECT date_today FROM desk LIMIT 1", ())
    vendors = _fetch_all(
        """
        SELECT v.id AS vendor_id, v.name AS vendor_name,
               v.specialty, v.lead_days,
               i.id AS invoice_id, i.amount AS invoice_amount,
               i.due_date AS invoice_due_date,
               i.status AS invoice_status,
               i.description AS invoice_description
        FROM vendors AS v
        LEFT JOIN invoices AS i ON i.vendor_id = v.id
        ORDER BY v.id, i.id
        """
    )
    return {
        "ticket": ticket,
        "shop_date": desk["date_today"] if desk else None,
        "inventory": inventory,
        "vendors_and_invoices": vendors,
    }


if __name__ == "__main__":
    mcp.run()
