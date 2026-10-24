# Networking Intelligence (v3.8.0)

Reference guide for the eight network-layer tools introduced in v3.8.0.

Closes the correlation gap that let a customer power outage escape detection. The primitives answer the networking questions operators ask every day (interface performance, top talkers, flapping ports, collector health, UPS state); the composites combine them into site-outage detection and coverage auditing that generic AIOps correlation misses.

## Table of contents

- [Primitives](#primitives)
  - [get_interface_metrics](#get_interface_metrics)
  - [get_top_talkers](#get_top_talkers)
  - [detect_alert_burst](#detect_alert_burst)
  - [get_link_flaps](#get_link_flaps)
  - [get_collector_health](#get_collector_health)
  - [get_power_events](#get_power_events)
- [Composite workflows](#composite-workflows)
  - [detect_site_outage](#detect_site_outage)
  - [audit_network_monitoring_coverage](#audit_network_monitoring_coverage)
- [Scoring model (detect_site_outage)](#scoring-model-detect_site_outage)
- [DataSource pattern defaults](#datasource-pattern-defaults)
- [Prerequisites for full coverage](#prerequisites-for-full-coverage)

---

## Primitives

### get_interface_metrics

Per-interface time-series metrics. Answers "how is this port performing?"

**Parameters:**
- `device_id` (int, required) -- LogicMonitor device ID
- `interface` (str, required) -- interface name or substring, case-insensitive (`Gi0/1`, `eth0`, `ens192`)
- `metrics` (str, optional) -- comma-separated datapoint names. Default: `RxRate,TxRate,ErrorsIn,ErrorsOut,DiscardsIn,DiscardsOut,InterfaceStatus`
- `hours_back` (int, optional, default `1`) -- history window

**Behavior:** Fetches the device's DataSource list, picks the Interface-family DataSource (prefers `SNMP_Network_Interfaces` when present), matches the interface name against instances by case-insensitive substring on `name` or `displayName`, then calls the standard metric-data endpoint.

**Errors surfaced:**
- `INTERFACE_DATASOURCE_NOT_FOUND` -- no Interface-family DataSource applied (device lacks SNMP monitoring).
- `INTERFACE_NOT_FOUND` -- DataSource found but no instance matches; response includes up to 50 available instance names.

### get_top_talkers

Ranks NetFlow flows for an exporter by bandwidth. Answers "what is consuming my WAN?"

**Parameters:**
- `exporter_device_id` (int, required) -- NetFlow exporter device ID
- `hours_back` (int, optional, default `1`)
- `n` (int, optional, default `10`) -- number of top entries
- `group_by` (str, optional, default `src_ip`) -- one of `src_ip`, `dst_ip`, `application`, `protocol`, `src_dst_pair`
- `min_bytes` (int, optional, default `0`) -- drop aggregated entries below this byte threshold

**Behavior:** Pulls raw flows from `/netflow/flows` in the window, aggregates client-side on the requested dimension, sorts by total bytes, returns top-N with `total_bytes`, `total_packets`, `flow_count`, and `percentage_of_total`.

**Graceful degradation:** Returns `"note": "No flows exported in window -- check NetFlow exporter configuration"` when the exporter is not sending flows.

### detect_alert_burst

Sliding-window mass-event detector. Buckets alerts by DataSource, identifies windows where alert count and distinct device count exceed thresholds. Used for power outages, DDoS, switch cascade failures, firmware push regressions.

**Parameters:**
- `group_id` (int, optional) -- scope to a device group
- `device` (str, optional) -- scope to a device name substring
- `datasource_pattern` (str, optional) -- substring filter on `dataSourceName`, case-insensitive
- `window_seconds` (int, optional, default `60`)
- `min_alerts` (int, optional, default `10`)
- `min_devices` (int, optional, default `3`)
- `hours_back` (int, optional, default `1`)
- `severity` (str, optional) -- `critical`, `error`, `warning`, `info`

**Output:** Per-burst entries with `datasource`, `window_start`, `window_end`, `alert_count`, `device_count`, `alert_ids[:50]`, `top_devices[:10]`.

**Hard cap:** 5000 alerts per analysis window. Exceeding the cap returns a `warning` field; narrow the scope or window for complete results.

### get_link_flaps

Identifies interfaces with repeated up/down transitions. Answers "which ports are unstable?" Common causes: bad cable, duplex mismatch, bad SFP, PoE power cycling, WAN instability.

**Parameters:**
- `group_id` (int, optional)
- `device` (str, optional)
- `hours_back` (int, optional, default `24`)
- `min_transitions` (int, optional, default `4`)
- `interface_pattern` (str, optional) -- regex matching interface DataSource names; default covers common variants

**Output:** Top 50 flapping (device, interface) pairs with transition count, first/last transition epoch, and `still_active` flag.

### get_collector_health

Enriched collector status. Leading indicator for site-level events. Preferred over `get_collectors` when investigating potential outages.

**Parameters:**
- `collector_id` (int, optional) -- single collector; other scope args ignored if set
- `collector_group_id` (int, optional) -- restrict to a collector group
- `include_history` (bool, optional, default `false`) -- include recent CollectorDown alerts
- `history_days` (int, optional, default `7`)

**Enrichments over `get_collectors`:**
- `is_down` -- computed from status field and active CollectorDown alerts; `null` when the CollectorDown alert read fails, with `down_signal_unavailable: true`
- `downstream_device_count` -- from `/device/devices?filter=currentCollectorId:{id}` (more reliable than stale `numberOfHosts`)
- `active_collector_down_alerts` -- count of current open CollectorDown alerts for this collector hostname; `null` when that read fails
- `collector_down_history` -- recent history when requested

### get_power_events

UPS/PDU alert filter. Simplest tool in the set.

**Parameters:**
- `group_id` (int, optional)
- `device` (str, optional)
- `hours_back` (int, optional, default `2`)
- `severity` (str, optional)
- `patterns` (list[str], optional) -- override defaults

**Default patterns:** `UPS`, `PDU`, `APC`, `Liebert`, `Eaton`, `Battery`, `PowerSupply`, `Power_`. Client-side case-insensitive substring match against `dataSourceName` and `alertName`.

**Output:** Matched events plus `patterns_matched_counts` dictionary for quick attribution (e.g., `{"ups": 12, "battery": 4}`).

---

## Composite workflows

### detect_site_outage

The headline tool. Chains four signals into a single site-outage verdict with confidence score.

**Parameters:**
- `group_id` (int, required) -- device group ID representing the site
- `window_seconds` (int, optional, default `300`) -- burst window size
- `hours_back` (int, optional, default `1`) -- context window for power events
- `detail_level` (str, optional, default `summary`) -- `summary` or `full`

**Flow:**
1. Enumerate devices in the group, derive the distinct set of collectors serving them via `currentCollectorId`.
2. Query `get_collector_health` for each -- any `is_down=True` trips **Signal A**.
3. Query `detect_alert_burst` filtered to Interface-family DataSources -- trips **Signal B**.
4. Query `get_power_events` scoped to the group -- trips **Signal C**.
5. Count dead/unreachable devices in the group -- trips **Signal D** when count exceeds `max(3, device_count // 5)`.
6. Compute confidence score (see model below) and derive the verdict. A signal whose read fails is reported with `status: "unavailable"` and its `error`, and is left out of the score; the report then carries `confidence_level: "reduced"` and `unavailable_signals`.

**Verdict thresholds:**
- `>= 70` -- `site_outage_detected`
- `>= 40` -- `possible_site_outage`
- `<  40` -- `no_outage_signature`
- `indeterminate` -- one or more signals could not be read, and their weights could change the verdict

**Recommendations:** Actionable next-step hints based on which signals fired (collector verification, UPS review, correlation to common rack/switch).

### audit_network_monitoring_coverage

Portal coverage audit. Produces a prioritized gap list with specific onboarding actions.

**Parameters:**
- `group_id` (int, optional) -- scope the audit to a device group; omit for portal-wide

**What it counts:**
- Total devices and rough classification (power-like, network-like, server-like, unclassified) by `systemCategories` heuristic
- SNMP-credentialed devices (property `snmp.version` or `snmp.community` set)
- NetFlow exporters (property `netflow.enabled` or `NetflowExporter` DataSource)
- Power-monitored devices (UPS/PDU/Battery patterns)
- Collector count + operational count

**Gap categories returned (when applicable):**
- `power` (high) -- no UPS/PDU devices; recommends onboarding APC_UPS_Battery / Liebert_UPS / Eaton_UPS DataSources
- `snmp` (high) -- < 25% SNMP coverage with network gear present
- `netflow` (medium) -- no NetFlow exporters with network gear present
- `collectors` (critical) -- zero collectors, or (high) -- some collectors down
- `inventory` (low) -- > 50% of devices unclassified

Each gap includes a concrete `recommendation` field the operator can act on.

---

## Scoring model (detect_site_outage)

Additive weights, capped at 100:

| Signal | Weight | Trigger |
|--------|--------|---------|
| Collector down | +40 | `get_collector_health` reports `is_down=True` for any collector serving the group |
| Interface burst | +25 | `detect_alert_burst` with `datasource_pattern="interface"` returns any burst |
| Power events | +25 | `get_power_events` returns any matched events in the last hour |
| Device silence | +10 | Dead-device count in the group >= `max(3, group_size / 5)` |

The 70 threshold for `site_outage_detected` requires at least two of the three heavy signals (collector, burst, power). The 40 threshold for `possible_site_outage` catches single-signal cases like "only UPS events" or "only interface burst" where context is needed.

---

## DataSource pattern defaults

Defaults are substring-match patterns (case-insensitive) used to identify infrastructure types when LM does not expose a structured category. Override any of them via tool parameters when a customer's portal uses non-standard DataSource names.

| Tool | Parameter | Default |
|------|-----------|---------|
| `get_interface_metrics` | internal constant | `interface`, `interfaces`, `if-`, `port`, `ethernet`; prefers `SNMP_Network_Interfaces` |
| `detect_alert_burst` | `datasource_pattern` | none (caller provides) |
| `get_link_flaps` | `interface_pattern` | `interface\|interfaces\|if-\|port\|ethernet` (regex) |
| `get_power_events` | `patterns` | `UPS`, `PDU`, `APC`, `Liebert`, `Eaton`, `Battery`, `PowerSupply`, `Power_` |
| `audit_network_monitoring_coverage` | internal | same as `get_power_events` plus `switch`, `router`, `firewall`, `wlan` for network-gear classification |

---

## Prerequisites for full coverage

The tools degrade gracefully when prerequisites are missing, but detection fidelity depends on what the portal is actually monitoring:

- **For `detect_site_outage` to trigger the UPS signal:** UPS and PDU devices must be onboarded as LM resources (APC, Liebert, or Eaton DataSources applied). Without them, Signal C always reports zero and the verdict relies on the other three signals.
- **For `get_interface_metrics`:** the target device must have an Interface-family DataSource applied (typically `SNMP_Network_Interfaces`), which requires SNMP credentials on the device.
- **For `get_top_talkers`:** the exporter device must be forwarding NetFlow/sFlow/IPFIX records to LM collectors, and NetFlow ingestion must be enabled on the portal.
- **For `get_collector_health` downstream-count accuracy:** the `currentCollectorId` field must be populated on devices; falls back to the collector's stale `numberOfHosts` when the filter endpoint is unavailable.

Run `audit_network_monitoring_coverage` first when onboarding a new customer or investigating repeated missed detections -- it surfaces the prerequisite gaps before they matter operationally.
