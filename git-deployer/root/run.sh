#!/usr/bin/env bashio
set -eo pipefail

export DEPLOY_REPO_URL="$(bashio::config 'repository.url')"
export DEPLOY_USERNAME="$(bashio::config 'repository.username')"
export DEPLOY_PASSWORD="$(bashio::config 'repository.password')"
export DEPLOY_BRANCH="$(bashio::config 'repository.branch')"
export DEPLOY_DRY_RUN="$(bashio::config 'dry_run')"
export DEPLOY_POLL_INTERVAL="$(bashio::config 'poll_interval')"
export DEPLOY_RELOAD="$(bashio::config 'reload')"
export DEPLOY_KEEP_BACKUPS="$(bashio::config 'keep_backups')"
export DEPLOY_CONFIGURATION="$(bashio::config 'deploy_configuration')"

exec python3 /deploy.py
