# Delphix Ruleset Drift Monitor

Delphix Continuous Compliance / Masking Engine monitor for detecting schema drift between a productive Ruleset and a discovery (dummy) Ruleset.

The monitor identifies source-database changes that may require a review of the productive masking configuration.

## Purpose

Each monitored pair contains:

- A **productive Ruleset**, representing the approved Delphix masking configuration.
- A **discovery Ruleset**, also called the **dummy** or **probe** Ruleset, refreshed against the source database to discover its current schema.

The monitor reports these five drift cases:

1. Tables added to the source database.
2. Tables removed from the source database.
3. Fields added to an existing table.
4. Fields removed from an existing table.
5. Data type changes on existing fields.

Known table changes are evaluated through their associated fields. In addition, the monitor queries the source connector catalog so a table that exists in the source but is absent from both Rulesets can also be detected. The operational goal remains the same: detect structural changes that may affect masking coverage.

## Deployment models

The Ruleset pair must be prepared according to the masking method:

### In-Place masking

```text
Productive Ruleset → source database connector
Discovery Ruleset  → same source database connector
```

The productive Ruleset represents the approved masking configuration for the source database. The discovery Ruleset is initially aligned with it and is refreshed to discover changes in that same source.

### On-The-Fly masking

```text
Productive/target Ruleset → target database connector
Discovery/source Ruleset  → source database connector
```

The On-The-Fly job uses the productive/target Ruleset and separately selects the source connector. The discovery Ruleset is used by this monitor to inspect the real source structure. The monitor compares the expected target structure with the structure discovered in the source; intentional differences must be accepted through the baseline.

## Recommended workflow

Follow this sequence when onboarding a new Ruleset pair:

1. Configure Delphix, SMTP, and notification settings.
2. Query the Rulesets available in the Engine with `--list-engine-rulesets` to identify the productive Ruleset and its ID.
3. Create the discovery Ruleset manually in Delphix and initially align its tables and fields with the productive Ruleset.
4. Register the productive/discovery pair with `--add-ruleset`.
5. Create the initial baseline with `--init-baseline`.
6. Run the audit with `--audit`.
7. Review any detected differences and either update the productive Ruleset or explicitly accept the differences.
8. Rebuild the baseline with `--init-baseline` after the corrective changes have been applied.
9. Run `--audit` again to confirm that no unmanaged differences remain.
10. Schedule recurring audits with the systemd timer.

Do not rebuild the baseline automatically when an alert is received. First determine whether the difference requires masking coverage or is an intentional, accepted change.

## How it works

For each active Ruleset pair, an audit performs this sequence:

1. Read the productive Ruleset inventory from Delphix.
2. Store a current snapshot in the local SQLite database.
3. Refresh the discovery Ruleset using Delphix's asynchronous refresh API.
4. Wait until the refresh task succeeds or fails.
5. Read the discovery Ruleset inventory.
6. Query the source connector catalog to obtain the tables currently visible in the source database.
7. Compare discovery data and source tables with the productive snapshot and accepted baseline exclusions.
8. Print consolidated results in the terminal.
9. Send one HTML email per affected Ruleset when notifications are enabled.

The discovery Ruleset is configured with `refreshDropsTables = true` when required, so refresh operations can reflect tables removed from the source. The independent connector catalog query is what allows the monitor to detect tables that have not yet been added to either Ruleset.

## Repository contents

| File | Purpose |
|---|---|
| `ruleset_monitor.py` | Command-line interface and audit orchestration. |
| `delphix_client.py` | REST client for Delphix Masking Engine. |
| `db_manager.py` | SQLite schema, snapshots, baseline exclusions, and drift comparison. |
| `email_notifier.py` | HTML email generation and SMTP delivery. |
| `config.example.json` | Example configuration file. |
| `install.sh` | Full Linux installation, including systemd timer setup. |
| `install_systemd.sh` | Installs only the systemd service and timer files. |
| `delphix-ruleset-monitor.service` | One-shot audit service. |
| `delphix-ruleset-monitor.timer` | Weekday schedule for the audit service. |
| `GUIA_USUARIO.md` | Spanish user and operations guide. |

The SQLite database is runtime data. In an installed deployment it is generated at `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` and is intentionally excluded from Git by `.gitignore`. Set `DELPHIX_RULESET_MONITOR_DATA_DIR` to override the data directory for development or testing.

## Requirements

- Linux with Python 3.
- Access to the Delphix Masking Engine REST API.
- A productive Ruleset and a discovery Ruleset for every monitored pair.
- SMTP access if email notifications are required.
- Root privileges for the standard installation and systemd setup.
- [age](https://github.com/FiloSottile/age) (`age` and `age-keygen` binaries) to encrypt credentials. On RHEL/Oracle Linux 9 it is available from EPEL: `dnf install age`.

The application uses Python standard-library modules only; no external Python package installation is required. The installer stops if `age` is not available.

## Installation

The installer resolves its own location, so it can be invoked from any working directory:

```bash
sudo /path/to/delphix-ruleset-monitor/install.sh
```

The installer copies the application to `/usr/local/bin/delphix-ruleset-monitor`, stores runtime data under `/var/lib/delphix-ruleset-monitor`, creates the global command link `/usr/local/bin/ruleset_monitor.py`, and enables the `delphix-ruleset-monitor.timer` systemd timer.

There is no need to run `install_systemd.sh` after a full installation. `install.sh` already installs the systemd units, reloads systemd, and enables the timer. Use `install_systemd.sh` only when the application is already installed and the systemd units need to be installed or refreshed independently.

Each full installation removes any pre-existing `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` so the application starts with a clean local state. This deletes registered pairs, productive inventories, and baseline exclusions. The configuration under `/etc/delphix-ruleset-monitor/config.json` is preserved during reinstallations.

### Installation layout

The application keeps executable files and mutable runtime data separate:

| Purpose | Location |
|---|---|
| Application scripts | `/usr/local/bin/delphix-ruleset-monitor/` |
| Global command link | `/usr/local/bin/ruleset_monitor.py` |
| Local configuration | `/etc/delphix-ruleset-monitor/config.json` |
| age identity for credentials | `/etc/delphix-ruleset-monitor/age.key` |
| SQLite runtime database | `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` |

For development or testing, set `DELPHIX_RULESET_MONITOR_DATA_DIR` to use another data directory without moving the application scripts.

## Configuration

Run the interactive configuration assistant:

```bash
sudo ruleset_monitor.py --configure
```

The assistant requests Delphix and SMTP credentials without displaying password input and writes `/etc/delphix-ruleset-monitor/config.json` with mode `600`.

The Delphix and SMTP usernames and passwords (`username`, `password`, `smtp_user`, `smtp_password`) are encrypted with age. On its first run, the assistant creates the age identity `/etc/delphix-ruleset-monitor/age.key` with mode `600` and encrypts those fields with its public key. The other fields remain in plain text.

Back up `age.key` separately from `config.json`: without it the credentials cannot be decrypted and `--configure` must be run again. If a credential field contains a value that is not age-encrypted, the monitor stops with an error.

Because the service runs unattended, the identity is stored on the same host. Encryption protects the credentials if `config.json` is copied, backed up, or shared, but not against a user who already has root access to the host.

Important configuration fields include:

```json
{
  "delphix_host": "https://delphix.example.com",
  "username": "-----BEGIN AGE ENCRYPTED FILE-----\n...",
  "password": "-----BEGIN AGE ENCRYPTED FILE-----\n...",
  "api_prefix": "/masking/api",
  "mock_mode": false,
  "refresh_retries": 2,
  "refresh_retry_delay_seconds": 60,
  "refresh_timeout_seconds": 300,
  "email_enabled": false,
  "smtp_host": "smtp.example.com",
  "smtp_port": 587,
  "smtp_user": "-----BEGIN AGE ENCRYPTED FILE-----\n...",
  "smtp_password": "-----BEGIN AGE ENCRYPTED FILE-----\n...",
  "use_tls": true,
  "email_from": "delphix-monitor@example.com",
  "email_to": ["operations@example.com"]
}
```

Productive/discovery Ruleset pairs are stored in SQLite and registered with `--add-ruleset`.

Before preparing or registering a pair, list the Rulesets available in the Engine to identify the official names and IDs:

```bash
sudo ruleset_monitor.py --list-engine-rulesets
```

The command displays the Ruleset ID, official name, and container type returned by the Delphix Engine.

Before registering a pair, create the discovery Ruleset manually in Delphix Continuous Compliance. For In-Place masking, both Rulesets use the same source connector. For On-The-Fly masking, the productive Ruleset belongs to the target connector and the discovery Ruleset belongs to the source connector. In both cases, the discovery Ruleset should initially match the structure represented by the productive Ruleset, unless the source and target are intentionally different. The monitor validates and stores the pair; it does not create or clone Rulesets in Delphix.

## Ruleset pair management

Register a pair:

```bash
sudo ruleset_monitor.py --add-ruleset PROD_ID DISCOVERY_ID
```

List configured pairs:

```bash
sudo ruleset_monitor.py --list-config
```

Pause or resume auditing for a pair:

```bash
sudo ruleset_monitor.py --set-active PROD_ID DISCOVERY_ID NO
sudo ruleset_monitor.py --set-active PROD_ID DISCOVERY_ID YES
```

Remove a pair and its local inventory and exclusions:

```bash
sudo ruleset_monitor.py --remove-ruleset PROD_ID DISCOVERY_ID
```

## Baseline and auditing

The baseline records differences intentionally accepted between discovery and productive inventories:

```bash
sudo ruleset_monitor.py --init-baseline
```

After registering a newly prepared pair, create its initial baseline while the discovery Ruleset still matches the productive Ruleset:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id PROD_ID DISCOVERY_ID
```

Rebuilding the baseline replaces the previous exclusions for the selected pair. Review changes carefully before using this command as an operational response to an alert.

If a table exists in the source but is intentionally not added to either Ruleset, rebuilding the baseline records a table-level exclusion for it. Future changes in that excluded table will not generate alerts until the exclusion is removed by rebuilding the baseline after the table is brought under monitoring.

Run an audit:

```bash
sudo ruleset_monitor.py --audit
```

Only active pairs are audited. Drift is printed to the terminal and, when enabled, one email is sent for each affected productive Ruleset. If a pair cannot be processed, see [Discovery refresh failures](#discovery-refresh-failures).

Inspect local data:

```bash
sudo ruleset_monitor.py --list-prod
sudo ruleset_monitor.py --list-prod --ruleset-id PROD_ID DISCOVERY_ID
sudo ruleset_monitor.py --list-exclusions
sudo ruleset_monitor.py --list-exclusions --ruleset-id PROD_ID DISCOVERY_ID
sudo ruleset_monitor.py --list-exclusions --filter-table TABLE_NAME
sudo ruleset_monitor.py --list-engine-rulesets
sudo ruleset_monitor.py --list-orphan-exclusions
```

### Discovery refresh failures

If the refresh of a discovery Ruleset fails or times out, the monitor retries it according to `refresh_retries`, `refresh_retry_delay_seconds`, and `refresh_timeout_seconds` (defaults: 2, 60, and 300).

If every attempt fails, the pair is reported as not processed and the run continues with the remaining pairs; the monitor never compares against stale discovery data, and `--init-baseline` keeps the previous baseline of that pair. A table of unprocessed Rulesets is printed and, when email is enabled, an incomplete-audit notice is sent on every run while the failure persists.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | All selected pairs were processed, with or without drift. |
| `75` | Partial run: at least one pair could not be processed. The systemd service declares `SuccessExitStatus=75`, so the unit does not enter the `failed` state. |
| `1` | General error, such as a missing configuration file or a failed Delphix authentication. |

## Scheduling

The default timer runs the audit Monday through Friday at 08:00:

```text
OnCalendar=Mon..Fri *-*-* 08:00:00
```

Useful commands:

```bash
systemctl status delphix-ruleset-monitor.timer
systemctl list-timers delphix-ruleset-monitor.timer
journalctl -u delphix-ruleset-monitor.service
```

Cron can run the same installed command as `root` using absolute paths:

```cron
0 8 * * 1-5 /usr/local/bin/ruleset_monitor.py --audit >> /var/log/delphix-ruleset-monitor-cron.log 2>&1
```

The application uses `/var/lib/delphix-ruleset-monitor` by default, so no user-specific home directory or working directory is required.

## Complementary operations

The CLI also supports listing configured pairs with `--list-config`, pausing or reactivating a pair with `--set-active`, removing a pair with `--remove-ruleset`, inspecting the productive inventory with `--list-prod`, inspecting baseline exclusions with `--list-exclusions`, finding orphan exclusions with `--list-orphan-exclusions`, and clearing all local state with `--purge`. Use `mock_mode` for development without contacting Delphix.

## Local persistence

The runtime database is `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` in an installed deployment. The application creates these tables when needed:

- `ruleset_config`: productive/discovery pair configuration and active state.
- `prod_inventory`: latest productive Ruleset snapshot.
- `exclusions`: accepted discovery-versus-production baseline differences.

Clear all local monitor state only when intentionally starting over:

```bash
sudo ruleset_monitor.py --purge
sudo ruleset_monitor.py --purge -y
```

## Mock mode

Set `mock_mode` to `true` to exercise the client without contacting Delphix. Mock mode provides synthetic Ruleset and table/column data for CLI demonstrations and development.

## Security notes

- The application currently disables TLS certificate and hostname verification for Delphix API calls.
- Credentials are encrypted with age, but the identity (`age.key`) resides on the same host, so root on the host can decrypt them.
- Keep `/etc/delphix-ruleset-monitor/config.json` and `/etc/delphix-ruleset-monitor/age.key` readable only by root, and back up `age.key` separately.
- The supplied systemd service runs as `root`.
- Review SMTP credentials and recipients before enabling notifications.

## Operational response

When drift is detected, review the affected table and field in the source database and Delphix. If the change is expected and intentionally accepted, rebuild the baseline for the relevant pair. If the change requires masking coverage, update the productive Ruleset first and then rebuild the baseline.

For Spanish operational instructions, see [GUIA_USUARIO.md](GUIA_USUARIO.md).
