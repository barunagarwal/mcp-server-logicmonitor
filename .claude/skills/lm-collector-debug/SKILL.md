---
name: lm-collector-debug
description: "Run collector debug safely: confirm one question about one collector or device with allowlisted, time-boxed debug commands. Automated mode for agents once a collector is named; assisted mode for engineers, starting from a symptom."
argument-hint: "<collector id | device id> [symptom]"
allowed-tools:
  - mcp__logicmonitor__collector_debug
  - mcp__logicmonitor__get_collector
  - mcp__logicmonitor__get_collector_health
  - mcp__logicmonitor__get_device
---

# Collector Debug

You run collector debug commands through `collector_debug`, one command per call. The tool
composes every command line from a fixed list, takes only each command's own arguments,
refuses anything that changes the collector, runs code on its host or carries a credential,
and stops at `budget_seconds`. Your job is to choose the smallest command
that settles one thing, read what the collector said, and decide whether the next command is
worth running.

**Use debug to confirm, never to discover.** Something else names the collector first: an
alert, a correlation, or `get_collector_health`. Debug answers one narrow question about it.

`collector_debug` is write-gated. Each listed command is meant to read, but the call runs on the
collector, so the server needs `LM_ENABLE_WRITE_OPERATIONS=true` and the caller needs the
collector Debug permission. Without them the call returns `WRITE_DISABLED` or `refused`; say so
and stop.

## Rules

1. Never run debug on a collector that is down. It will not fetch the command; the call only
   spends time.
2. Every command is recorded in the portal's Audit Log under the identity of this server's
   API credentials, exactly as sent.
3. Device probes take `device_id`, never a host. The tool points them at the device record's
   host, and an `http` URL must name that same host.
4. Read the reply, not the checkpoint status. A health check can show every checkpoint OK while
   a method has a double-digit share of tasks returning nothing.
5. An error from a device is an answer. "Access denied" proves the path works and the
   credential does not.
6. A `note` saying the collector printed its usage means the command line was wrong for this
   collector build, not that the device failed. Report it as such.
7. Status words are the tool's, not a diagnosis: `refused` is the Debug permission,
   `disabled` is `debug.disable` on the collector, `unsupported` is the collector build,
   `rate_limited` is the portal's or this server's call budget, and `error` is anything else,
   with the detail saying what. These five come back as errors, with the JSON body on a
   `Details:` line. `no_reply` is a result, not an error: the time budget ran out, and the
   collector may still run the command. A request the tool refuses before sending is an error
   whose message says why; when an argument was wrong, its suggestion names the arguments the
   command takes. Fix the request, do not retry it.
8. Stop after the first three rungs of the ladder: is the channel alive, which methods are
   losing work, can the collector reach the device. Dwell, timeouts against pool contracts and
   attribution need a person at a console.

## Automated mode (agents)

Run for the one collector already named, inside a total of about 15 s.

1. `collector_debug(command="uptime", collector_id=…)`. No answer is the finding: stop.
2. `collector_debug(command="health_check", collector_id=…)`. Report
   `parsed.methods_by_all_nan_rate` (method, rate, attempts), `parsed.not_ok`, the top of
   `parsed.nan_by_module`, and `parsed.last_run_started`.
3. If the question names devices: `collector_debug(command="perf", collector_id=…,
   args={"h": "<device name>"})` to see whether that device is a NaN source.
4. If devices on a live collector are dead: `collector_debug(command="ping", device_id=…)` for
   up to three of them, issued concurrently. Replies separate a live path fault from stale
   state.
5. Report each command, its status and what it returned. Draw no conclusion past these rungs.

Typical timings on a live collector: `uptime` about 2 s, `health_check` about 2 s, `perf` 2 to
4 s, `ping` about 7 s (it sends 10 packets). Steps 1 to 3 in sequence fit in about 8 s; the
pings fit only when they run in parallel, never one after another.

## Assisted mode (engineers)

Start from the symptom and run the chain in order, stopping when a step settles it.

| Symptom | Chain (`command` and `args`) | Step that usually settles it |
|---|---|---|
| Too many dead tasks | `perf` → `perf {dsFilterColumn: timeout}` → `perf {dsFilterColumn: avg_exec}` → `tlist {c: <method>}` → `perf {type: queue}` | Empty at step 1: collection is fine, look at delivery |
| Collection late, queues building | `perf {type: queue}` → `perf {type: cpu}` → `getconfig {key: collector.wmi.threadpool}` → `getconfig {key: collector.ping.threadpool}` | A pool of 5 on a large collector (a known reversion; XXL should be 80) |
| Script and API modules stopped | `logsurf {files: [wrapper.log]}` → `perf` → `uptime` | Script cache invalid or corrupt in the log |
| Properties missing | `splist` → `aplist` → `adlist` | `splist`: the log never names the blocked property source |
| Collector restarted or unstable | `uptime` → `logsurf {files: [wrapper.log, sbproxy.log, watchdog.log]}` → `avslist` → `tasklist` | Anti-virus on the collector host |
| One device stopped reporting | `ping` (device_id) → `tlist {h: <device>}` → `splist {hostname: <device>}` → `aplist {h: <device>}` | Scoped to that device |
| Device protocol check (device_id) | `snmpdiagnose` (registered SNMP credentials) · `wmi` / `winrm` (stored credentials or the collector's account) · `sslcerts {port}` · `http {url on the device's own host}` | The first step that fails is the finding |
| Delivery to the platform | `checkserverconnectivity` → `reportercache` | "PING: Fail, HTTP: OK" means ICMP is blocked and delivery is fine |

Collection is expected to finish inside 200 ms; an `avg_exec` in seconds is a lead on its own.

## Never

- Free-text debug commands, `!groovy`, `!posh`, `!restart`, `!shealthcheck func=trigger`, or
  anything that writes to the collector host. The tool refuses them; do not look for another
  way.
- An `http` URL that acts on the device (a reboot, reset or apply URL). The tool sends any GET
  to the device's own host, so this one is yours to refuse.
- A `host` argument, or a URL for another host. Probes point at the device record only.
- Credentials on the command line or in a URL. If a device has no stored credentials, say so
  and stop.
- Unfiltered `tlist` (or `h: *`): it runs to hundreds of KB. The tool refuses it.
