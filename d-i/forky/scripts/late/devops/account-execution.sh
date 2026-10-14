#!/bin/sh
# Sourced installer module; edit this file directly.

devops_run_as_account() {
  run_label=$1
  shift
  devops_validate_account_name "$ACCOUNT_USERNAME"
  case "${account_ids%%:*}" in
    ''|0|*[!0-9]*) devops_fatal "tool execution requires a non-root target UID" ;;
  esac
  case "$ACCOUNT_HOME" in
    /root|/root/*) devops_fatal "tool execution must not use root's home" ;;
  esac

  run_in_target \
    "$run_label" \
    /usr/sbin/runuser \
      -u "$ACCOUNT_USERNAME" \
      -- \
      /usr/bin/env -i \
        HOME="$ACCOUNT_HOME" \
        USER="$ACCOUNT_USERNAME" \
        LOGNAME="$ACCOUNT_USERNAME" \
        PATH="${CARGO_INSTALL_ROOT}/bin:${CARGO_HOME}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        XDG_CONFIG_HOME="${ACCOUNT_HOME}/.config" \
        XDG_CACHE_HOME="${ACCOUNT_HOME}/.cache" \
        XDG_DATA_HOME="${ACCOUNT_HOME}/.local/share" \
        XDG_STATE_HOME="${ACCOUNT_HOME}/.local/state" \
        CODEX_HOME="$DEVOPS_CODEX_HOME" \
        CARGO_HOME="$CARGO_HOME" \
        CARGO_TARGET_DIR="$CARGO_TARGET_DIR" \
        CARGO_INSTALL_ROOT="$CARGO_INSTALL_ROOT" \
        RUSTUP_HOME="$RUSTUP_HOME" \
        RUSTUP_TOOLCHAIN="$DEVOPS_RUSTUP_TOOLCHAIN" \
        SCCACHE_DIR="$SCCACHE_DIR" \
        GOPATH="$GOPATH" \
        GOBIN="${GOPATH}/bin" \
        GOMODCACHE="$GOMODCACHE" \
        GOCACHE="$GOCACHE" \
        GOENV="$GOENV" \
        GOTMPDIR="$GOTMPDIR" \
        GOTOOLCHAIN=local \
        MISE_CONFIG_DIR="${ACCOUNT_HOME}/.config/mise" \
        MISE_DATA_DIR="$MISE_DATA_DIR" \
        MISE_STATE_DIR="$MISE_STATE_DIR" \
        MISE_CACHE_DIR="$MISE_CACHE_DIR" \
        MISE_TMP_DIR="$MISE_TMP_DIR" \
        BAZELISK_HOME="$BAZELISK_HOME" \
        ANSIBLE_HOME="$ANSIBLE_HOME" \
        ANSIBLE_GALAXY_CACHE_DIR="$ANSIBLE_GALAXY_CACHE_DIR" \
        CHECKPOINT_DISABLE=1 \
        PACKER_CACHE_DIR="$PACKER_CACHE_DIR" \
        PACKER_CONFIG="$PACKER_CONFIG_PATH" \
        PACKER_CONFIG_DIR="$PACKER_CONFIG_DIR" \
        PACKER_CONFIG_PATH="$PACKER_CONFIG_PATH" \
        PACKER_PLUGIN_PATH="$PACKER_PLUGIN_PATH" \
        TF_PLUGIN_CACHE_DIR="$TF_PLUGIN_CACHE_DIR" \
        "$@"
}

