---
name: lm-collector-debug
description: "Run collector debug safely: confirm one question about one collector or device with allowlisted, time-boxed debug commands. Automated mode for agents after assess_collector_health; assisted mode for engineers, starting from a symptom."
argument-hint: "<collector id | device id> [symptom]"
allowed-tools:
  - mcp__logicmonitor__assess_collector_health
  - mcp__logicmonitor__collector_debug
  - mcp__logicmonitor__get_collector
  - mcp__logicmonitor__get_device
---

# Collector Debug

You run collector debug commands through `collector_debug`, one command per call. The tool
composes every command line from a fixed safe list, refuses anything that changes the
collector, runs code on its host, writes to a device or carries a credential, and stops at
`budget_seconds`. Your job is to choose the smallest command that settles one thing, read what
the collector said, and decide whether the next command is worth running.

**Use debug to confirm, never to discover.** `assess_collector_health` (tier 1, read-only, about
a second) says which collector to look at. Debug answers one narrow question about it.

## Rules

1. Never run debug on a collector whose state is `down` or `silent_reported_up`. It will not
   fetch the command; the call only spends time.
2. Every command is recorded in the portal's Audit Log under your identity, exactly as sent.
3. Read the reply, not the checkpoint status. A health check can show every checkpoint OK while
   a method has a double-digit share of tasks returning nothing.
4. An error from a device is an answer. "Access denied" proves the path works and the
   credential does not.
5. A `note` saying the collector printed its usage means the command line was wrong for this
   collector build, not that the device failed. Report it as such.
6. Status words are the tool's, not a diagnosis: `refused` is the Debug permission,
   `disabled` is `debug.disable` on the collector, `unsupported` is the collector build,
   `no_reply` is the time budget.
7. Stop after the first three rungs of the ladder: is the channel alive, which methods are
   losing work, can the collector reach the device. Dwell, timeouts against pool contracts and
   attribution need a person at a console.

## Automated mode (Edwin and other agents)

Run after `assess_collector_health`, for the lead collector only, inside a total of about 15 s.

1. Only if the lead collector's state is `healthy`, `up_losing_work` or
   `up_devices_unreachable`.
2. `collector_debug(command="uptime", collector_id=…)`. No answer is the finding: stop.
3. `collector_debug(command="health_check", collector_id=…)`. Report
   `parsed.methods_by_all_nan_rate` (method, rate, attempts), `parsed.not_ok`, the top of
   `parsed.nan_by_module`, and `parsed.last_run_started`.
4. If the insight names devices: `collector_debug(command="perf", collector_id=…,
   args={"h": "<device name>"})` to see whether that device is a NaN source.
5. If the state is `up_devices_unreachable`: `collector_debug(command="ping", device_id=…)` for
   up to three of the dead devices, issued concurrently. Replies separate a live path fault
   from stale state.

Measured on a live Windows collector: `uptime` about 2 s, `health_check` about 2 s, `perf`
2 to 4 s, `ping` about 7 s (it sends 10 packets). Steps 2 to 4 in sequence fit in about 8 s;
the pings fit only when they run in parallel, never one after another.
6. Report each command, its status and what it returned. Name which tier ran. Draw no
   conclusion past these rungs.

## Assisted mode (engineers)

Start from the symptom and run the chain in order, stopping when a step settles it.

| Symptom | Chain (`command` and `args`) | Step that usually settles it |
|---|---|---|
| Too many dead tasks | `perf` → `perf {dsFilterColumn: timeout}` → `perf {dsFilterColumn: avg_exec}` → `tlist {c: <method>}` → `perf {type: queue}` | Empty at step 1: collection is fine, look at delivery |
| Collection late, queues building | `perf {type: queue}` → `perf {type: cpu}` → `getconfig {key: collector.wmi.threadpool}` → `getconfig {key: collector.ping.threadpool}` | A pool of 5 on a large collector (a known reversion; XXL should be 80) |
| Script and API modules stopped | `logsurf {files: [wrapper.log]}` → `perf` → `uptime` | Script cache invalid or corrupt in the log |
| Properties missing | `splist` → `aplist` → `adlist` | `splist`: the log never names the blocked property source |
| Collector restarted or unstable | `uptime` → `logsurf {files: [wrapper.log, sbproxy.log, watchdog.log]}` → `avslist` → `tasklist` | Anti-virus on the collector host |
| One device stopped reporting | `ping {device}` → `tlist {h: <device>}` → `splist {hostname: <device>}` → `aplist {h: <device>}` | Scoped to that device |
| Device protocol check | `snmpdiagnose` (registered SNMP credentials) · `wmi` / `winrm` (stored credentials or the collector's account) · `sslcerts {port}` · `http {url with scheme}` | The first step that fails is the finding |
| Delivery to the platform | `checkserverconnectivity {host: <portal host>}` → `reportercache` | "PING: Fail, HTTP: OK" means ICMP is blocked and delivery is fine |

Collection is expected to finish inside 200 ms; an `avg_exec` in seconds is a lead on its own.

## Never

- Free-text debug commands, `!groovy`, `!posh`, `!restart`, `!shealthcheck func=trigger`, or
  anything that writes to the collector host or a device. The tool refuses them; do not look
  for another way.
- Credentials on the command line. If a device has no stored credentials, say so and stop.
- Unfiltered `tlist`: it runs to hundreds of KB.
