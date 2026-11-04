# git-exporter-Private

A hardened, privately maintained fork of the Home Assistant Git Exporter add-on.
It exports your Home Assistant configuration to a git repository you control.

## Origin

Derived from the [Poeschl-HomeAssistant-Addons/git-exporter](https://github.com/Poeschl-HomeAssistant-Addons/git-exporter)
project (Apache License 2.0, see `LICENCE`). The upstream project is archived.

## Differences from upstream

- **Allow-list export.** Only `*.yaml`, `*.yml`, `*.json`, `*.md` and `.gitignore` are exported
  from `/config` (extend with the `include` option). Tokens, keys, caches, databases, backups
  and `custom_components/` are never exported.
- **Every exported file is secret-scanned**, not just a few file types. The scan also covers
  common key names and private key blocks, and matches the real values from `secrets.yaml`.
- **No credentials in URLs or `.git/config`.** The token is passed to git through `GIT_ASKPASS`.
- **No force-push.** A diverged remote makes the run fail instead of overwriting history.
- **Works with an empty remote repository** (creates the branch on first push) and no longer
  fails when there is nothing to commit.
- **Add-on options export is off by default** and credential-looking values are redacted.
- Built from source (no `image:` key), on a current base image, with `git-secrets` pinned to a
  commit, PyYAML from the Alpine package, and only `amd64` / `aarch64`.

## Install

1. Settings -> Add-ons -> Add-on Store -> menu -> Repositories.
2. Add `https://github.com/GhostInTheLoop/git-exporter-Private`. If the repository is private,
   Home Assistant needs a way to read it, which can be awkward; copying the `git-exporter`
   folder into `/addons` on the Home Assistant host is the simple alternative.
3. Install "Home Assistant Git Exporter (private)" and read `git-exporter/DOCS.md`.
4. **Run it with `dry_run: true` first** and check the log before enabling pushes.

## Status

Not yet tested on a live Home Assistant instance. The export logic was exercised with a
stubbed `bashio` against a fake `/config` and a local git remote, not inside the Supervisor,
and the Docker image has not been built.
