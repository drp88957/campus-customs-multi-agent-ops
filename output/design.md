# Campus Customs agent desk — design notes

I designed the dashboard as a late-night campus shop operations room: dark ink surfaces, raspberry pink signals, and warm paper-like details. It should feel focused enough for real work, with a little personality left in it.

## Layout

- A narrow left rail anchors the shop name and backend connection state.
- The header shows the shop date, followed by three quick reads: ticket count, checking cash, and crew status.
- The main desk has a ticket queue, a selected-ticket work area, and a live crew column. The queue stays visible while a ticket is being reviewed.
- The selected ticket shows its request, requester, product details, and linked invoice or lease before the agent run control.
- The human approval cards sit directly under the ticket they affect, so a payment or purchase cannot be mistaken for an agent action.
- The right column shows the five roles, their latest update and MCP calls, then a chronological field-note feed. It collapses below the work area on smaller screens.

## Agents and live updates

The dashboard polls the events route while it is open and while an agent run is in progress. Each role has a distinct accent: Boss in pink, Inventory in mint, Accounting in pale blue, Facilities in warm amber, and Customer Service in violet. Their status changes from standby to working to complete, and each card shows the agent’s latest summary and tool calls. The activity feed keeps the longer sequence visible without hiding who did what.

## Resolved tickets and cash

A completed agent run changes the ticket to **Resolved** on the board. If that run still asks for a human decision, its approval card remains active under the resolved ticket so resolution does not look like payment or purchase approval. The checking tile always refreshes from the backend; after an approved payment or purchase, the new balance and total cash outflow appear there.

## Small details

The shop note, pin-like brand mark, tiny star, soft card edges, and “field notes” label give the page some warmth without getting between the person and the work. Clear status colors distinguish open work, completed analysis, active agent turns, and human-only decisions. The layout becomes a single-column desk on narrow screens, and no external images or font downloads are needed.
