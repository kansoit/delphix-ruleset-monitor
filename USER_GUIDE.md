# User Guide

## Delphix Ruleset Drift Monitor

This tool monitors structural drift between a productive Ruleset in Delphix Continuous Compliance and a discovery Ruleset used to discover the current structure of the source database.

Its purpose is to detect changes that could leave tables or fields outside masking coverage.

## Recommended workflow

To add a new Ruleset pair:

1. Configure the Delphix, SMTP, and notification settings.
2. Manually create the discovery Ruleset in Delphix and initially align its tables and fields with the productive Ruleset.
3. List the Rulesets available in the Engine with `--list-engine-rulesets`.
4. Register the productive/discovery pair with `--add-ruleset`.
5. Create the initial baseline with `--init-baseline`.
6. Run the audit with `--audit`.
7. Review the detected differences and correct the productive Ruleset or explicitly accept the differences.
8. Run `--init-baseline` again after applying the corrections.
9. Run `--audit` again to confirm that no unmanaged differences remain.
10. Schedule periodic audits with the systemd timer.

Do not rebuild the baseline automatically when an alert is received. First determine whether the difference requires masking coverage or is an intentional change that can be accepted.

## Monitored cases

The monitor covers these five cases:

1. Tables added to the source.
2. Tables removed from the source.
3. Fields added to a table.
4. Fields removed from a table.
5. Data type changes in existing fields.

Known table changes are evaluated through their fields. In addition, the monitor queries the source database connector catalog to detect a table that exists in the source but is absent from both Rulesets. If a table appears with new columns, those columns are reported as new; if all known columns of a table disappear, they are reported as removed. The operational goal is to detect any relevant structural change.

## Main concepts

### Productive Ruleset

The Ruleset containing the approved masking configuration: tables, fields, and algorithms.

### Discovery Ruleset

An auxiliary Ruleset refreshed against the source database. Its purpose is to discover the actual structure that exists at that time.

### Baseline

The set of known and accepted differences between the productive and discovery Rulesets. A difference included in the baseline does not generate another alert during the audit.

## Audit flow

For each active pair, the program:

1. Retrieves the current productive Ruleset inventory.
2. Stores that snapshot in SQLite.
3. Refreshes the discovery Ruleset.
4. Waits for the asynchronous Delphix task to finish.
5. Retrieves the tables and fields discovered by the probe.
6. Queries the connector catalog to obtain the tables currently visible in the source database.
7. Compares both inventories, the source catalog, and the baseline exclusions.
8. Displays the differences.
9. Sends an HTML email for each Ruleset with differences, if email is enabled.

## Installation

The installer resolves its own location, so it can be run from any directory:

```bash
sudo /path/to/repository/delphix-ruleset-monitor/install.sh
```

The installation copies the application to `/usr/local/bin/delphix-ruleset-monitor`, stores runtime data in `/var/lib/delphix-ruleset-monitor`, creates the global command `/usr/local/bin/ruleset_monitor.py`, and enables a systemd timer that runs the audit Monday through Friday at 08:00.

It is not necessary to run `install_systemd.sh` after a complete installation. `install.sh` already installs the systemd units, reloads systemd, and enables the timer. Use `install_systemd.sh` only when the application is already installed and the systemd units must be installed or updated independently.

Each complete installation removes `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` if it exists. This removes registered pairs, productive inventories, and baseline exclusions, so the pairs must be registered and their baselines recreated afterwards. The configuration at `/etc/delphix-ruleset-monitor/config.json` is preserved during reinstalls.

### Separation between application and data

The installation keeps executable scripts and modifiable data separate:

| Purpose | Location |
|---|---|
| Application scripts | `/usr/local/bin/delphix-ruleset-monitor/` |
| Global command | `/usr/local/bin/ruleset_monitor.py` |
| Local configuration | `/etc/delphix-ruleset-monitor/config.json` |
| Runtime SQLite database | `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` |

For development or testing, set `DELPHIX_RULESET_MONITOR_DATA_DIR` to use another data directory without moving the scripts.

## Configuration

Run the assistant:

```bash
sudo ruleset_monitor.py --configure
```

The assistant requests the Delphix URL, username and password, SMTP settings, sender, and recipients. It writes `/etc/delphix-ruleset-monitor/config.json` with mode `600`.

Values with the `b64:` prefix are only Base64-obfuscated; they are not encrypted. Protect `/etc/delphix-ruleset-monitor/config.json` with filesystem permissions and, preferably, an external secrets-management mechanism.

## Preparing the Ruleset pair in Delphix

Before registering a pair, list the Rulesets available in the Engine to identify the IDs of the productive and discovery Rulesets:

```bash
sudo ruleset_monitor.py --list-engine-rulesets
```

The query displays the ID, official name, and type of each Ruleset available in Delphix.

Before registering the pair in this tool, prepare the discovery Ruleset directly in the Delphix Continuous Compliance Engine:
Before registering the pair in this tool, prepare the discovery Ruleset directly in the Delphix Continuous Compliance Engine:

1. Identify the productive Ruleset to monitor.
2. Create a new Ruleset to use as the discovery Ruleset.
3. Initially copy the same content from the productive Ruleset to the discovery Ruleset: configured tables and fields.
4. Verify that both Rulesets represent the same initial structure.

This step is important because the first synchronization must start without accidental differences. The baseline is then built from an aligned pair, and subsequent differences represent real changes in the source.

The tool does not create or clone Rulesets in Delphix. The discovery Ruleset must already exist in the Engine, and its ID is used when registering the pair.

## Registering a Ruleset pair

```bash
sudo ruleset_monitor.py --add-ruleset PROD_ID DISCOVERY_ID
```

Example:

```bash
sudo ruleset_monitor.py --add-ruleset 4 5
```

The program validates the IDs against Delphix and stores the pair in the local SQLite database.

After registering the pair, create the initial baseline:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id PROD_ID DISCOVERY_ID
```

For example:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id 4 5
```

The first baseline must be created while the discovery Ruleset still has content equivalent to the productive Ruleset.

List registered pairs:

```bash
sudo ruleset_monitor.py --list-config
```

## Activating or pausing a pair

Pause a pair:

```bash
sudo ruleset_monitor.py --set-active PROD_ID DISCOVERY_ID NO
```

Reactivate it:

```bash
sudo ruleset_monitor.py --set-active PROD_ID DISCOVERY_ID YES
```

Paused pairs do not participate in `--audit`.

## Creating or rebuilding the baseline

For all active Rulesets:

```bash
sudo ruleset_monitor.py --init-baseline
```

For a specific pair:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id PROD_ID DISCOVERY_ID
```

This command removes the previous exclusions for the selected pair and recalculates the accepted differences between the discovery and productive Rulesets. Run it only after the differences have been reviewed and accepted.

If a table exists in the source but is intentionally not added to either Ruleset, rebuilding the baseline records a table-level exclusion for it. Future changes in that excluded table will not generate alerts until the exclusion is replaced by rebuilding the baseline after the table is brought under monitoring.

## Running the audit

```bash
sudo ruleset_monitor.py --audit
```

The result is shown in three main groups:

- New structures in the source.
- Structures removed from the source.
- Data type changes.

Added or removed tables are represented through their associated fields.

## Available queries

```bash
sudo ruleset_monitor.py --list-prod
sudo ruleset_monitor.py --list-prod --ruleset-id PROD_ID DISCOVERY_ID
sudo ruleset_monitor.py --list-exclusions
sudo ruleset_monitor.py --list-exclusions --ruleset-id PROD_ID DISCOVERY_ID
sudo ruleset_monitor.py --list-exclusions --filter-table CUSTOMERS
sudo ruleset_monitor.py --list-engine-rulesets
```

## Additional operations

The tool also allows you to:

- List configured pairs with `--list-config`.
- Pause a pair with `--set-active PROD_ID DISCOVERY_ID NO`.
- Reactivate a pair with `--set-active PROD_ID DISCOVERY_ID YES`.
- Remove a pair with `--remove-ruleset`.
- Inspect the productive inventory with `--list-prod`.
- Inspect exclusions with `--list-exclusions`.
- Filter exclusions by Ruleset or table.
- Purge all local state with `--purge`.
- Use `mock_mode` for tests without connecting to Delphix.

## Removing a pair

```bash
sudo ruleset_monitor.py --remove-ruleset PROD_ID DISCOVERY_ID
```

Removal deletes the local configuration, productive inventory, and associated exclusions.

## Purging local state

```bash
sudo ruleset_monitor.py --purge
sudo ruleset_monitor.py --purge -y
```

The SQLite database is created at `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` in a standard installation. If it does not exist, the program automatically creates the required structure when it starts. For development or testing, use `DELPHIX_RULESET_MONITOR_DATA_DIR`.

## Automatic execution with systemd

```bash
systemctl status delphix-ruleset-monitor.timer
systemctl list-timers delphix-ruleset-monitor.timer
journalctl -u delphix-ruleset-monitor.service
```

The service runs `ruleset_monitor.py --audit` as a `oneshot` task.

It can also be run from cron as `root`, using absolute paths:

```cron
0 8 * * 1-5 /usr/local/bin/ruleset_monitor.py --audit >> /var/log/delphix-ruleset-monitor-cron.log 2>&1
```

It does not depend on the working directory or the user's home directory.

## Test mode

To run the application without connecting to Delphix:

```json
"mock_mode": true
```

Mock mode generates example Rulesets, tables, and fields. It is useful for reviewing CLI output and the general workflow, but it does not validate the real Engine configuration.

## Recommended response to an alert

1. Review the reported table and field in the source database.
2. Confirm whether the change is expected.
3. If protection is required, update the productive Ruleset and assign the appropriate algorithm.
4. If the change is intentional and does not require masking, rebuild the baseline.
5. Run the audit again.

## Security considerations

- Base64 credentials are not encrypted.
- The client disables TLS certificate validation for Delphix.
- The supplied systemd service runs as `root`.
- Protect `/etc/delphix-ruleset-monitor/config.json` and review recipients before enabling email.
