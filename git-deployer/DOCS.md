# Home Assistant Git Deployer

Deploys four things from one git branch into Home Assistant, and nothing else:

- `automations.yaml`, `scripts.yaml`, `scenes.yaml`
- `dashboards/*.yaml` (dashboards running in YAML mode)

It never clones into `/config`. It keeps its own working copy in the add-on's data folder and copies
only those files across. `secrets.yaml`, `configuration.yaml`, `.storage`, `custom_components` and
everything else in `/config` are never read, written or deleted, even if they exist on the branch.
Symlinks and any other file names on the branch are ignored.

## What it does on every check

1. Fetches the branch (read-only token) into its own folder.
2. Validates the files: valid YAML, automations list is non-empty, every automation has an id and an
   alias, ids are unique, dashboards have `views`. If anything fails, **nothing is copied**.
3. Compares with `/config`. If the files are identical it does nothing.
4. Backs up each file it is about to overwrite, then copies the new files in.
5. Asks Home Assistant to check the configuration. **If the check fails, every file is restored** and
   newly created files are removed.
6. Reloads automations, scripts and scenes (no restart) and posts a notification.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `repository.url` | | HTTPS URL of the repository |
| `repository.username` | | Your GitHub user name |
| `repository.password` | | A fine-grained token with **Contents: read-only** on that one repository |
| `repository.branch` | `deploy` | Branch to deploy from |
| `dry_run` | `true` | Only report what would be copied. Nothing is changed |
| `poll_interval` | `0` | Seconds between checks. `0` checks once and stops |
| `reload` | `true` | Reload automations, scripts and scenes after a successful deploy |
| `keep_backups` | `20` | How many backup folders to keep |

## First use

1. Take a full Home Assistant backup.
2. Set the repository options and leave `dry_run: true` and `poll_interval: 0`. Start the add-on.
3. Read the log. It should say `DRY RUN: commit abc1234 would copy N file(s): ...` and that nothing
   was changed. Check that the list is what you expect.
4. Set `dry_run: false` and start it once. The log shows the files copied, the configuration check,
   the reloads and where the backup of the old files is.
5. When that works, set `poll_interval: 300`, switch on "Start on boot", and start it.

## Notes and limits

- Edits made in the Home Assistant UI to automations, scripts or scenes are overwritten by the next
  deploy. The overwritten version is kept in the add-on's backup folder. The git history is the
  real undo: revert the change in the repository and it deploys again.
- Backups live in the add-on's own data folder (`/data/backups`). They are part of Home Assistant
  backups of this add-on, but they are not visible from the file editor.
- The configuration check validates what Home Assistant loads from YAML. It cannot check dashboard
  contents; those are validated for structure only.
- If the branch is missing or the token is wrong, the log says so and nothing is changed.
