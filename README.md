# esdoctor: offline analyzer for Elasticsearch diagnostic bundles

English · [한국어](README.ko.md)

**Version 0.14.0** · Findings based on the Elasticsearch 9.4 official docs · Python 3.8+ · No external dependencies

esdoctor analyzes bundles created by Elastic [support-diagnostics](https://github.com/elastic/support-diagnostics) **inside an air-gapped network** and produces a report of current issues, potential issues and configuration risks.

It is built for environments where security policy does not allow diagnostic files to leave the site.
It makes no network calls and uses only the Python standard library.

> **Validation scope: verified on real bundles in api mode (ECH 9.4.4 and 9.5.3) and in local mode (self-managed 8.19.21, single node, including server logs and `syscalls/`). Remote mode and multi-node local mode bundles have not been verified on real bundles yet.**
>
> **This is not an official Elastic tool and does not replace analysis by Elastic Support.** Findings rest on facts recorded in the bundle and on the published official docs. Every finding states whether its basis is an official threshold, a fact reported by Elasticsearch, or a threshold set by the tool.

---

## Table of contents

- [Key features](#key-features)
- [Quick start](#quick-start)
- [Requirements and runtime environment](#requirements-and-runtime-environment)
- [Collecting a diagnostic bundle](#collecting-a-diagnostic-bundle)
- [Baseline version](#baseline-version)
- [Findings model](#findings-model)
- [Analysis principles](#analysis-principles)
- [Report layout](#report-layout)
- [Elastic Support summary](#elastic-support-summary)
- [Documentation](#documentation)
- [Adjusting thresholds](#adjusting-thresholds)
- [Adding rules](#adding-rules)
- [Verification](#verification)
- [Limitations](#limitations)
- [Structure](#structure)

---

## Key features

- **Built for air-gapped networks**: no external communication, CDN, fonts or package installs. Copy the repository in and run it
- **No dependencies**: Python 3.8 or later, standard library only
- **133 rules**: 122 for a single bundle and 11 for comparing two bundles
- **Bottleneck summary**: five questions at the top of the report (is ingest keeping up, is search slow, is storage the limit, do restarts skew the numbers, capacity or concentration), each answered from symptoms first and then from the findings that explain them
- **Storage cost**: rolled-over data kept on hot, replicas nobody searches, uneven disk use across tiers, and how many days of ingest the landing tier can still hold
- **Action priority by root cause**: findings that come from the same cause (for example yellow status, unassigned shards, allocation explain and replicas above the node count) are grouped under one representative finding, and the rest are shown as related findings
- **Evidence basis on every finding**: Official / Reported fact / Tool threshold / Computed
- **Settings change analysis**: cluster, node and index settings that differ from the default are reported with the original default, dynamic or static, what the setting does, and the impact of raising or lowering it (knowledge base of 94 settings)
- **Oversharding analysis**: shards that can be removed per index, excess data stream rollovers, and shard size distribution
- **Tier awareness**: hot/warm/cold/frozen are separated, and only nodes with the same role are compared
- **Comparison mode**: compares against an earlier bundle to decide whether a cumulative counter is still increasing, with a before/now table per node. With three or more bundles it also reports throughput per interval (peak and off-peak) for sizing
- **Large bundle handling**: files of several hundred MB (cluster_state, mapping) are parsed only where needed or summarized per index, which keeps memory bounded
- **Stated bundle coverage**: 62 of the 104 files in a diagnostic bundle are used for findings. For the other 42, [COVERAGE.md](COVERAGE.md) ([한국어](COVERAGE.ko.md)) gives the reason: duplicate, empty when the feature is unused, or not a basis for findings
- **Not collected vs tool error**: a finding is skipped when its input file is missing, and the report is still generated when a single rule fails
- **Transparent specification**: [RULES.md](RULES.md) ([한국어](RULES.ko.md)) lists every condition and threshold, extracted from the code
- **Single-file HTML report**: inline CSS and JS only, so it opens offline in any browser

---

## Quick start

```bash
# Clone the repository and run it. No pip install needed.
git clone https://github.com/Munsik/airgapped-es-diag-analyzer.git
cd airgapped-es-diag-analyzer

# Check the runtime environment
python3 analyze.py --check-env

# Console summary
python3 analyze.py diagnostic-20260814.zip

# HTML, Markdown and JSON in one run
python3 analyze.py diagnostic-20260814.zip --out-dir ./report

# Compare with an earlier bundle
python3 analyze.py diag-0814.zip --baseline diag-0807.zip --html report.html

# Three or more bundles: throughput per interval (peak and off-peak)
python3 analyze.py diag-0814-1800.zip --baseline diag-0814-0900.zip --baseline diag-0814-0300.zip
```

On an air-gapped network, download the repository as a zip, carry it in, unzip it and run it the same way.

### Options

| Option | Description |
| --- | --- |
| `--html FILE` / `--md FILE` / `--json FILE` | Output path for each format |
| `--out-dir DIR` | Write `es-diag-report.{html,md,json}` together |
| `--baseline FILE` | Compare with an earlier bundle and report increases and growth rates. Can be repeated: the bundles are ordered by collection time, the latest one is the comparison base, and three or more bundles in total add throughput per interval (DIF-014) |
| `--support-summary FILE` | Also write a summary (Markdown) for a case with Elastic Support. Written only when specified |
| `--mask none\|basic\|strict` | Masking level for the summary (default `basic`). Use with `--support-summary` |
| `--mask-map FILE` | Path of the alias-to-original-name mapping JSON (default: summary file name + `.mask-map.json`). Use with `--support-summary` |
| `--lang both\|ko\|en\|auto` | Output language (default `both`). `both` writes Korean and English and adds `.ko` / `.en` to the file name (`report.html` becomes `report.ko.html` and `report.en.html`). `ko` and `en` write one language and use the name exactly as given. `auto` follows the locale. The environment variable `ESDOCTOR_LANG` also sets it |
| `--no-ok` | Hide OK findings |
| `--only MODULE` | Run only the given rule modules (`cluster` `settings` `nodes` `shards` `sharding` `guidance` `hotspot` `cost` `ops` `deep` `runtime` `syscalls`). Can be repeated |
| `--thresholds FILE` | JSON file that overrides thresholds (unknown keys are ignored with a warning) |
| `--print-thresholds` | Print the default thresholds |
| `--fail-on critical\|warning` | Exit with code 1 if a finding of that severity exists |
| `--quiet` / `--debug` | Suppress console output / print tool error details |
| `--check-env` | Check the runtime environment |
| `--version` | Tool version |

Exit codes: `0` success, `1` the `--fail-on` condition was met, `2` input error (path not found, not recognized as a diagnostic bundle) or summary masking failure (see below).

---

## Requirements and runtime environment

**There are no external package dependencies.** `requirements.txt` exists only to state this. All you need is a Python interpreter.

| Item | Details |
| --- | --- |
| Python | 3.8 or later. Full validation passed on 3.8.20 and 3.12.3, with identical findings on both |
| Python 3.6-3.7 | Should work by static analysis (one 3.7-only feature has a fallback), **not verified by running** |
| Standard modules | argparse, collections, datetime, fnmatch, html, io, json, math, os, re, sys, tempfile, traceback, zipfile, zlib |
| OS | Linux / macOS / Windows |
| Input | Diagnostic bundle zip or an unzipped directory |
| Scale and memory | Real bundle (2,494 indices, about 500MB unzipped): 7 seconds, up to about 0.9GB. Synthetic bundle (20,000 indices, 60,000 shards): about 30 seconds |

`--check-env` checks the Python version, the standard modules, zlib (needed to unzip), console encoding, and write permission on the output path.
If Python is a minimal build without zlib, pass the unzipped bundle directory instead.
If the console cannot display Korean, the analysis still runs. File output is always UTF-8.

### How to bring it in

| Form | Method |
| --- | --- |
| Source clone (default) | `git clone`, then `python3 analyze.py ...` |
| Source zip | Download the zip from GitHub and unzip it, then `python3 analyze.py ...` |
| Single file (optional) | Build `dist/esdoctor.pyz` with `python3 tools/build_pyz.py`, then `python3 esdoctor.pyz ...` |
| Standalone executable (optional) | Build `dist/esdoctor` with `bash tools/build_binary.sh`, then `./esdoctor ...` (no Python needed) |

### Choosing by environment

| Target environment | Method |
| --- | --- |
| Python 3.8 or later is installed (RHEL 9 ships 3.9, Ubuntu 20.04 and later, and so on) | Copy the repository in and run `python3 analyze.py` |
| RHEL 8 without python3 | Can run with the bundled `/usr/libexec/platform-python` (3.6), but this is not verified. Install python39 or later if possible |
| RHEL 7 | The default Python is 2.7 and cannot be used. Install python3 or use the standalone executable |
| Windows PC used for analysis inside the air-gapped network | Use an installed Python. If installation is blocked, the Windows embeddable package from python.org should work (not verified) |
| Python cannot be installed at all | Build the standalone executable |

In every case the diagnostic bundle stays inside the air-gapped network. You can also analyze on a PC inside the network instead of on the server.

### Building the standalone executable (optional)

```bash
bash tools/build_binary.sh     # dist/esdoctor (PyInstaller, uses a build-only virtual environment)
```

- PyInstaller is needed only on the build machine. The result runs without Python.
- A Linux binary **runs only on the glibc version of the build OS or later**. Build on an OS that is the same as or older than the target server.
  For this reason the repository does not include a built binary.
- Build the Windows executable on Windows.

---

## Collecting a diagnostic bundle

| Collection mode | Contents | Analysis scope |
| --- | --- | --- |
| `api` | REST API responses | Findings based on state, configuration and statistics |
| `local` / `remote` | API + server logs (elasticsearch.log, gc.log) + `syscalls/` | Everything above, plus log pattern analysis and OS settings (SYS-001 to SYS-004) |

Logs show when an event happened, so collect in `local` or `remote` mode when you can.

> **Note:** `syscalls/` in local mode holds values from the one host where the diagnostics ran.
> When you analyze a local or remote mode bundle, also check "Input not collected" and "Tool errors" at the bottom of the report.
> For how to collect, see the [official docs](https://www.elastic.co/docs/troubleshoot/elasticsearch/diagnostic).

**Collect twice at an interval and compare with `--baseline`.** Rejections, GC and circuit breaker counts are cumulative since node start, so one bundle cannot tell you whether they are still occurring.

---

## Baseline version

| Item | Value |
| --- | --- |
| Elasticsearch version used as the baseline | **9.4** |
| Date checked against the official docs | 2026-10 |
| Verified on real bundles | 9.4.4 (ECH, 3 nodes, single tier) and 9.5.3 (ECH, 14 nodes, hot/warm/cold/frozen), both in api mode |
| Verified collection modes | **api** (the two bundles above) and **local** (self-managed ES 8.19.21 single node on Rocky Linux 9, collected with diagnostics 9.4.1). **Remote and multi-node local are not verified** |
| Large bundle check | 9.5.3 bundle (2,494 indices, cluster\_state 190MB, mapping 178MB): analysis in 7 seconds, peak memory about 0.9GB |
| Minimum supported version | 8.0 (earlier versions work only for the APIs that exist in that version) |

The baseline is fixed in `esdoctor/__init__.py` and printed at the top of every report.
If the analyzed version is newer than the baseline, `VER-001` (Info) is shown.

### Findings that depend on the version

| Version | Finding | Detail |
| --- | --- | --- |
| 8.0 | SET-\* | `action.destructive_requires_name` defaults to true |
| 8.3 | SHD-001 | The 20 shards per 1GB of heap guideline applies only below 8.3 (officially retired in 8.3) |
| 8.5 | DISK-\* | Disk watermarks use max\_headroom (low 200GB / high 150GB / flood 100GB) |
| 8.8 | IDX-015 | `index.translog.flush_threshold_size` defaults to 10GB (512MB before) |
| 8.14 | VEC-002 | dense\_vector defaults to int8\_hnsw when index\_options is not set |
| 9.1 | VEC-002 | float vectors with 384 or more dimensions default to bbq\_hnsw |
| 9.0 | IDX-013 | logsdb applies automatically to new `logs-*-*` data streams. Data streams that existed before an upgrade from 8.x stay as they are |
| 9.2 | VEC-003 | `index.mapping.exclude_source_vectors` applies by default |

---

## Findings model

### Severity

| Level | Meaning |
| --- | --- |
| Critical | An outage is happening now, or will be soon if left alone |
| Warning | Performance, stability or recoverability is already degraded |
| Info | Context, or room to improve |
| OK | Checked and no problem found (kept to show what was checked) |

### Evidence basis

| Basis | Meaning | Number of finding IDs |
| --- | --- | --- |
| Official | The threshold is stated in the official Elastic docs (for example heap ≤ 50% of RAM, shard size 10-50GB and 200 million documents, watermarks, setting defaults) | 68 |
| Reported fact | State, error or setting reported by Elasticsearch, passed on as is, no threshold (for example red status, ILM error) | 57 |
| Tool threshold | No official number exists, so the tool sets the threshold (for example heap usage 75%, average search latency 200ms) | 59 |
| Computed | Increase, growth rate or linear extrapolation between two bundles | DIF-001 to DIF-013 |

When you pass results to the customer, present "Official" and "Reported fact" as evidence and "Tool threshold" as a recommendation.

### Overall result

Decided only by the number of Critical and Warning findings. Any Critical gives **Action needed**. 5 or more Warnings give **Review recommended**. 1-4 Warnings give **Good (room to improve)**. Otherwise the result is **Good**.
No weighted score is used. It would be an arbitrary formula with no official basis, and large clusters would easily score 0, which carries no information.

### Items that could not be checked

These are shown separately at the bottom of the report, in two kinds. Neither means "no problem". Both mean **"could not be checked"**.

| Kind | Cause | Action |
| --- | --- | --- |
| Input not collected | A file the rule needs is not in the bundle (collection mode, account privileges, tool version) | Check the collection conditions and collect again |
| Tool error | This tool could not process the data format of the bundle | Send `rule_errors` from the JSON output to the tool maintainer |

If one rule fails, the other findings and the report are still produced.

---

## Analysis principles

### Tier awareness

Data nodes are grouped into tiers (hot / content / warm / cold / frozen) by their role combination. **Specs, shard counts, resource usage and workload are compared only within the same tier.** Differences between tiers are intended design and are not reported as findings. NODE-003 holds only a per-tier spec table.
If every node in a tier is near its CPU limit, the cause is lack of capacity, not skew, and HOT-005 reports it.
Dedicated frozen nodes have most of their disk taken up in advance by the shared cache, so the low and high watermarks are not applied. Only `flood_stage.frozen` (95%, max_headroom 20GB) is checked.

### Index classification

- `.ds-<data stream>-*` backing indices are **user data**. They count as system indices only when the data stream name itself starts with `.` (such as `.ds-.kibana-*`).
- Searchable snapshots are handled differently depending on the mount type.
  - **Partial mount (frozen, `partial-*`)**: the store size is the local cache size, not the original size. Excluded from size-based findings (small, large, oversharding).
  - **Fully mounted (cold, `restored-*`)**: whole shards are copied locally, so the store size is the real size. Included in size-based findings.
  - For both, the snapshot is the source, so shrink and force-merge are not possible. They are excluded from action-type findings (segments, deleted documents, per-index oversharding), and the guidance points to the cause (rollover, primary count setting).
- Write blocks on rolled-over indices and on searchable snapshots are normal ILM behavior and are not reported.
  **Only a block on the current write target (data stream write index, alias write index) and a flood stage block** are Critical.

### Settings change analysis

Settings that differ from the default are reported with the **original default / current value / dynamic or static / meaning / impact of change (↑ raised, ↓ lowered)**.

| Finding | Scope |
| --- | --- |
| SET-001 | Cluster settings set in persistent / transient that differ from the default |
| SET-002 | Settings explicitly set to the same value as the default (they do not follow a new default after an upgrade) |
| SET-003 | elasticsearch.yml values that are ignored because an API setting overrides them |
| SET-004 | Node settings (yml, including static) that differ from the default |
| SET-005 | Settings that differ between data nodes of the same tier |
| SET-006 | User index settings that differ from the default |

The official precedence applies (transient > persistent > elasticsearch.yml > default).
`cluster_settings_defaults` in the bundle already reflects yml values, and a key set through the API does not report its default.
So the **original default comes from a knowledge base built from the official docs (`esdoctor/settings_kb.py`)**. Settings not registered there are reported with the value only and marked "no description registered".
Settings judged by a dedicated rule (for example ARS, reported as CLU-014) are marked `[finding: rule ID]` in the table and left out of the SET severity, so nothing is reported twice.

### Oversharding analysis

| Finding | Criterion |
| --- | --- |
| OVS-001 | Index with 2 or more primaries whose average shard size is below the official lower bound of 10GB. Removable shards = (current - ceil(size/50GB)) × (1 + replicas) |
| OVS-002 | Median shard size of data stream backing indices is below 1GB (excess rollover) |
| OVS-003 | Distribution of user primary shard sizes (<1GB / 1-10GB / 10-50GB / 50GB+). If 80% or more are below 10GB, oversharding is general |

The current write index of a data stream is still filling, so it is excluded from size-based findings.

### Document limit and logsdb

Rollover always runs once a shard reaches 200M documents, whatever the other conditions are. Setting `max_primary_shard_docs` above 200M has no effect (official). ILM checks its conditions every `indices.lifecycle.poll_interval` (10m by default), so a rolled-over index usually ends a little above 200M.

| Finding | Criterion |
| --- | --- |
| SHD-008 | A shard of a write index, or of an index without rollover, has 200M documents or more (official). Searchable snapshot mounts take no writes and are rated like SHD-013 |
| SHD-013 | A shard of a rolled-over index is more than 5% above 200M: rollover ran late (tool threshold) |
| SHD-014 | The largest primary shard of a logsdb index is 30GB or more and under 50GB (tool threshold, Info) |
| SHD-015 | A logsdb data stream with 5 or more indices rolled over under 10GB and under 200M documents (official lower bound, Info, one row per data stream) |
| IDX-013 | On 9.0 or later, a `logs-*-*` data stream whose write index is not in logsdb mode (Info) |
| ILM-007 | `max_primary_shard_docs` above 200M (no effect, official) |
| ILM-008 | Free disk on the tier that runs a one-segment force merge is under 3 times the largest primary shard (official) |
| ILM-009 | An index has been in force merge for 24 hours or more (tool threshold, Info) |

logsdb stores data efficiently, so it usually reaches 200M documents before 50GB. The official 10-50GB range stays as it is, and logsdb alone gets 30GB as a tool upper bound. The reasons are the merge cost of index sorting, the free space for a one-segment force merge (up to 3 times), and recovery time, each backed by the official docs. 30GB itself is not an official number; it follows an Elastic internal discussion. The finding lists, per index, the largest shard, its document count, bytes per document and the estimated rollover condition. Partially mounted (frozen) indices are skipped because their size is the cache size.

### Comparison mode

| Finding | Detail |
| --- | --- |
| DIF-001 | Cluster status got worse or better |
| DIF-002 to DIF-003 | Node restart (uptime went backward), nodes that left or joined |
| DIF-004 to DIF-005 | Rejection increase and hourly rate (with no increase, classified as past history) |
| DIF-006 to DIF-007 | Share of old GC in the interval, increase in circuit breaker trips |
| DIF-008 | Disk growth rate and the expected date of reaching the high watermark, judged per tier (linear extrapolation, frozen excluded) |
| DIF-009 to DIF-011 | Throughput and its distribution in the interval, index growth, index creation and deletion |
| DIF-012 | Change in findings (new / worse / resolved) |
| DIF-013 | Warns when the two bundles come from different clusters (cluster_uuid differs, for example). Treat the comparison findings as reference only |

---

## Report layout

The HTML report (single file) has this order. Markdown and console output contain the same content.

1. Header: cluster, version, deployment type, collection time and mode, tool version and baseline, overall result, severity counts
2. **Bottleneck summary**: five questions with a verdict, the symptoms and findings it rests on, and where to look next (see below)
3. Action priority: list of Critical and Warning findings, each linking to its finding
4. **Results by area**: status and counts for Availability / Capacity / Data structure / Performance / Data protection and operations / Security / Configuration
5. Changes since the earlier bundle (when `--baseline` is given), with a before/now table per node
6. Node status at a glance: bars for heap, CPU, load, disk and shard count
7. Top indices by storage
8. Filter: severity × category, and a text box that narrows findings and their evidence rows to an index, node or tier name
9. Findings, in health check area order: Observed / Impact / Recommendation / Evidence table / Source file / Reference docs, with the evidence basis
10. Explanation of evidence basis, and items that could not be checked (input not collected, tool error)

### Bottleneck summary

| Question | Symptoms checked first | Causes checked in this order once a symptom exists |
| --- | --- | --- |
| Is ingest keeping up? | write rejections, write queue, indexing pressure rejections, indexing throttled now | storage (IDX-005, PERF-012, IDX-014, DISK-008, IDX-015, PERF-009) → memory (JVM-001, JVM-005, BRK-*, IP-001) → CPU (HOT-005, OS-001, OS-003) → uneven write load (SHD-016, HOT-002, HOT-001, SHD-006, SHD-012) → ingest pipeline (ING-002, ING-001) → index settings (IDX-007, PERF-004) |
| Is search slow? | search rejections, search queue, high latency (PERF-001, 002), busy search pool with low CPU (PERF-013) | memory → CPU → storage (PERF-013, FRZ-*, DISK-008, PERF-009, PERF-003) → query cost (PERF-011, PERF-010, PERF-005, GEN-001) → shard count (SHD-001, OVS-*, SHD-004, SHD-009) → uneven search load. PERF-013 moves storage to the front |
| Is storage the limit? | none | IDX-005, PERF-012, IDX-014, DISK-008, PERF-013, FRZ-002, FRZ-001, PERF-009, IDX-015 |
| Do restarts or recoveries skew the numbers? | none | OS-007 → DIF-002 → OS-006 → CLU-020, REC-001, HOT-003 |
| Capacity or concentration? | none | tier CPU (HOT-005) → disk (DISK-001 to 003, DIF-008, COST-004) → concentration (HOT-001, HOT-002, SHD-006, SHD-016, NODE-001) |

A cause counts when its finding is Critical or Warning (PERF-013 also at Info). When the symptom is on certain nodes (a queue or rejections there, PERF-013 nodes), a finding that names nodes counts only if it names one of them or another node of the same data tier, so high heap on a frozen node is not named for a write queue on a hot node. The first group with a finding is the verdict, and the other groups with findings are listed after it. With no symptom the row says so and names no cause, and if symptoms exist but no group has a finding, the row points outside Elasticsearch (clients, queries). The order is the tool's judgment of where to look first, not an official decision tree. The summary is left out when `--only` runs part of the rules. It is also in the Markdown, console, JSON (`bottleneck`) and Support summary output.

### Health check areas

| Area | Categories | Representative findings |
| --- | --- | --- |
| Availability | Cluster | Status, unassigned shards, master quorum, shard limit, node shutdown, voting exclusion |
| Capacity | Node, Hot spots and balancing, Storage cost | heap, GC, CPU, disk, watermarks, thread pools, circuit breakers, tier saturation, skew, data kept on hot, idle replicas, ingest headroom, storage by data type, sizing signals per tier |
| Data structure | Shards and indices, Vector search | Shard size, oversharding, mapping limits, write blocks, vector memory |
| Performance | Performance baselines, Runtime | Expensive search patterns, caches, ingest, hot threads, logs |
| Data protection and operations | Operations | Snapshot RPO, SLM, ILM, license, monitoring, ML |
| Security | Security and authentication | Security features, TLS certificate expiry |
| Configuration | Configuration baselines, Settings changes | Required official settings, changes from defaults |

---

## Elastic Support summary

With `--support-summary FILE`, esdoctor writes a Markdown summary, separate from the analysis report, that you can attach to a case with Elastic Support. Without the option, no summary is written.

```bash
python3 analyze.py diagnostic.zip --support-summary support-summary.md            # default basic masking
python3 analyze.py diagnostic.zip --support-summary support-summary.md --mask strict
```

**Included**: cluster overview, results by area, and for Critical and Warning findings the observed facts, evidence basis, source files in the bundle and evidence tables (up to 10 rows). Also Info findings, items that could not be checked, and a node summary.
**Not included**: the tool's recommendation text, raw server log excerpts, hot threads thread names and stacks. For log findings only the counts and categories remain.

Masking replaces values with aliases such as `node-001`, `ip-001` and `path-001`. The same value always gets the same alias. The original values are only in the mapping file (`*.mask-map.json`, permission 0600), so you can translate aliases in Support's reply back. **Do not take the mapping file out of the customer environment.**

| Level | Masked |
| --- | --- |
| `none` | Nothing is masked |
| `basic` (default) | Cluster name and UUID, node name, ID, host, IP and transport address, paths, addresses, URLs and bucket values in node settings, certificate paths and subjects, license holder, repository buckets, paths and endpoints |
| `strict` | basic + indices, aliases, data streams and backing indices, ILM and SLM policies, templates, pipelines, repositories and snapshots, ML / transform / rollup IDs |

After masking each output string, a separate check looks for leftover original identifiers (case-insensitive) and unregistered IPv4 addresses. If anything is left, **the summary and the mapping file are not written** and the exit code is 2. The check covers identifiers collected from the bundle, so read the summary yourself once before you send it.

Limits: values shorter than 6 characters can overlap ordinary words, so they are not checked for leftovers. System indices that start with `.`, default install paths, loopback addresses, versions and timestamps are not masked. This summary does not replace a Support case, and a request for the original diagnostic bundle is a separate matter.

---

## Documentation

| Document | Contents |
| --- | --- |
| [RULES.md](RULES.md) ([한국어](RULES.ko.md)) | Full specification of all 133 rules: conditions, thresholds (current value and source), required input, reference docs, settings knowledge base. **Generated from the code** |
| [COVERAGE.md](COVERAGE.md) ([한국어](COVERAGE.ko.md)) | Which official doc items are covered, and why some items cannot be judged |
| [CHANGELOG.md](CHANGELOG.md) ([한국어](CHANGELOG.ko.md)) | Change history: previous behavior → current behavior, and the reason |

Do not edit RULES.md or RULES.ko.md by hand. Regenerate them after you change a rule.

```bash
python3 tools/gen_rules_doc.py            # regenerate RULES.md and RULES.ko.md
python3 tools/gen_rules_doc.py --check    # check for missing or unused thresholds and missing docstrings
```

---

## Adjusting thresholds

```bash
python3 analyze.py --print-thresholds > my.json   # extract the defaults
# keep only the keys you need in my.json and edit them
python3 analyze.py bundle.zip --thresholds my.json
```

The source of each of the 141 thresholds (`[Official]` / `[Tool]`) is in the comments of `esdoctor/thresholds.py` and in the appendix of RULES.md. Do not change `[Official]` values.

---

## Adding rules

1. Write a function in the matching module (`esdoctor/rules/*.py`) and register it in `RULES`.
2. State the exact condition in the function docstring. It is copied as is into RULES.md.
3. Declare the input files it needs in `REQUIRES` in `esdoctor/rules/__init__.py`.
4. Register the evidence basis of the finding ID in `esdoctor/basis.py`.
5. Add any new threshold to `esdoctor/thresholds.py` with a source comment.
6. Read numeric fields with `num()`, lists of dicts with `dicts()`, lists of strings with `strs()` and dict entries with `items()`. This absorbs format differences between versions.
7. Add a scenario to `tests/drive_branches.py` that makes the finding actually fire, so no branch is left unexecuted.
8. Confirm that `bash tests/run_all.sh <bundle>` passes.

```python
def r_example(ctx):
    """Warning if any node has heap_used_percent >= example_warn."""
    bad = [n.name for n in ctx.nodes if (n.heap_used_pct or 0) >= ctx.t["example_warn"]]
    if not bad:
        return []
    return [Finding("EX-001", "node", Severity.WARNING, T("rules.example.r_example.01"),
                    observed=T("rules.example.r_example.02") % ", ".join(bad),
                    impact=T("rules.example.r_example.03"),
                    recommend=T("rules.example.r_example.04"),
                    evidence=table(["node"], [[b] for b in bad]),
                    source="nodes_stats.json")]
```

Do not write user-facing text in the code. Add it under the same key to `esdoctor/i18n/ko.txt` and `en.txt` and read it with `T("key")`. Text inside tables is marked with `N_("key")` and converted with `tr()` where it is used. Follow [docs/STYLE.md](docs/STYLE.md) for style and terms. `tests/i18n_check.py` checks the keys, `%` fields and dashes of both catalogs.

When a string contains a literal `%` and a `%` format is applied to it, write `%%` (`tests/lint_format.py` checks this).

---

## Verification

```bash
bash tests/run_all.sh diagnostic.zip
```

| Check | Content | Current result |
| --- | --- | --- |
| `tests/lint_format.py` | Static check of `%` format strings, including format errors in branches that never run | 985 strings, 0 problems |
| `tests/verify_logic.py` | Assertions on calculation logic: watermarks, GC logs, cross-check against the settings knowledge base, multi-tier, mounted indices and write block cases. Runs in Korean and English | 110 passed |
| `tests/drive_branches.py` | Forces every finding branch to run with 63 scenarios and checks the severity too | 63 passed, 0 finding branches not run |
| `tests/fuzz_rules.py` | Mutations: missing fields, null, numbers as strings (`--harsh` uses arbitrary types) | 0 failures |
| `tools/gen_rules_doc.py --check` | Consistency of thresholds and docstrings | 0 problems |
| `tests/test_local_mode.py` | Local and remote mode handling (false positives from logs/, gz, double counting, syscalls/ branches, collection failure messages) on synthetic data. No external bundle needed | 0 failures |
| `tests/test_logsdb.py` | Every branch of the document limit, logsdb and force merge findings (SHD-008, 013, 014, 015, IDX-013, ILM-007, 008, 009) on synthetic data, in both languages. No external bundle needed | 0 failures |
| `tests/test_write_path.py` | Every branch of the write path and operations findings (PERF-012, OS-007, SHD-016, IDX-014, 015, CLU-017, MAP-004, DIF-013) on synthetic data, in both languages. No external bundle needed | 0 failures |
| `tests/test_doc_audit.py` | Fixes from the official documentation audit: JVM-002 oops flag, CLU-007, DISK-006, DISK-007, IDX-013, CLU-015, SHD-010, MAP-006, max_headroom conditions, development mode, and context-dependent settings defaults, on synthetic data, in both languages. No external bundle needed | 0 failures |
| `tests/test_bottleneck_cost.py` | Bottleneck summary, recently restarted nodes left out of comparisons (HOT-001, 002, PERF-012, DIF-009), FRZ-002, PERF-013, ING-001, COST-001 to 006, bottleneck causes scoped to the symptom tiers, DIF-008 per tier, DIF-014 interval checks and SET-005 per tier on synthetic data, in both languages. No external bundle needed | 0 failures |
| `tests/test_handoff.py` | Support summary: no canary identifier (cluster, node, host, IP, path, certificate, license, repository, index, log, stack) is left at any level, mapping round trip, no summary when masking fails, CLI options. No external bundle needed | 0 failures |
| `tests/check_docs.py` | Numbers, lists and links in README, RULES, COVERAGE and CHANGELOG match the code; finding IDs match the evidence basis table | 0 mismatches |

`tests/make_broken_bundle.py` creates a bundle with failure conditions injected into a healthy bundle (for report examples and manual checks).

---

## Limitations

- **Remote mode and multi-node local mode are not verified on real bundles.** Local mode was checked on one single-node test environment. A production-scale bundle may have a different file layout (for example per-node log file names).

The limits below come from what a diagnostic bundle collects, not from the tool.

- **Query bodies are not in the bundle.** The share of expensive patterns is judged from the cumulative use count per query type (`cluster_stats.indices.search`, PERF-011). To find which query on which index, use slowlog or the Search Profiler.
- **Security configuration (users, roles, privileges) is not judged.** It belongs to a security audit and is sensitive data. Only whether security features are enabled and certificate expiry are checked.
- **Index setting defaults are not in the bundle.** The index settings knowledge base (30 settings) is based on the official docs and is not cross-checked against the bundle.
- **OS kernel settings** (readahead, vm.swappiness, raw vm.max_map_count) are not in api mode bundles, so they are not judged. From `syscalls/` in local and remote mode, only sysctl (vm.max_map_count, vm.swappiness), proc-limit (nofile, nproc) and dmesg (OOM killer) are read (SYS-001 to SYS-004). readahead, THP, iostat, jstack and netstat are not read yet.
- **Hot threads is a 500ms snapshot** taken at collection time. If you collect when the cluster is idle, it shows no signal.
- The disk saturation forecast (DIF-008) is a linear extrapolation between two points in time.

[COVERAGE.md](COVERAGE.md) ([한국어](COVERAGE.ko.md)) lists every item that cannot be judged, with the reason.

---

## Structure

```
.
├── analyze.py                  # CLI entry point
├── requirements.txt            # no external dependencies (for the record)
├── esdoctor/
│   ├── __init__.py             # version, baseline, version gates
│   ├── loader.py               # zip/directory loading, absorbs api, local and remote layouts
│   ├── context.py              # normalization layer: effective watermarks, tiers, index classification, write targets, deployment type
│   ├── thresholds.py           # all thresholds (with source comments)
│   ├── settings_kb.py          # settings knowledge base (defaults, type, meaning, impact)
│   ├── basis.py                # evidence basis of findings
│   ├── engine.py               # rule execution and isolation, not-collected handling, overall result, version check
│   ├── envcheck.py             # runtime environment check (--check-env)
│   ├── mask.py                 # masking for the Support summary (alias replacement, leak check)
│   ├── diff.py                 # two-bundle comparison
│   ├── bottleneck.py           # bottleneck summary (five questions from symptoms and findings)
│   ├── i18n/                   # ko.txt and en.txt message catalogs, T() / tr() / N_()
│   ├── model.py                # Finding / Severity
│   ├── util.py                 # unit parsing, safe accessors (num, dicts, strs, items)
│   ├── rules/                  # cluster · settings · nodes · shards · sharding · guidance · hotspot · cost · ops · deep · runtime
│   └── report/                 # text (console, Markdown) · html (single file) · handoff (Support summary)
├── tools/
│   ├── gen_rules_doc.py        # RULES.md generator + consistency check
│   ├── build_pyz.py            # build the single-file distribution (esdoctor.pyz), optional
│   └── build_binary.sh         # build the standalone executable, optional
├── tests/
│   ├── run_all.sh              # run all checks
│   ├── i18n_check.py           # message catalog check (keys, fields, dashes)
│   ├── check_docs.py           # documentation consistency check
│   ├── lint_format.py          # static check of format strings
│   ├── verify_logic.py         # assertions on calculation logic
│   ├── drive_branches.py       # drives every finding branch
│   ├── fuzz_rules.py          # input mutation fuzzing
│   ├── test_handoff.py         # Support summary and masking checks (synthetic data)
│   ├── test_logsdb.py          # document limit, logsdb and force merge checks (synthetic data)
│   ├── test_write_path.py      # write path and operations checks (synthetic data)
│   ├── test_bottleneck_cost.py # bottleneck summary and storage cost checks (synthetic data)
│   ├── test_doc_audit.py       # fixes from the official documentation audit (synthetic data)
│   └── make_broken_bundle.py   # create a bundle with injected failures
├── docs/STYLE.md              # style and glossary
├── README.md / README.ko.md
├── RULES.md / RULES.ko.md      # rule specification (generated)
├── COVERAGE.md / .ko.md        # comparison with the official docs
└── CHANGELOG.md / .ko.md       # change history
```

---

## Release procedure

```bash
# 1) Update __version__ in esdoctor/__init__.py and CHANGELOG.md
# 2) Regenerate the specification and run all checks
python3 tools/gen_rules_doc.py
bash tests/run_all.sh <bundle-for-validation.zip>
# 3) (optional) Build the single-file distribution and attach it to GitHub Releases (do not commit it)
python3 tools/build_pyz.py        # dist/esdoctor.pyz
git tag v0.13.0
```

Validation diagnostic bundles and their analysis reports contain customer environment information (cluster names, index names, hosts), so do not commit them to the repository.

---

## License

This project is open-sourced software licensed under the [MIT license](LICENSE).
