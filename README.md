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

At implementation level, table changes are inferred from the presence or absence of their fields. A table addition or removal is therefore reported through its associated field differences. The operational goal remains the same: detect structural changes that may affect masking coverage.

## Recommended workflow

Follow this sequence when onboarding a new Ruleset pair:

1. Configure Delphix, SMTP, and notification settings.
2. Create the discovery Ruleset manually in Delphix and initially align its tables and fields with the productive Ruleset.
3. Query the Rulesets available in the Engine with `--list-engine-rulesets`.
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
6. Compare discovery data with the productive snapshot and accepted baseline exclusions.
7. Print consolidated results in the terminal.
8. Send one HTML email per affected Ruleset when notifications are enabled.

The discovery Ruleset is configured with `refreshDropsTables = true` when required, so refresh operations can reflect tables removed from the source.

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

The application uses Python standard-library modules only; no external Python package installation is required.

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
| SQLite runtime database | `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` |

For development or testing, set `DELPHIX_RULESET_MONITOR_DATA_DIR` to use another data directory without moving the application scripts.

## Configuration

Run the interactive configuration assistant:

```bash
sudo ruleset_monitor.py --configure
```

The assistant requests Delphix and SMTP credentials without displaying password input and writes `/etc/delphix-ruleset-monitor/config.json` with mode `600`.

Secrets may be stored with the `b64:` prefix. This is only reversible Base64 obfuscation, not encryption. Protect `/etc/delphix-ruleset-monitor/config.json` using filesystem permissions and an appropriate secrets-management process.

Important configuration fields include:

```json
{
  "delphix_host": "https://delphix.example.com",
  "username": "b64:...",
  "password": "b64:...",
  "api_prefix": "/masking/api",
  "mock_mode": false,
  "email_enabled": false,
  "smtp_host": "smtp.example.com",
  "smtp_port": 587,
  "smtp_user": "b64:...",
  "smtp_password": "b64:...",
  "use_tls": true,
  "email_from": "delphix-monitor@example.com",
  "email_to": ["operations@example.com"]
}
```

Productive/discovery Ruleset pairs are stored in SQLite and registered with `--add-ruleset`.

Before registering a pair, create the discovery Ruleset manually in Delphix Continuous Compliance. Its initial content must match the productive Ruleset, including the configured tables and fields. This ensures that the first inventory comparison starts from an aligned state and that the initial baseline does not contain accidental differences. The monitor validates and stores the pair; it does not create or clone Rulesets in Delphix.

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

Run an audit:

```bash
sudo ruleset_monitor.py --audit
```

Only active pairs are audited. Drift is printed to the terminal and, when enabled, one email is sent for each affected productive Ruleset.

Inspect local data:

```bash
sudo ruleset_monitor.py --list-prod
sudo ruleset_monitor.py --list-prod --ruleset-id PROD_ID DISCOVERY_ID
sudo ruleset_monitor.py --list-exclusions
sudo ruleset_monitor.py --list-exclusions --ruleset-id PROD_ID DISCOVERY_ID
sudo ruleset_monitor.py --list-exclusions --filter-table TABLE_NAME
sudo ruleset_monitor.py --list-engine-rulesets
```

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

The CLI also supports listing configured pairs with `--list-config`, pausing or reactivating a pair with `--set-active`, removing a pair with `--remove-ruleset`, inspecting the productive inventory with `--list-prod`, inspecting baseline exclusions with `--list-exclusions`, and clearing all local state with `--purge`. Use `mock_mode` for development without contacting Delphix.

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
- Base64 values are not encrypted.
- Keep `/etc/delphix-ruleset-monitor/config.json` readable only by the service account or root.
- The supplied systemd service runs as `root`.
- Review SMTP credentials and recipients before enabling notifications.

## Operational response

When drift is detected, review the affected table and field in the source database and Delphix. If the change is expected and intentionally accepted, rebuild the baseline for the relevant pair. If the change requires masking coverage, update the productive Ruleset first and then rebuild the baseline.

For Spanish operational instructions, see [GUIA_USUARIO.md](GUIA_USUARIO.md).
