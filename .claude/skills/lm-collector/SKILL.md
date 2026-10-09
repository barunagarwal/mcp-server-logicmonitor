---
name: lm-collector
description: "Is the collector the cause? Assess the collector(s) behind a correlated group of devices: down, silent while reported up, up with its devices unreachable, losing work, healthy or unknown."
argument-hint: "<device ids from the insight | collector ids | nothing for the fleet>"
allowed-tools:
  - mcp__logicmonitor__assess_collector_health
  - mcp__logicmonitor__get_collector
  - mcp__logicmonitor__get_devices
  - mcp__logicmonitor__get_alerts
  - mcp__logicmonitor__collector_debug
---

# Collector Health in an Investigation

You are checking whether a collector explains a group of correlated alerts before anyone
reasons about the devices one by one. One collector problem presents as hundreds of device
problems; answer the collector question first.

## Argument Parsing

- **Device IDs** (from the insight or alert group) — the normal case. Pass them as `device_ids`.
- **Collector IDs** — pass as `collector_ids`.
- **Nothing** — assess the fleet. Healthy collectors are counted, not listed.

## Workflow

### Step 1: Assess

Call `assess_collector_health` with the scope above. Leave `use_debug` off: tier 1 is fast
(about six API calls, run concurrently, whatever the fleet size) and is enough to decide.

### Step 2: Read the lead

When `device_ids` were given, `lead` names the collector carrying most of the insight's
devices and its state. Concentration decides how much the state explains:

| Concentration | Meaning |
|---|---|
| 0.5 or more, and state not healthy | The collector very likely explains the insight. Lead the RCA with it |
| Low, state not healthy | A real collector problem, but background to this insight |
| Any, state healthy | The collector is not the cause. Investigate the devices |

### Step 3: Act on the state

| State | What it means | Next step | Who |
|---|---|---|---|
| `down` | LM holds the collector down, or its own resource is dead. Devices behind it read dead-collector | Check the collector host and its service; check failover | Collector or host owner |
| `silent_reported_up` | The watchdog is silent while LM reports the collector up. Devices behind it read stale, not down | Treat every no-data alert behind it as one finding; restart the agent | Collector or host owner |
| `up_devices_unreachable` | The collector is live and most of its devices are dead | Look at the network path between the collector and the devices (firewall, VPN, routing, the site link) | Network team |
| `up_losing_work` | LM's thresholds on the collector's self-monitoring are breached | Read the evidence lines: queue, unavailable task rate, heap | Collector owner |
| `unknown` | A required signal was missing | Say so. Never report it as healthy | — |
| `healthy` | No collector-side cause | Move on to the devices | — |

### Step 4: Optional tier 2

Only when the state is `healthy` or `up_losing_work` and you need per-method detail, call again
with `use_debug: true` for that one collector, or follow the `lm-collector-debug` skill, which
runs `collector_debug` one command at a time. It reads the collector's stored health check
(`!shealthcheck func=detail`), needs debug rights, and is slower: every read shares
`debug_budget_seconds` (default 15). A read that does not answer in time returns `no_reply`;
the tier-1 state stands. Tier 2 never changes a state. Down and silent collectors are not asked,
because they will not pick the command up.

## Reporting

- Name the collector, its state, its concentration and the evidence lines, as given.
- State `unknowns` and `assumptions` when they bear on the answer. In particular, a collector
  listed under `collectors_not_monitored_as_resource` has no host status or self-monitoring
  of its own, so `up_losing_work` cannot be detected on it.
- Collector-down alerts are not in the alert list. Do not search alerts for them; the tool
  reads the collector's own resource status instead.
