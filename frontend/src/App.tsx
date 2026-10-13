import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
let dashboardAuthorization: string | null = null

function makeBasicAuthorization(username: string, password: string) {
  const bytes = new TextEncoder().encode(`${username}:${password}`)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return `Basic ${window.btoa(binary)}`
}

type Ticket = {
  id: number
  type: string
  requester: string
  subject: string
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  status: string
  notes: string | null
  created_at: string
  is_open: boolean
  is_resolved: boolean
}

type ToolUse = { name: string; arguments?: unknown }
type ApprovalRequest = {
  kind: 'payment' | 'purchase_order' | 'discount'
  reference_table?: string | null
  reference_id?: number | null
  amount?: number | null
  amount_basis?: string
  reason: string
  requires_human_approval: true
}
type AgentOutput = {
  summary?: string
  facts?: { table: string; record_id?: string | number | null; field: string; value: unknown }[]
  recommendations?: string[]
  approval_requests?: ApprovalRequest[]
  draft_messages?: { recipient: string; subject: string; body: string; delivery_status: string }[]
  unresolved_questions?: string[]
}
type DeskEvent = {
  event: string
  logged_at?: string
  run_id?: string
  step_number?: number
  ticket_id?: number
  agent_role?: string
  parent_role?: string | null
  depth?: number
  task?: string
  said?: string | null
  output?: AgentOutput | null
  tools?: ToolUse[]
  reason?: string
  error_type?: string
  approval?: Record<string, unknown>
  usage?: Record<string, unknown>
}
type Vendor = {
  id: number
  name: string
  specialty: string
  lead_days: number
  open_invoice_ids: number[]
  can_ship: boolean
}
type Cash = { account: string; balance: number; date: string }
type RunResult = { run_id: string; ticket_id: number; status: string; agent_steps: number }
type RoleName = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'

const ROLES: { id: RoleName; name: string; mark: string; description: string }[] = [
  { id: 'boss', name: 'Boss', mark: 'B', description: 'Routing & final call' },
  { id: 'inventory', name: 'Inventory', mark: 'I', description: 'Stock & restock' },
  { id: 'accounting', name: 'Accounting', mark: 'A', description: 'Cash & margin' },
  { id: 'facilities', name: 'Facilities', mark: 'F', description: 'Lease & rent' },
  { id: 'customer_service', name: 'Customer Service', mark: 'CS', description: 'Unsent drafts' },
]

const ticketLabel: Record<string, string> = {
  customer_order: 'Customer order',
  rent_notice: 'Rent notice',
  price_override: 'Price exception',
}

function Icon({ name, size = 18 }: { name: 'spark' | 'arrow' | 'clock' | 'check' | 'box' | 'wallet' | 'refresh' | 'send' | 'chevron' | 'radio'; size?: number }) {
  const shared = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const }
  const shapes: Record<string, ReactNode> = {
    spark: <><path d="m12 3 1.5 6.5L20 12l-6.5 1.5L12 20l-1.5-6.5L4 12l6.5-2.5L12 3Z" /><path d="m19 3 .6 2.4L22 6l-2.4.6L19 9l-.6-2.4L16 6l2.4-.6L19 3Z" /></>,
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    check: <><path d="m5 12 4 4L19 6" /></>,
    box: <><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="M3 8v8l9 5 9-5V8" /><path d="M12 13v8" /></>,
    wallet: <><rect x="3" y="5" width="18" height="15" rx="3" /><path d="M3 9h18" /><path d="M16 14h2" /><path d="M6 5V3h12v2" /></>,
    refresh: <><path d="M20 7v5h-5" /><path d="M4 17v-5h5" /><path d="M5.6 9a7 7 0 0 1 11.8-2L20 12M4 12l2.6 5a7 7 0 0 0 11.8-2" /></>,
    send: <><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></>,
    chevron: <path d="m9 18 6-6-6-6" />,
    radio: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" /></>,
  }
  return <svg {...shared}>{shapes[name]}</svg>
}

function money(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return 'Amount pending'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value)
}

function relativeTime(value?: string) {
  if (!value) return 'just now'
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return 'just now'
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000))
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  return `${Math.floor(seconds / 60)}m ago`
}

async function readJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (dashboardAuthorization) headers.set('Authorization', dashboardAuthorization)
  const response = await fetch(url, { ...init, headers })
  const data = await response.json().catch(() => ({}))
  if (response.status === 401) window.dispatchEvent(new Event('cc-auth-required'))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`)
  return data as T
}

function AccessGate({ onUnlock }: { onUnlock: (username: string, password: string) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  return (
    <div className="access-backdrop">
      <form className="access-card" onSubmit={(event) => { event.preventDefault(); onUnlock(username, password) }}>
        <span className="section-kicker">CAMPUS CUSTOMS / PRIVATE DESK</span>
        <h2>Sign in to the operations desk</h2>
        <p>This deployment is access controlled. Use the credentials shared by the desk owner.</p>
        <label className="field-label" htmlFor="desk-user">Username</label>
        <input id="desk-user" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required />
        <label className="field-label" htmlFor="desk-password">Password</label>
        <input id="desk-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        <button className="run-button" type="submit">Open the desk <Icon name="arrow" size={16} /></button>
      </form>
    </div>
  )
}

function ApprovalCard({
  ticket,
  request,
  approved,
  vendors,
  onApprove,
}: {
  ticket: Ticket
  request: ApprovalRequest
  approved: boolean
  vendors: Vendor[]
  onApprove: (payload: Record<string, unknown>) => Promise<void>
}) {
  const [approver, setApprover] = useState('')
  const [vendorId, setVendorId] = useState('')
  const [quotedAmount, setQuotedAmount] = useState(request.amount == null ? '' : String(request.amount))
  const [skuFit, setSkuFit] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const isPurchase = request.kind === 'purchase_order'
  const isPayment = request.kind === 'payment'
  const validVendor = vendors.find((vendor) => vendor.id === Number(vendorId))
  const canSubmit = approver.trim().length > 0 && !busy && (isPayment || (
    Boolean(validVendor?.can_ship) && Number(quotedAmount) > 0 && skuFit
  ))

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) return
    setBusy(true)
    setError('')
    const payload: Record<string, unknown> = {
      ticket_id: ticket.id,
      kind: request.kind,
      approved_by: approver.trim(),
      confirm: true,
    }
    if (isPayment && request.amount != null) payload.approved_amount = request.amount
    if (isPurchase) {
      payload.vendor_id = Number(vendorId)
      payload.approved_amount = Number(quotedAmount)
      payload.confirmed_sku_fit = skuFit
    }
    try {
      await onApprove(payload)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not record this approval.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className={`approval-card ${approved ? 'approval-card--done' : ''}`}>
      <div className="approval-card__top">
        <span className={`approval-stamp ${approved ? 'approval-stamp--done' : ''}`}>
          <Icon name={approved ? 'check' : 'wallet'} size={15} />
        </span>
        <div className="approval-card__heading">
          <strong>{isPayment ? 'Payment approval' : isPurchase ? 'Purchase approval' : 'Discount decision'}</strong>
          <span>{approved ? 'Human approval recorded' : 'Waiting for your decision'}</span>
        </div>
        <span className={`approval-state ${approved ? 'is-approved' : ''}`}>{approved ? 'Approved' : 'Review'}</span>
      </div>
      <p className="approval-reason">{request.reason}</p>
      {request.reference_id != null && (
        <div className="approval-reference">
          <span>{request.reference_table ?? (isPurchase ? 'Ticket' : 'Record')} #{request.reference_id}</span>
          <b>{money(request.amount)}</b>
        </div>
      )}

      {isPurchase && !approved && (
        <div className="purchase-details">
          <label className="field-label" htmlFor={`vendor-${ticket.id}`}>Vendor quote</label>
          <select id={`vendor-${ticket.id}`} value={vendorId} onChange={(event) => setVendorId(event.target.value)}>
            <option value="">Choose an eligible vendor</option>
            {vendors.map((vendor) => (
              <option key={vendor.id} value={vendor.id} disabled={!vendor.can_ship}>
                {vendor.name}{vendor.can_ship ? ` · ${vendor.lead_days}d lead` : ` · invoice #${vendor.open_invoice_ids.join(', #')} open`}
              </option>
            ))}
          </select>
          {validVendor && <small>{validVendor.specialty} · Lead time {validVendor.lead_days} days</small>}
          <label className="field-label" htmlFor={`quote-${ticket.id}`}>Quoted total</label>
          <div className="money-input"><span>$</span><input id={`quote-${ticket.id}`} type="number" min="0.01" step="0.01" value={quotedAmount} onChange={(event) => setQuotedAmount(event.target.value)} placeholder="0.00" /></div>
          <label className="confirm-fit"><input type="checkbox" checked={skuFit} onChange={(event) => setSkuFit(event.target.checked)} /> I verified this quote is for the exact SKU and size.</label>
        </div>
      )}
      {request.kind === 'discount' && !approved && <p className="approval-note">A discount is a human pricing decision. This board has no discount write route.</p>}
      {!approved && (isPayment || isPurchase) && (
        <form className="approval-form" onSubmit={submit}>
          <label className="field-label" htmlFor={`approver-${ticket.id}-${request.kind}`}>Your name</label>
          <input id={`approver-${ticket.id}-${request.kind}`} value={approver} onChange={(event) => setApprover(event.target.value)} placeholder="Approver name" maxLength={120} required />
          {error && <p className="form-error">{error}</p>}
          <button className="approve-button" disabled={!canSubmit} type="submit">
            {busy ? <><span className="mini-spinner" /> Recording…</> : <>{isPayment ? 'Approve & pay' : 'Approve purchase'} <Icon name="arrow" size={16} /></>}
          </button>
        </form>
      )}
    </article>
  )
}

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [events, setEvents] = useState<DeskEvent[]>([])
  const [vendors, setVendors] = useState<Vendor[]>([])
  const [cash, setCash] = useState<Cash | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [runStates, setRunStates] = useState<Record<number, { state: 'idle' | 'running' | 'finished' | 'error'; runId?: string; startedAt?: number; error?: string }>>({})
  const [loading, setLoading] = useState(true)
  const [connectionError, setConnectionError] = useState('')
  const [toast, setToast] = useState('')
  const [lastRefresh, setLastRefresh] = useState(Date.now())
  const [authRequired, setAuthRequired] = useState(false)

  useEffect(() => {
    const requestSignIn = () => setAuthRequired(true)
    window.addEventListener('cc-auth-required', requestSignIn)
    return () => window.removeEventListener('cc-auth-required', requestSignIn)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [ticketResult, eventResult, cashResult, vendorResult] = await Promise.all([
        readJson<{ tickets: Ticket[] }>(`${API}/tickets`),
        readJson<{ events: DeskEvent[] }>(`${API}/events?limit=150`),
        readJson<Cash>(`${API}/cash`),
        readJson<{ vendors: Vendor[] }>(`${API}/vendors`),
      ])
      setTickets(ticketResult.tickets)
      setEvents(eventResult.events)
      setCash(cashResult)
      setVendors(vendorResult.vendors)
      setSelectedId((current) => current ?? ticketResult.tickets[0]?.id ?? null)
      setConnectionError('')
      setLastRefresh(Date.now())
    } catch (caught) {
      setConnectionError(caught instanceof Error ? caught.message : 'Backend connection failed.')
    } finally {
      setLoading(false)
    }
  }, [])

  function unlockDesk(username: string, password: string) {
    dashboardAuthorization = makeBasicAuthorization(username, password)
    setAuthRequired(false)
    void refresh()
  }

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 2300)
    return () => window.clearInterval(timer)
  }, [refresh])

  const selectedTicket = tickets.find((ticket) => ticket.id === selectedId) ?? null
  const runningId = useMemo(() => Object.entries(runStates).find(([, state]) => state.state === 'running')?.[0], [runStates])
  const ticketEvents = useMemo(() => {
    if (!selectedTicket) return []
    const all = events.filter((event) => event.ticket_id === selectedTicket.id)
    const resolved = all.find((event) => event.event === 'ticket_marked_resolved')
    const runId = runStates[selectedTicket.id]?.runId ?? resolved?.run_id ?? all.find((event) => event.run_id)?.run_id
    return runId ? all.filter((event) => event.run_id === runId) : all
  }, [events, runStates, selectedTicket])

  const latestByRole = useMemo(() => {
    const map: Partial<Record<RoleName, DeskEvent>> = {}
    for (const event of ticketEvents) {
      if (event.agent_role && !(event.agent_role in map)) map[event.agent_role as RoleName] = event
    }
    return map
  }, [ticketEvents])

  const approvalItems = useMemo(() => {
    const items: { event: DeskEvent; request: ApprovalRequest }[] = []
    for (const event of ticketEvents) {
      if (event.event !== 'agent_step_completed') continue
      for (const request of event.output?.approval_requests ?? []) {
        const alreadyAdded = items.some(({ request: prior }) => prior.kind === request.kind && prior.reference_id === request.reference_id)
        if (!alreadyAdded) items.push({ event, request })
      }
    }
    return items
  }, [ticketEvents])

  const countResolved = tickets.filter((ticket) => ticket.is_resolved).length
  const countOpen = tickets.filter((ticket) => ticket.is_open).length
  const outflow = cash ? Math.max(0, 3400 - cash.balance) : 0
  const activeTicket = runningId ? tickets.find((ticket) => ticket.id === Number(runningId)) : null

  async function startRun(ticket: Ticket) {
    if (!ticket.is_open || runningId) return
    const startedAt = Date.now()
    setRunStates((current) => ({ ...current, [ticket.id]: { state: 'running', startedAt } }))
    setToast('')
    try {
      const result = await readJson<RunResult>(`${API}/tickets/${ticket.id}/run`, { method: 'POST' })
      setRunStates((current) => ({ ...current, [ticket.id]: { state: 'finished', runId: result.run_id, startedAt } }))
      setToast(`Ticket ${ticket.id} analysis complete · ${result.agent_steps} agent steps recorded`)
      await refresh()
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Agent run failed.'
      setRunStates((current) => ({ ...current, [ticket.id]: { state: 'error', startedAt, error: message } }))
      setToast(message)
      await refresh()
    }
  }

  async function approve(payload: Record<string, unknown>) {
    await readJson<{ approved: boolean }>(`${API}/approvals`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    setToast('Approval recorded. Checking balance and board are refreshed.')
    await refresh()
  }

  function isApproved(request: ApprovalRequest) {
    return events.some((event) => {
      if (event.ticket_id !== selectedTicket?.id || event.event !== 'human_approval_completed') return false
      const approval = event.approval ?? {}
      const kind = String(approval.kind ?? '')
      if (request.kind === 'purchase_order') return kind === 'purchase_order'
      if (request.kind === 'payment') return kind === 'invoice' || kind === 'rent'
      return false
    })
  }

  const orderedEvents = [...ticketEvents].sort((a, b) => new Date(b.logged_at ?? 0).getTime() - new Date(a.logged_at ?? 0).getTime())

  return (
    <>
    {authRequired && <AccessGate onUnlock={unlockDesk} />}
    <div className="app-shell">
      <aside className="rail">
        <div className="brand-lockup">
          <div className="brand-mark"><span>CC</span><i /></div>
          <div><strong>campus<br />customs</strong><small>multi-agent ops</small></div>
        </div>
        <div className="rail-rule" />
        <div className="rail-label">WORKSPACE</div>
        <button className="rail-link rail-link--active" type="button"><span className="rail-glyph"><Icon name="box" /></span>Desk <span className="rail-count">{tickets.length || '—'}</span></button>
        <div className="rail-spacer" />
        <div className="rail-bottom">
          <div className={`connection-dot ${connectionError ? 'connection-dot--off' : ''}`} />
          <span>{connectionError ? 'Backend offline' : 'Backend connected'}</span>
          <small>LOCAL · PORT 8000</small>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><span>WORKSPACE</span><Icon name="chevron" size={14} /><b>The desk</b></div>
          <div className="topbar-right">
            <div className="shop-date"><span className="date-dot" /> SHOP DATE <b>{cash?.date ?? '—'}</b></div>
            <div className="avatar" title="Human reviewer">D</div>
          </div>
        </header>

        {connectionError && (
          <div className="connection-banner"><span><Icon name="radio" size={16} /> Can’t reach the backend: {connectionError}</span><button onClick={() => void refresh()} type="button"><Icon name="refresh" size={15} /> Retry</button></div>
        )}
        {toast && <div className="toast-line"><Icon name="check" size={15} /> {toast}</div>}

        <section className="welcome-row">
          <div>
            <div className="overline"><span className="overline-mark" /> CONTROL ROOM <span className="overline-sep">/</span> OPEN TICKETS</div>
            <h1>The desk<span className="title-period">.</span></h1>
            <p>Good work gets done together. Pick up a ticket and let the crew take a first pass.</p>
          </div>
          <div className="welcome-note">
            <span className="note-pin" />
            <small>SHIFT NOTE</small>
            <p>Agents can recommend.<br /><em>You make the call.</em></p>
            <span className="note-lines" />
          </div>
        </section>

        <section className="metric-row" aria-label="Desk overview">
          <div className="metric-card metric-card--tickets"><span className="metric-icon"><Icon name="box" /></span><div><small>IN THE QUEUE</small><b>{loading ? '—' : tickets.length.toString().padStart(2, '0')}</b></div><span className="metric-foot">{countOpen} open <i /> {countResolved} resolved</span></div>
          <div className="metric-card metric-card--cash"><span className="metric-icon"><Icon name="wallet" /></span><div><small>CHECKING BALANCE</small><b>{cash ? money(cash.balance) : '—'}</b></div><span className="metric-foot">{outflow > 0 ? `${money(outflow)} paid out so far` : 'No cash has gone out'} <i className="small-pink-dot" /></span></div>
          <div className="metric-card metric-card--pulse"><span className="metric-icon"><Icon name="spark" /></span><div><small>CREW STATUS</small><b>{runningId ? 'On the move' : 'Standing by'}</b></div><span className="metric-foot">5 specialist roles <i className="green-dot" /></span></div>
        </section>

        <div className="desk-grid">
          <section className="queue-column">
            <div className="section-head"><div><span className="section-kicker">YOUR BOARD</span><h2>Tickets <span>{tickets.length}</span></h2></div><button className="icon-button" type="button" aria-label="Refresh desk" onClick={() => void refresh()}><Icon name="refresh" size={16} /></button></div>
            <div className="queue-list">
              {tickets.map((ticket, index) => {
                const selected = ticket.id === selectedId
                const running = runStates[ticket.id]?.state === 'running'
                return (
                  <button className={`ticket-card ${selected ? 'ticket-card--selected' : ''}`} type="button" key={ticket.id} onClick={() => setSelectedId(ticket.id)}>
                    <div className="ticket-card__top"><span className="ticket-number">#{ticket.id}</span><span className={`queue-status ${ticket.is_resolved ? 'queue-status--resolved' : ''}`}>{running ? <><i className="tiny-spinner" /> Running</> : ticket.is_resolved ? <><Icon name="check" size={12} /> Resolved</> : 'Open'}</span></div>
                    <strong>{ticket.subject}</strong>
                    <span className="ticket-requester">{ticket.requester}</span>
                    <div className="ticket-card__bottom"><span>{ticketLabel[ticket.type] ?? ticket.type}</span><Icon name="chevron" size={15} /></div>
                    {selected && <span className="selected-edge" />}
                    {index === 0 && !ticket.is_resolved && <span className="priority-dot" title="First in queue" />}
                  </button>
                )
              })}
              {!loading && tickets.length === 0 && <div className="empty-queue">No tickets on the board.</div>}
            </div>
            <div className="queue-footnote"><span className="tiny-star">✳</span><p><b>Every ticket is a team effort.</b><br />The Boss routes. Specialists help. You decide.</p></div>
          </section>

          <section className="work-column">
            {!selectedTicket ? (
              <div className="empty-work"><span>✳</span><h2>Choose a ticket</h2><p>Pick a card from the board to get started.</p></div>
            ) : (
              <>
                <div className="work-header">
                  <div className="work-breadcrumb"><span>DESK</span><Icon name="chevron" size={13} /><span>TICKET #{selectedTicket.id}</span></div>
                  <div className={`resolution-pill ${selectedTicket.is_resolved ? 'resolution-pill--done' : ''}`}><span />{selectedTicket.is_resolved ? 'Resolved' : 'Open ticket'}</div>
                </div>
                <div className="ticket-title-block">
                  <span className="type-label">{ticketLabel[selectedTicket.type] ?? selectedTicket.type}</span>
                  <h2>{selectedTicket.subject}</h2>
                  <p>From <b>{selectedTicket.requester}</b><span className="title-divider">·</span>Ticket #{selectedTicket.id}</p>
                </div>

                <div className="request-card">
                  <div className="request-card__label"><span>THE REQUEST</span><span>{relativeTime(selectedTicket.created_at)}</span></div>
                  <p>{selectedTicket.notes || 'No additional notes attached to this ticket.'}</p>
                  {selectedTicket.sku && <div className="request-meta"><span><small>ITEM</small><b>{selectedTicket.sku}</b></span>{selectedTicket.size && <span><small>SIZE</small><b>{selectedTicket.size}</b></span>}{selectedTicket.qty != null && <span><small>QTY</small><b>{selectedTicket.qty}</b></span>}</div>}
                  {selectedTicket.invoice_id && <div className="linked-record"><span>LINKED BILL</span><b>Invoice #{selectedTicket.invoice_id}</b><span className="link-arrow">↗</span></div>}
                  {selectedTicket.lease_id && <div className="linked-record"><span>LEASE RECORD</span><b>Lease #{selectedTicket.lease_id}</b><span className="link-arrow">↗</span></div>}
                </div>

                <div className="run-card">
                  <div className="run-orbit"><Icon name="spark" size={23} /></div>
                  <div className="run-copy"><strong>{runStates[selectedTicket.id]?.state === 'running' ? 'The crew is on it' : selectedTicket.is_resolved ? 'First pass complete' : 'Ready when you are'}</strong><span>{runStates[selectedTicket.id]?.state === 'running' ? `Working ticket #${selectedTicket.id} · ${relativeTime(new Date(runStates[selectedTicket.id]?.startedAt ?? Date.now()).toISOString())}` : selectedTicket.is_resolved ? 'Review the team notes and any pending approvals below.' : 'Boss will bring in the specialists this ticket needs.'}</span></div>
                  <button className="run-button" type="button" disabled={!selectedTicket.is_open || Boolean(runningId) || loading} onClick={() => void startRun(selectedTicket)}>
                    {runStates[selectedTicket.id]?.state === 'running' ? <><span className="button-spinner" /> Running</> : selectedTicket.is_resolved ? <>Run complete <Icon name="check" size={16} /></> : <>Start the crew <Icon name="arrow" size={16} /></>}
                  </button>
                  {runStates[selectedTicket.id]?.state === 'error' && <p className="run-error">{runStates[selectedTicket.id]?.error}</p>}
                </div>

                {approvalItems.length > 0 && (
                  <section className="approvals-section">
                    <div className="subsection-title"><div><span className="section-kicker">HUMAN REVIEW</span><h3>Needs your call <span>{approvalItems.filter(({ request }) => !isApproved(request)).length}</span></h3></div><span className="human-only"><span /> HUMAN ONLY</span></div>
                    <div className="approval-list">
                      {approvalItems.map(({ event, request }, index) => <ApprovalCard key={`${event.run_id}-${request.kind}-${request.reference_id ?? index}`} ticket={selectedTicket} request={request} approved={isApproved(request)} vendors={vendors} onApprove={approve} />)}
                    </div>
                  </section>
                )}
                {approvalItems.length === 0 && selectedTicket.is_resolved && (
                  <div className="quiet-success"><span><Icon name="check" size={17} /></span><div><b>Team pass complete</b><small>No approval request was recorded for this run.</small></div></div>
                )}
              </>
            )}
          </section>

          <aside className="crew-column">
            <div className="crew-heading"><div><span className="section-kicker">LIVE CREW</span><h2>On the desk</h2></div><span className={`live-indicator ${runStates[selectedId ?? 0]?.state === 'running' ? 'live-indicator--active' : ''}`}><i />{runStates[selectedId ?? 0]?.state === 'running' ? 'LIVE' : 'READY'}</span></div>
            <p className="crew-intro">{activeTicket ? `Talking through ticket #${activeTicket.id}` : selectedTicket ? `The team for ticket #${selectedTicket.id}` : 'Five roles, one shared desk.'}</p>
            <div className="crew-list">
              {ROLES.map((role) => {
                const event = latestByRole[role.id]
                const status = !event ? 'standby' : event.event === 'agent_step_started' ? 'working' : event.event === 'agent_step_failed' || event.event === 'agent_step_blocked' ? 'attention' : 'done'
                const stateText = status === 'working' ? 'Working now' : status === 'done' ? 'Pass complete' : status === 'attention' ? 'Needs a look' : 'On standby'
                return (
                  <article className={`crew-card role-${role.id} ${status === 'working' ? 'crew-card--working' : ''}`} key={role.id}>
                    <div className="crew-mark">{role.mark}</div>
                    <div className="crew-card__body"><div className="crew-card__top"><b>{role.name}</b><span className={`crew-status crew-status--${status}`}><i />{stateText}</span></div>
                      <p>{event?.said || (status === 'working' ? event?.task : null) || role.description}</p>
                      {event?.tools && event.tools.length > 0 && <div className="tool-chips">{event.tools.slice(0, 3).map((tool, index) => <code key={`${tool.name}-${index}`}>{tool.name.replace('get_', '').replaceAll('_', ' ')}</code>)}</div>}
                    </div>
                  </article>
                )
              })}
            </div>

            <div className="activity-heading"><div><span className="section-kicker">FIELD NOTES</span><h3>What’s happening</h3></div><span className="refresh-age">Updated {relativeTime(new Date(lastRefresh).toISOString())}</span></div>
            <div className="activity-feed">
              {orderedEvents.filter((event) => event.event.startsWith('agent_step_')).slice(0, 8).map((event, index) => {
                const role = ROLES.find((item) => item.id === event.agent_role)
                const isStart = event.event === 'agent_step_started'
                return (
                  <article className="activity-item" key={`${event.run_id}-${event.step_number}-${event.event}-${index}`}>
                    <div className={`activity-mark role-${event.agent_role ?? 'boss'}`}>{role?.mark ?? '•'}</div>
                    <div className="activity-copy"><div className="activity-meta"><b>{role?.name ?? event.agent_role ?? 'Desk'}</b><time>{relativeTime(event.logged_at)}</time></div>
                      <p>{event.said || (isStart ? event.task : event.reason) || event.error_type || 'Agent step updated.'}</p>
                      {!isStart && event.tools && event.tools.length > 0 && <small><Icon name="spark" size={12} /> {event.tools.map((tool) => tool.name).join(' · ')}</small>}
                    </div>
                  </article>
                )
              })}
              {orderedEvents.filter((event) => event.event.startsWith('agent_step_')).length === 0 && <div className="feed-empty"><span className="empty-sun">✳</span><p>No notes yet.<br /><b>Your crew will leave a trail here.</b></p></div>}
            </div>
            <div className="crew-signoff"><span>✳</span><p>Made for people who<br /><em>keep the shop moving.</em></p><b>CC — 2026</b></div>
          </aside>
        </div>

        <footer className="desk-footer"><span><i /> CONNECTED TO THE WORKING DESK</span><span>FACTS FROM THE SHOP DATABASE <b>·</b> HUMAN DECISIONS STAY HUMAN</span></footer>
      </main>
    </div>
    </>
  )
}
