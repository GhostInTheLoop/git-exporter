# Configuration

```yaml
repository:
  url: <path to your repository>
  username: user
  password: pass
  pull_before_push: true
  commit_message: 'Home Assistant Git Exporter'
  branch_name: 'main'
export:
  lovelace: true
  addons: false
  esphome: true
  node_red: true
check:
  enabled: true
  check_for_secrets: true
  check_for_ips: true
include: []
exclude:
  - '*.db'
  - '*.log'
  - __pycache__
  - deps/
  - known_devices.yaml
  - tts/
  - '*.db-shm'
  - '*.db-wal'
  - '*.gz'
secrets: []
allowed_secrets: []
dry_run: false
```

### `repository.url`

Any https url to your git repository. (For now _no_ SSH)

### `repository.email` (Optional)

The email address the commits author is using.

### `repository.username`

Your username for https authentication.

### `repository.password`

Your password or [__access token__](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) for your repository.

### `repository.pull_before_push`

Should the repository be pulled first and commit the new state on top? If the remote is empty, or the
branch does not exist yet, it is created on the first push. The add-on never force-pushes: if the remote
has diverged the run fails.

### `repository.commit_message`

The commit message for the next commit.

### `repository.branch_name`

The working branch for the repository.

### `repository.ssl_verification` (Optional, default: true)

Use this to disable the ssl verification. Can be used for self-signed certificates. __Use this only when you know what you are doing__


### `export.lovelace`

Enable / Disable the export for the lovelace config.

### `export.addons` (default: false)

Enable / Disable the export for the supervisor addons config. Values of keys that look like
credentials (password, token, secret, key, ...) are replaced with `<redacted>`.

### `export.esphome`

Enable / Disable the export for the esphome config.

### `export.node_red`

Enable / Disable the export for the Node-RED flows.
Secure your credentials with [node-red-contrib-credentials](https://flows.nodered.org/node/node-red-contrib-credentials).


### `check.enabled`

Enable / Disable the checks in the exported files.

### `check.check_for_secrets`

Add your secret values to the check.

### `check.check_for_ips`

Add pattern for ip and mac addresses to the search.


### `include`

By default only `*.yaml`, `*.yml`, `*.json`, `*.md` and `.gitignore` files are exported from
`/config`. Add extra glob patterns here (for example `*.py`). Anything you add is still scanned
for secrets, but think before adding file types that can hold credentials.

### `exclude`

Additional files / folders to leave out of the config export.

Always excluded, regardless of `include`:

* `secrets.yaml` (only the key names are exported, with empty values)
* `.storage/`, `.cloud/`, `.git/`, `.uuid`
* `esphome/`, `node-red/` (exported separately, if enabled)
* `custom_components/`, `backups/`, `ssl/`, `deps/`, `tts/`
* `*service_account*`, `*client_secret*`, `*credentials*`, `*token*`, `*.pem`, `*.key`

### `secrets`

Additional secrets which will be checked for.


### `allowed_secrets`

Additional allowed secrets which will not make the secret check fail.


### `dry_run`

Only show the changes and don't commit or push. Use this for the first run.


## Known limitations

* The secret check is a safety net, not a guarantee. Review the first export in your repository by hand
  and keep the target repository **private**.
* Values from `secrets.yaml` are matched as literal strings (values shorter than 4 characters are skipped).
  Custom entries in `secrets` are regular expressions, so brackets in them can cause grep errors.
* `.storage` is never exported, so the device / entity / area registries and non-Lovelace dashboards
  are not in the repository.
* `hassio_role: manager` is only needed for `export.addons`. If you never enable that option the role
  can probably be removed (untested).
