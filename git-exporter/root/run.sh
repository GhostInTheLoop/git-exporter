#!/usr/bin/env bashio
set -eo pipefail

# Enable jemalloc for better memory handling, if the base image ships it
if [ -f /usr/local/lib/libjemalloc.so.2 ]; then
    export LD_PRELOAD="/usr/local/lib/libjemalloc.so.2"
fi

local_repository='/data/repository'
pull_before_push="$(bashio::config 'repository.pull_before_push')"
branch="$(bashio::config 'repository.branch_name')"

# Only these file types are exported from /config. Everything else (tokens, caches,
# keys, databases, python code, ...) is ignored, so it can never be committed unscanned.
# Extra patterns can be added with the `include` option.
default_includes=('*.yaml' '*.yml' '*.json' '*.md' '.gitignore')
# Never exported, even if they match an include pattern.
hard_excludes=(
    'secrets.yaml' '.storage/' '.cloud/' '.git/' '.uuid'
    'esphome/' 'node-red/' 'custom_components/' 'backups/' 'ssl/' 'deps/' 'tts/'
    '*service_account*' '*client_secret*' '*credentials*' '*token*' '*.pem' '*.key'
)

function setup_git {
    local repository username password commiter_mail ssl_verify askpass
    repository=$(bashio::config 'repository.url')
    username=$(bashio::config 'repository.username')
    password=$(bashio::config 'repository.password')
    commiter_mail=$(bashio::config 'repository.email')
    ssl_verify=$(bashio::config 'repository.ssl_verification')

    # Hand credentials to git through an askpass helper, so the token is never put
    # into a URL, a command line, or the repository's .git/config.
    askpass="$(mktemp /tmp/git-askpass.XXXXXX)"
    cat > "$askpass" <<'ASKPASS'
#!/bin/sh
case "$1" in
    Username*) printf '%s\n' "$GIT_EXPORTER_USERNAME" ;;
    *) printf '%s\n' "$GIT_EXPORTER_PASSWORD" ;;
esac
ASKPASS
    chmod 700 "$askpass"
    export GIT_ASKPASS="$askpass"
    export GIT_TERMINAL_PROMPT=0
    export GIT_EXPORTER_USERNAME="$username"
    export GIT_EXPORTER_PASSWORD="$password"

    if [ "${ssl_verify:-true}" == 'false' ]; then
        bashio::log.warning 'Disabling SSL verification for git'
        export GIT_SSL_NO_VERIFY=true
    fi

    mkdir -p "$local_repository"
    cd "$local_repository"

    if [ ! -d .git ]; then
        if [ "$pull_before_push" == 'true' ]; then
            bashio::log.info 'Clone existing repository'
            git clone "$repository" "$local_repository"
        else
            bashio::log.info 'Initialize new repository'
            git init "$local_repository"
            git remote add origin "$repository"
        fi
    fi
    git remote set-url origin "$repository"
    git config user.name "${username}"
    git config user.email "${commiter_mail:-git.exporter@home-assistant}"

    # Reset secrets config if existing
    git config --unset-all 'secrets.allowed' || true
    git config --unset-all 'secrets.patterns' || true
    git config --unset-all 'secrets.providers' || true

    if [ "$pull_before_push" == 'true' ]; then
        bashio::log.info 'Pull latest'
        git fetch origin
        if git rev-parse --verify --quiet "origin/$branch" > /dev/null; then
            git checkout -B "$branch" "origin/$branch"
            git reset --hard "origin/$branch"
        else
            # Remote is empty or the branch does not exist yet: start it from here.
            bashio::log.info "Branch '$branch' does not exist on the remote yet, it will be created"
            git checkout -B "$branch"
        fi
    else
        git checkout -B "$branch"
    fi

    git clean -ffdx
}

function check_secrets {
    cd "$local_repository"
    bashio::log.info 'Add secrets pattern'

    # Allow !secret lines
    git secrets --add -a '!secret'

    # Set prohibited patterns
    local key
    for key in password token client_id api_key chat_id allowed_chat_ids latitude longitude credential_secret \
        client_secret access_token refresh_token private_key webhook_id; do
        git secrets --add "${key}\"?:[[:space:]]*['\"]?[^[:space:]'\"]+"
    done
    git secrets --add 'BEGIN [A-Z ]*PRIVATE KEY'

    if [ "$(bashio::config 'check.check_for_secrets')" == 'true' ] && [ -f /config/secrets.yaml ]; then
        # Provider output is matched as literal strings (one secret value per line).
        git secrets --add-provider -- /utils/secretValues.py /config/secrets.yaml
    fi

    if [ "$(bashio::config 'check.check_for_ips')" == 'true' ]; then
        git secrets --add '([0-9]{1,3}\.){3}[0-9]{1,3}'
        git secrets --add '([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})'

        # Allow dummy / general ips and mac
        git secrets --add -a --literal 'AA:BB:CC:DD:EE:FF'
        git secrets --add -a --literal '123.456.789.123'
        git secrets --add -a --literal '0.0.0.0'
    fi

    local custom
    while IFS= read -r custom; do
        [ -n "$custom" ] && git secrets --add "$custom"
    done < <(bashio::config 'secrets' | grep -v '^$' || true)

    while IFS= read -r custom; do
        [ -n "$custom" ] && git secrets --add -a "$custom"
    done < <(bashio::config 'allowed_secrets' | grep -v '^$' || true)

    bashio::log.info 'Checking all exported files for secrets'
    # Scan every file that would be committed, not only a few file types.
    if ! git ls-files -z --cached --others --exclude-standard | xargs -0 -r git secrets --scan; then
        bashio::log.error 'Found secrets in files! Fix them to be able to commit. See https://www.home-assistant.io/docs/configuration/secrets/'
        exit 1
    fi
}

function export_ha_config {
    bashio::log.info 'Get Home Assistant config'
    local pattern
    local -a args=()
    local -a user_excludes=() user_includes=()

    mapfile -t user_excludes < <(bashio::config 'exclude' | grep -v '^$' || true)
    mapfile -t user_includes < <(bashio::config 'include' | grep -v '^$' || true)

    # rsync uses the first matching rule: excludes first, then includes, then exclude the rest.
    for pattern in "${hard_excludes[@]}" "${user_excludes[@]}"; do
        args+=("--exclude=${pattern}")
    done
    args+=("--include=*/")
    for pattern in "${default_includes[@]}" "${user_includes[@]}"; do
        args+=("--include=${pattern}")
    done
    args+=("--exclude=*")

    rsync --archive --compress --delete --delete-excluded --checksum --prune-empty-dirs -q "${args[@]}" /config "${local_repository}"

    # Keep the key names of secrets.yaml, drop every value (and any multi-line values / comments)
    mkdir -p "${local_repository}/config"
    if [ -f /config/secrets.yaml ]; then
        sed -n 's/^\([A-Za-z0-9_.-]\{1,\}\):.*/\1: ""/p' /config/secrets.yaml > "${local_repository}/config/secrets.yaml"
    fi
    chmod -R u=rwX,go=rX "${local_repository}/config"
}

function export_lovelace {
    bashio::log.info 'Get Lovelace config yaml'
    mkdir -p "${local_repository}/lovelace" /tmp/lovelace
    find /config/.storage -name "lovelace*" -printf '%f\n' | xargs -r -I % cp /config/.storage/% /tmp/lovelace/%.json
    /utils/jsonToYaml.py '/tmp/lovelace/' 'data'
    rsync --archive --compress --delete --checksum --prune-empty-dirs -q --include='*.yaml' --exclude='*' /tmp/lovelace/ "${local_repository}/lovelace"
    chmod -R u=rwX,go=rX "${local_repository}/lovelace"
}

function export_esphome {
    bashio::log.info 'Get ESPHome configs'
    mkdir -p "${local_repository}/esphome"
    rsync --archive --compress --delete --checksum --prune-empty-dirs -q \
        --exclude='.esphome*' --include='*/' --include='.gitignore' --include='*.yaml' --include='*.disabled' --exclude='secrets.yaml' --exclude='*' \
        /config/esphome "${local_repository}"
    if [ -f /config/esphome/secrets.yaml ]; then
        sed -n 's/^\([A-Za-z0-9_.-]\{1,\}\):.*/\1: ""/p' /config/esphome/secrets.yaml > "${local_repository}/esphome/secrets.yaml"
    fi
    chmod -R u=rwX,go=rX "${local_repository}/esphome"
}

function export_addons {
    local addon
    mkdir -p "${local_repository}/addons" /tmp/addons
    for addon in $(bashio::addons.installed); do
        bashio::log.info "Get ${addon} configs"
        bashio::addon.options "$addon" > /tmp/tmp.json
        # Values of keys that look like credentials are always redacted
        /utils/jsonToYaml.py /tmp/tmp.json '' --redact
        mv /tmp/tmp.yaml "/tmp/addons/${addon}.yaml"
    done
    bashio::log.info "Get addon repositories"
    bashio::api.supervisor GET "/store/repositories" false \
        | jq '. | map(select(.source != null and .source != "core" and .source != "local")) | map({(.name): {source,maintainer,slug}}) | add' > /tmp/tmp.json
    /utils/jsonToYaml.py /tmp/tmp.json
    mv /tmp/tmp.yaml "/tmp/addons/repositories.yaml"
    rsync --archive --compress --delete --checksum --prune-empty-dirs -q /tmp/addons/ "${local_repository}/addons"
    chmod -R u=rwX,go=rX "${local_repository}/addons"
}

function export_node-red {
    bashio::log.info 'Get Node-RED flows'
    mkdir -p "${local_repository}/node-red"
    rsync --archive --compress --delete --checksum --prune-empty-dirs -q \
        --exclude='flows_cred.json' --exclude='*.backup' --include='flows.json' --include='settings.js' --exclude='*' \
        /config/node-red/ "${local_repository}/node-red"
    chmod -R u=rwX,go=rX "${local_repository}/node-red"
}

bashio::log.info 'Start git export'

setup_git

export_ha_config

if [ "$(bashio::config 'export.lovelace')" == 'true' ]; then
    export_lovelace
fi

if [ "$(bashio::config 'export.esphome')" == 'true' ] && [ -d '/config/esphome' ]; then
    export_esphome
fi

if [ "$(bashio::config 'export.addons')" == 'true' ]; then
    export_addons
fi

if [ "$(bashio::config 'export.node_red')" == 'true' ] && [ -d '/config/node-red' ]; then
    export_node-red
fi

cd "$local_repository"

if [ "$(bashio::config 'check.enabled')" == 'true' ]; then
    check_secrets
else
    bashio::log.warning 'Secret checks are disabled: everything exported will be committed unscanned'
fi

git add -A

if [ "$(bashio::config 'dry_run')" == 'true' ]; then
    bashio::log.info 'Dry run: showing changes only'
    git status
elif git diff --cached --quiet; then
    bashio::log.info 'No changes to commit'
else
    bashio::log.info 'Commit changes and push to remote'
    git commit -m "$(bashio::config 'repository.commit_message')"
    # Never force-push: if the remote has diverged this fails instead of overwriting history.
    git push --set-upstream origin "$branch"
fi

bashio::log.info 'Exporter finished'
