# shellcheck shell=sh
# Managed by unattended-installer.
#
# DevOps tooling is deliberately opt-in for ordinary terminals. Sourcing this
# fragment defines the environment and toggle functions only; it does not alter
# PATH or export DevOps state. `devops_de_apply_environment` is the authoritative
# noninteractive environment used when managed Codex CLI and ChatGPT/Codex
# desktop-app launches do not already inherit an active DevOps shell. An active
# shell is marked only after construction completes so Codex can preserve its
# exact exported values and PATH. The `devops` command starts a nested
# interactive shell in the current terminal and working directory. Exiting that
# shell, or running `devops` again from it, returns to the unchanged ordinary
# shell environment.

devops_de_prepend_path() {
  case "$#" in
    1) ;;
    *) return 64 ;;
  esac

  case "$1" in
    /*) ;;
    *) return 64 ;;
  esac
  case "$1" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./@+-]*)
      return 64
      ;;
  esac
  case "/$1/" in
    */./*|*/../*) return 64 ;;
  esac

  case ":${PATH:-}:" in
    *":$1:"*) ;;
    *) PATH="$1${PATH:+:${PATH}}" ;;
  esac
}

devops_de_append_path() {
  case "$#" in
    1) ;;
    *) return 64 ;;
  esac

  case "$1" in
    /*) ;;
    *) return 64 ;;
  esac
  case "$1" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./@+-]*)
      return 64
      ;;
  esac
  case "/$1/" in
    */./*|*/../*) return 64 ;;
  esac

  case ":${PATH:-}:" in
    *":$1:"*) ;;
    *) PATH="${PATH:+${PATH}:}$1" ;;
  esac
}

# Runtime filesystem validation. These helpers run in subshells so their
# scratch variables never leak into an interactive caller.
devops_de_account_owned_directory_is_mode() (
  case "$#" in
    2) ;;
    *) return 64 ;;
  esac

  devops_de_path_value=$1
  devops_de_path_mode=$2
  case "$devops_de_path_value" in
    /*) ;;
    *) return 1 ;;
  esac
  case "$devops_de_path_mode" in
    ''|*[!0-7]*) return 1 ;;
  esac

  [ -d "$devops_de_path_value" ] &&
    [ ! -L "$devops_de_path_value" ] &&
    [ -r "$devops_de_path_value" ] &&
    [ -w "$devops_de_path_value" ] &&
    [ -x "$devops_de_path_value" ] ||
    return 1

  devops_de_path_real=$(/usr/bin/readlink -f -- "$devops_de_path_value" 2>/dev/null) ||
    return 1
  [ "$devops_de_path_real" = "$devops_de_path_value" ] || return 1
  devops_de_path_owner=$(/usr/bin/stat -c '%u' -- "$devops_de_path_value" 2>/dev/null) ||
    return 1
  devops_de_path_actual_mode=$(/usr/bin/stat -c '%a' -- "$devops_de_path_value" 2>/dev/null) ||
    return 1
  devops_de_path_uid=$(/usr/bin/id -u 2>/dev/null) || return 1
  [ "$devops_de_path_owner" = "$devops_de_path_uid" ] &&
    [ "$devops_de_path_actual_mode" = "$devops_de_path_mode" ]
)

# This internal helper deliberately rejects all arguments.
# shellcheck disable=SC2120
devops_de_validate_runtime_directory() (
  case "$#" in
    0) ;;
    *) return 64 ;;
  esac

  devops_de_runtime_uid=$(/usr/bin/id -u 2>/dev/null) || {
    printf '%s\n' 'devops: cannot resolve the current account identifier' >&2
    return 1
  }
  case "$devops_de_runtime_uid" in
    ''|*[!0-9]*)
      printf '%s\n' 'devops: the current account identifier is malformed' >&2
      return 1
      ;;
  esac
  devops_de_expected_runtime_dir="/run/user/${devops_de_runtime_uid}"
  [ "${XDG_RUNTIME_DIR:-}" = "$devops_de_expected_runtime_dir" ] || {
    printf 'devops: XDG_RUNTIME_DIR must be %s\n' "$devops_de_expected_runtime_dir" >&2
    return 1
  }
  devops_de_account_owned_directory_is_mode "$XDG_RUNTIME_DIR" 700 || {
    printf '%s\n' 'devops: XDG_RUNTIME_DIR must be a direct account-owned mode-0700 directory' >&2
    return 1
  }
)

devops_de_ensure_private_runtime_directory() (
  case "$#" in
    1) ;;
    *) return 64 ;;
  esac

  devops_de_private_runtime_path=$1
  case "$devops_de_private_runtime_path" in
    /*) ;;
    *) return 64 ;;
  esac
  if [ ! -e "$devops_de_private_runtime_path" ] &&
     [ ! -L "$devops_de_private_runtime_path" ]; then
    (umask 077 && /usr/bin/mkdir -- "$devops_de_private_runtime_path") || return 1
    /usr/bin/chmod 00700 -- "$devops_de_private_runtime_path" || return 1
  fi
  devops_de_account_owned_directory_is_mode \
    "$devops_de_private_runtime_path" \
    700
)

# Interactive shell integration.
devops_de_push_terminal_title() {
  printf '\033[22;0t'
}

devops_de_set_terminal_title() {
  case "${DEVOPS_DE_ACTIVE:-}" in
    1) printf '\033]0;%s\007' '[devops]' ;;
  esac
}

devops_de_restore_terminal_title() {
  printf '\033[23;0t'
}

devops_de_enable_zsh_terminal_title() {
  case "${DEVOPS_DE_ACTIVE:-}:${ZSH_VERSION:-}" in
    1:?*) ;;
    *) return 0 ;;
  esac

  autoload -Uz add-zsh-hook || return 1
  add-zsh-hook -d precmd devops_de_set_terminal_title 2>/dev/null || true
  add-zsh-hook -d preexec devops_de_set_terminal_title 2>/dev/null || true
  add-zsh-hook precmd devops_de_set_terminal_title || return 1
  add-zsh-hook preexec devops_de_set_terminal_title || return 1
  devops_de_set_terminal_title
}

devops_de_enable_shell_completions() {
  case "${DEVOPS_DE_ACTIVE:-}:${DEVOPS_DE_COMPLETIONS_ENABLED:-}" in
    1:) ;;
    *) return 0 ;;
  esac

  case "${BASH_VERSION:-}:${ZSH_VERSION:-}" in
    ?*:|:?*) ;;
    *) return 0 ;;
  esac

  # The shell gate above leaves only Bash and Zsh, both of which provide
  # function-local variables through `local`.
  # shellcheck disable=SC3043
  local devops_de_ansible_completion

  case "${BASH_VERSION:-}:${ZSH_VERSION:-}" in
    ?*:)
      devops_de_ansible_completion=/usr/local/lib/ansible/share/bash-completion/completions/ansible
      ;;
    :?*)
      autoload -Uz bashcompinit || return 1
      bashcompinit || return 1
      devops_de_ansible_completion=/usr/local/lib/ansible/share/zsh/site-functions/_ansible-managed
      ;;
    *) return 0 ;;
  esac

  if [ -x /usr/local/lib/ansible/bin/ansible ]; then
    [ -r "$devops_de_ansible_completion" ] || return 1
    # shellcheck disable=SC1090
    . "$devops_de_ansible_completion" || return 1
  fi
  if [ -x /usr/local/lib/hashicorp/terraform/bin/terraform ]; then
    # Bash provides `complete` directly; Zsh provides it through bashcompinit above.
    # shellcheck disable=SC3044
    complete -o nospace \
      -C /usr/local/lib/hashicorp/terraform/bin/terraform \
      terraform || return 1
  fi
  if [ -x /usr/local/lib/hashicorp/packer/bin/packer ]; then
    # Bash provides `complete` directly; Zsh provides it through bashcompinit above.
    # shellcheck disable=SC3044
    complete -o nospace \
      -C /usr/local/lib/hashicorp/packer/bin/packer \
      packer || return 1
  fi

  DEVOPS_DE_COMPLETIONS_ENABLED=1
}

devops_de_deactivate() {
  case "${DEVOPS_DE_ACTIVE:-}" in
    1)
      printf '%s\n' 'DevOps environment deactivated'
      exit 0
      ;;
    *)
      printf '%s\n' 'devops: no DevOps environment is active' >&2
      return 1
      ;;
  esac
}

devops_de_environment_is_active() {
  case "$#" in
    0) ;;
    *) return 64 ;;
  esac

  [ "${DEVOPS_DE_ACTIVE:-}" = 1 ] &&
    [ "${DEVOPS_DE_ENVIRONMENT_READY:-}" = 1 ] &&
    [ -n "${PATH:-}" ]
}

# Managed environment construction.
# This public shell helper deliberately rejects all arguments.
# shellcheck disable=SC2120
devops_de_apply_environment() {
  case "$#" in
    0) ;;
    *)
      printf '%s\n' 'devops: devops_de_apply_environment accepts no arguments' >&2
      return 64
      ;;
  esac
  case "${USER:-}" in
    ''|.|..|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.@-]*)
      printf '%s\n' 'devops: the current account name is unsafe for managed paths' >&2
      return 1
      ;;
  esac
  case "${HOME:-}" in
    /*) ;;
    *)
      printf '%s\n' 'devops: HOME must be an absolute path' >&2
      return 1
      ;;
  esac
  devops_de_validate_runtime_directory || return 1

  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  export PATH
  unset \
    XDG_CONFIG_HOME \
    DEVOPS_DE_ACTIVE \
    DEVOPS_DE_ENVIRONMENT_READY \
    DEVOPS_DE_COMPLETIONS_ENABLED \
    DEVOPS_DE_MISE_ENABLED \
    DEVOPS_DE_BAZELISK_ENABLED \
    CARGO_HOME \
    CARGO_TARGET_DIR \
    CARGO_INSTALL_ROOT \
    RUSTUP_HOME \
    RUSTUP_TOOLCHAIN \
    SCCACHE_DIR \
    RUSTC_WRAPPER \
    CMAKE_C_COMPILER_LAUNCHER \
    CMAKE_CXX_COMPILER_LAUNCHER \
    MISE_CONFIG_DIR \
    MISE_DATA_DIR \
    MISE_STATE_DIR \
    MISE_CACHE_DIR \
    MISE_TMP_DIR \
    NPM_CONFIG_CACHE \
    NPM_CONFIG_PREFIX \
    COREPACK_HOME \
    NODE_REPL_HISTORY \
    DENO_DIR \
    DENO_INSTALL_ROOT \
    DENO_REPL_HISTORY \
    DENO_NO_UPDATE_CHECK \
    PNPM_HOME \
    PNPM_CONFIG_STORE_DIR \
    PNPM_CONFIG_CACHE_DIR \
    PNPM_CONFIG_STATE_DIR \
    PNPM_CONFIG_GLOBAL_DIR \
    PNPM_CONFIG_GLOBAL_BIN_DIR \
    YARN_CACHE_FOLDER \
    YARN_GLOBAL_FOLDER \
    YARN_ENABLE_GLOBAL_CACHE \
    PYTHONDONTWRITEBYTECODE \
    PYTHONHASHSEED \
    PYTHONHOME \
    PYTHONINSPECT \
    PYTHONOPTIMIZE \
    PYTHONPATH \
    PYTHONPYCACHEPREFIX \
    PYTHONSTARTUP \
    PYTHONUSERBASE \
    PYTHON_HISTORY \
    PYTHONSAFEPATH \
    PYTHONUTF8 \
    PYTHONWARNINGS \
    PYTHONWARNDEFAULTENCODING \
    PIP_CACHE_DIR \
    PIP_DISABLE_PIP_VERSION_CHECK \
    UV_CACHE_DIR \
    UV_TOOL_DIR \
    UV_TOOL_BIN_DIR \
    VIRTUAL_ENV \
    VIRTUAL_ENV_PROMPT \
    GOPATH \
    GOMODCACHE \
    ANSIBLE_HOME \
    ANSIBLE_GALAXY_CACHE_DIR \
    ANSIBLE_LOCAL_TEMP \
    ANSIBLE_NOCOWS \
    ANSIBLE_PERSISTENT_CONTROL_PATH_DIR \
    ANSIBLE_RETRY_FILES_ENABLED \
    ANSIBLE_SSH_CONTROL_PATH_DIR \
    CHECKPOINT_DISABLE \
    PACKER_CACHE_DIR \
    PACKER_CONFIG \
    PACKER_CONFIG_DIR \
    PACKER_CONFIG_PATH \
    PACKER_GETTER_READ_TIMEOUT \
    PACKER_PLUGIN_PATH \
    TF_PLUGIN_CACHE_DIR \
    TF_REGISTRY_CLIENT_TIMEOUT \
    TF_REGISTRY_DISCOVERY_RETRY \
    BAZELISK_HOME \
    CODEX_AGENTS \
    CODEX_HOME \
    CODEX_LOG_DIR \
    CODEX_SKILLS \
    CODEX_SQLITE_HOME \
    DEVOPS_DATABASE_HOME \
    PGDATA \
    PGSERVICEFILE \
    PGPASSFILE \
    PSQL_HISTORY \
    MYSQL_HOME \
    MYSQL_HISTFILE \
    MYSQLSH_USER_CONFIG_HOME \
    SQLITE_HISTORY \
    DUCKDB_HISTORY \
    REDISCLI_HISTFILE \
    USQL_CONFIG_FILE \
    QOREDB_CONFIG_DIR

  devops_de_pool_root=/pool
  devops_de_build_home="${devops_de_pool_root}/build/${USER}"
  devops_de_cache_home="${devops_de_pool_root}/cache/${USER}"
  devops_de_db_home="${devops_de_pool_root}/db/${USER}"
  XDG_CONFIG_HOME="${HOME}/.config"
  export XDG_CONFIG_HOME
  devops_de_xdg_config_home=$XDG_CONFIG_HOME

  for devops_de_account_root in \
    "$devops_de_build_home" \
    "$devops_de_cache_home" \
    "$devops_de_db_home"
  do
    devops_de_account_owned_directory_is_mode "$devops_de_account_root" 2770 || {
      printf 'devops: account work root must be a direct account-owned writable mode-2770 directory: %s\n' \
        "$devops_de_account_root" >&2
      return 1
    }
  done
  for devops_de_private_database_dir in \
    "$devops_de_db_home/postgresql" \
    "$devops_de_db_home/postgresql/data" \
    "$devops_de_db_home/mysql" \
    "$devops_de_db_home/mysql/config" \
    "$devops_de_db_home/mysql-shell" \
    "$devops_de_db_home/sqlite" \
    "$devops_de_db_home/duckdb" \
    "$devops_de_db_home/redis-compatible" \
    "$devops_de_db_home/usql" \
    "$devops_de_db_home/qoredb" \
    "$devops_de_db_home/qoredb/config"
  do
    devops_de_ensure_private_runtime_directory "$devops_de_private_database_dir" || {
      printf 'devops: cannot create or validate private database directory: %s\n' \
        "$devops_de_private_database_dir" >&2
      return 1
    }
  done

  # Native database-client selectors keep histories, credentials, service
  # definitions, and database state below the account-scoped /pool root.
  export DEVOPS_DATABASE_HOME="$devops_de_db_home"
  export PGDATA="$devops_de_db_home/postgresql/data"
  export PGSERVICEFILE="$devops_de_db_home/postgresql/pg_service.conf"
  export PGPASSFILE="$devops_de_db_home/postgresql/pgpass"
  export PSQL_HISTORY="$devops_de_db_home/postgresql/psql_history"
  export MYSQL_HOME="$devops_de_db_home/mysql/config"
  export MYSQL_HISTFILE="$devops_de_db_home/mysql/history"
  export MYSQLSH_USER_CONFIG_HOME="$devops_de_db_home/mysql-shell"
  export SQLITE_HISTORY="$devops_de_db_home/sqlite/history"
  export DUCKDB_HISTORY="$devops_de_db_home/duckdb/history"
  export REDISCLI_HISTFILE="$devops_de_db_home/redis-compatible/history"
  export QOREDB_CONFIG_DIR="$devops_de_db_home/qoredb/config"
  # usql consumes --config rather than a native environment selector.
  export USQL_CONFIG_FILE="$devops_de_db_home/usql/config.yaml"

  # Keep Python bytecode ephemeral and isolated below the validated account
  # runtime directory. Persistent interpreter history, user installs, pip
  # downloads, and uv state remain on the account-scoped /pool roots. Clear
  # inherited Python and virtual-environment selectors above before rebuilding
  # this deterministic environment.
  devops_de_python_runtime_root="${XDG_RUNTIME_DIR}/python"
  for devops_de_private_runtime_dir in \
    "$devops_de_python_runtime_root" \
    "$devops_de_python_runtime_root/pycache"
  do
    devops_de_ensure_private_runtime_directory "$devops_de_private_runtime_dir" || {
      printf 'devops: cannot create or validate private Python runtime directory: %s\n' \
        "$devops_de_private_runtime_dir" >&2
      return 1
    }
  done

  export PYTHONPYCACHEPREFIX="${devops_de_python_runtime_root}/pycache"
  export PYTHONUSERBASE="${devops_de_build_home}/python"
  export PYTHON_HISTORY="${devops_de_db_home}/python/history"
  export PYTHONSAFEPATH=1
  export PYTHONUTF8=1
  export PYTHONWARNDEFAULTENCODING=1
  export PIP_CACHE_DIR="${devops_de_cache_home}/pip"
  export PIP_DISABLE_PIP_VERSION_CHECK=1
  export UV_CACHE_DIR="${devops_de_cache_home}/uv"
  export UV_TOOL_DIR="${devops_de_db_home}/uv/tools"
  export UV_TOOL_BIN_DIR="${devops_de_build_home}/uv/bin"
  devops_de_prepend_path "${PYTHONUSERBASE}/bin" || return 1
  devops_de_prepend_path "${UV_TOOL_BIN_DIR}" || return 1

  # Keep Ansible local temporary files and persistent control sockets inside
  # the authenticated account's private runtime directory. Persistent Ansible
  # state and Galaxy downloads use their account-scoped /pool roots.
  devops_de_ansible_runtime_root="${XDG_RUNTIME_DIR}/ansible"
  for devops_de_private_runtime_dir in \
    "$devops_de_ansible_runtime_root" \
    "$devops_de_ansible_runtime_root/tmp" \
    "$devops_de_ansible_runtime_root/pc" \
    "$devops_de_ansible_runtime_root/ssh"
  do
    devops_de_ensure_private_runtime_directory "$devops_de_private_runtime_dir" || {
      printf '%s\n' 'devops: cannot create or validate a private Ansible runtime directory' >&2
      return 1
    }
  done
  export ANSIBLE_HOME="${devops_de_db_home}/ansible"
  export ANSIBLE_GALAXY_CACHE_DIR="${devops_de_cache_home}/ansible/galaxy"
  export ANSIBLE_LOCAL_TEMP="${devops_de_ansible_runtime_root}/tmp"
  export ANSIBLE_PERSISTENT_CONTROL_PATH_DIR="${devops_de_ansible_runtime_root}/pc"
  export ANSIBLE_SSH_CONTROL_PATH_DIR="${devops_de_ansible_runtime_root}/ssh"
  export ANSIBLE_NOCOWS=1
  export ANSIBLE_RETRY_FILES_ENABLED=0

  # HashiCorp release binaries remain isolated from ordinary terminals. Packer
  # uses PACKER_CONFIG; PACKER_CONFIG_PATH is a managed path alias retained for
  # operator scripts because upstream does not consume that name directly.
  devops_de_hashicorp_cache_root="${devops_de_cache_home}/hashicorp"
  export CHECKPOINT_DISABLE=1
  export TF_PLUGIN_CACHE_DIR="${devops_de_hashicorp_cache_root}/terraform/plugin-cache"
  export TF_REGISTRY_CLIENT_TIMEOUT=30
  export TF_REGISTRY_DISCOVERY_RETRY=3
  export PACKER_CACHE_DIR="${devops_de_hashicorp_cache_root}/packer/cache"
  export PACKER_CONFIG_DIR="${devops_de_hashicorp_cache_root}/packer.d"
  export PACKER_CONFIG_PATH="${PACKER_CONFIG_DIR}/config.json"
  export PACKER_CONFIG="$PACKER_CONFIG_PATH"
  export PACKER_PLUGIN_PATH="${PACKER_CONFIG_DIR}/plugins"
  export PACKER_GETTER_READ_TIMEOUT=30m

  # Keep Go workspaces and downloaded modules on the account-scoped /pool
  # roots. Managed publication wrappers are prepended below and therefore
  # cannot be shadowed by a binary installed into GOPATH/bin.
  export GOPATH="${devops_de_build_home}/go"
  export GOMODCACHE="${devops_de_cache_home}/go-mod"
  devops_de_prepend_path "${GOPATH}/bin" || return 1

  # Expose only the class-gated publication command entrypoints.
  if [ -d /usr/local/libexec/obs-publishing-bin ]; then
    devops_de_prepend_path /usr/local/libexec/obs-publishing-bin || return 1
  fi
  if [ -d /usr/local/libexec/aptly-publishing-bin ]; then
    devops_de_prepend_path /usr/local/libexec/aptly-publishing-bin || return 1
  fi

  # Keep the isolated upstream tool roots visible only in the opt-in DevOps
  # shell. Aptly and osc remain behind their prepended credential-aware
  # publication wrappers, while their direct binaries stay available by path.
  if [ -d /usr/local/lib/opentufo/bin ]; then
    devops_de_append_path /usr/local/lib/opentufo/bin || return 1
  fi
  if [ -d /usr/local/lib/ansible/bin ]; then
    devops_de_append_path /usr/local/lib/ansible/bin || return 1
  fi
  if [ -x /usr/local/lib/deno/bin/deno ]; then
    export DENO_DIR="${devops_de_cache_home}/deno"
    export DENO_INSTALL_ROOT="${devops_de_build_home}/deno"
    export DENO_REPL_HISTORY="${devops_de_db_home}/deno/repl_history"
    export DENO_NO_UPDATE_CHECK=1
    devops_de_append_path /usr/local/lib/deno/bin || return 1
    devops_de_append_path "${DENO_INSTALL_ROOT}/bin" || return 1
  fi
  if [ -x /usr/local/lib/yt-dlp/bin/yt-dlp ]; then
    # The checksum-pinned official standalone payload bundles yt-dlp-ejs; its
    # wrapper binds that component to the managed Deno runtime and system ffmpeg.
    devops_de_append_path /usr/local/lib/yt-dlp/bin || return 1
  fi
  if [ -d /usr/local/lib/hashicorp/terraform/bin ]; then
    devops_de_append_path /usr/local/lib/hashicorp/terraform/bin || return 1
  fi
  if [ -d /usr/local/lib/hashicorp/packer/bin ]; then
    devops_de_append_path /usr/local/lib/hashicorp/packer/bin || return 1
  fi
  if [ -d /usr/local/lib/wrangler/node_modules/.bin ]; then
    devops_de_append_path /usr/local/lib/wrangler/node_modules/.bin || return 1
  fi
  if [ -d /usr/local/lib/aptly/bin ]; then
    devops_de_append_path /usr/local/lib/aptly/bin || return 1
  fi
  if [ -d /usr/local/lib/osc/bin ]; then
    devops_de_append_path /usr/local/lib/osc/bin || return 1
  fi
  if [ -d /usr/local/lib/obs-build/bin ]; then
    devops_de_append_path /usr/local/lib/obs-build/bin || return 1
  fi

  if [ -x /usr/local/lib/rustup/bin/rustup-init ]; then
    export CARGO_HOME="${devops_de_cache_home}/cargo"
    export CARGO_TARGET_DIR="${devops_de_build_home}/cargo/target"
    export CARGO_INSTALL_ROOT="${devops_de_build_home}/cargo/install"
    export RUSTUP_HOME="${devops_de_db_home}/rustup"
    RUSTUP_TOOLCHAIN=nightly
    export RUSTUP_TOOLCHAIN
    devops_de_prepend_path "${CARGO_HOME}/bin" || return 1
    devops_de_prepend_path "${CARGO_INSTALL_ROOT}/bin" || return 1
    devops_de_prepend_path /usr/local/lib/rustup/bin || return 1
  fi

  if command -v sccache >/dev/null 2>&1; then
    export SCCACHE_DIR="${devops_de_cache_home}/sccache"
    export RUSTC_WRAPPER=sccache
    export CMAKE_C_COMPILER_LAUNCHER=sccache
    export CMAKE_CXX_COMPILER_LAUNCHER=sccache
  fi

  if [ -x /usr/local/lib/node-26/bin/node ]; then
    # Keep Node 26 ahead of any distribution Node binary as the fallback.
    # Mise's standard shim directory is prepended below and therefore wins
    # whenever the user selects a project or shell-specific Node version.
    devops_de_prepend_path /usr/local/lib/node-26/bin || return 1
  fi

  if command -v mise >/dev/null 2>&1; then
    export MISE_CONFIG_DIR="${devops_de_xdg_config_home}/mise"
    export MISE_DATA_DIR="${devops_de_db_home}/mise/data"
    export MISE_STATE_DIR="${devops_de_db_home}/mise/state"
    export MISE_CACHE_DIR="${devops_de_cache_home}/mise"
    export MISE_TMP_DIR="${devops_de_cache_home}/mise/tmp"

    export NPM_CONFIG_CACHE="${devops_de_cache_home}/npm"
    export NPM_CONFIG_PREFIX="${devops_de_build_home}/npm-global"
    export COREPACK_HOME="${devops_de_cache_home}/corepack"
    export NODE_REPL_HISTORY="${devops_de_db_home}/node/repl_history"
    export PNPM_HOME="${devops_de_build_home}/pnpm"
    export PNPM_CONFIG_STORE_DIR="${devops_de_cache_home}/pnpm/store"
    export PNPM_CONFIG_CACHE_DIR="${devops_de_cache_home}/pnpm/cache"
    export PNPM_CONFIG_STATE_DIR="${devops_de_db_home}/pnpm/state"
    export PNPM_CONFIG_GLOBAL_DIR="${PNPM_HOME}/global"
    export PNPM_CONFIG_GLOBAL_BIN_DIR="${PNPM_HOME}/bin"
    export YARN_CACHE_FOLDER="${devops_de_cache_home}/yarn"
    export YARN_GLOBAL_FOLDER="${devops_de_build_home}/yarn-global"
    export YARN_ENABLE_GLOBAL_CACHE=false
    # This marker is intentionally exported to the exec'ed child shell.
    # shellcheck disable=SC2030
    DEVOPS_DE_MISE_ENABLED=1
    export DEVOPS_DE_MISE_ENABLED
    devops_de_prepend_path "${NPM_CONFIG_PREFIX}/bin" || return 1
    devops_de_prepend_path "${PNPM_HOME}/bin" || return 1
    devops_de_prepend_path "${YARN_GLOBAL_FOLDER}/bin" || return 1
    devops_de_prepend_path "${MISE_DATA_DIR}/shims" || return 1
  fi

  if [ -x /usr/lib/llvm-24/bin/clang ] &&
     [ -x /usr/lib/llvm-24/bin/clang++ ] &&
     [ -x /usr/lib/llvm-24/bin/llvm-config ] &&
     [ -x /usr/lib/llvm-24/bin/lld ] &&
     [ -x /usr/lib/llvm-24/bin/ld.lld ] &&
     [ -x /usr/lib/llvm-24/bin/lldb ]; then
    devops_de_prepend_path /usr/lib/llvm-24/bin || return 1
  fi

  # The CUDA classes install versioned toolkits below /usr/local. Add only
  # installed toolkit paths, oldest first, because each successful prepend
  # moves the newer toolkit ahead of the older one in the final PATH.
  if [ -d /usr/local/cuda-12.8/bin ]; then
    devops_de_prepend_path /usr/local/cuda-12.8/bin || return 1
  fi
  if [ -d /usr/local/cuda-12.9/bin ]; then
    devops_de_prepend_path /usr/local/cuda-12.9/bin || return 1
  fi
  if [ -d /usr/local/cuda-13.1/bin ]; then
    devops_de_prepend_path /usr/local/cuda-13.1/bin || return 1
  fi

  if [ -x /usr/local/lib/bazelisk/bazel ]; then
    export BAZELISK_HOME="${devops_de_db_home}/bazelisk"
    # This marker is intentionally exported to the exec'ed child shell.
    # shellcheck disable=SC2030
    DEVOPS_DE_BAZELISK_ENABLED=1
    export DEVOPS_DE_BAZELISK_ENABLED
  fi

  export CODEX_AGENTS="/data/codex/usr/agents"
  export CODEX_HOME="/data/codex/usr/home"
  export CODEX_LOG_DIR="/data/codex/log"
  export CODEX_SKILLS="/data/codex/usr/skills"
  export CODEX_SQLITE_HOME="/data/codex/sqlite"
  # Keep only the sandboxing wrapper on the host PATH. The wrapper injects the
  # checksum-pinned release directory into the confined Codex runtime PATH.
  devops_de_append_path /data/codex/lib || return 1

  if [ -x /data/llama/lib/llama ]; then
    devops_de_append_path /data/llama/lib || return 1
  fi
  if [ -d /data/llama/bin ]; then
    devops_de_append_path /data/llama/bin || return 1
  fi

  # Mark the environment active only after every managed variable and PATH
  # entry has been constructed successfully. Codex uses the ready marker to
  # preserve this exact interactive DevOps environment instead of rebuilding
  # and overwriting it in its wrapper process.
  DEVOPS_DE_ACTIVE=1
  DEVOPS_DE_ENVIRONMENT_READY=1
  export DEVOPS_DE_ACTIVE DEVOPS_DE_ENVIRONMENT_READY PATH
  unset \
    devops_de_pool_root \
    devops_de_build_home \
    devops_de_cache_home \
    devops_de_db_home \
    devops_de_account_root \
    devops_de_ansible_runtime_root \
    devops_de_hashicorp_cache_root \
    devops_de_private_database_dir \
    devops_de_private_runtime_dir \
    devops_de_python_runtime_root \
    devops_de_xdg_config_home
  return 0
}

# Same-terminal nested-shell activation.
devops_de_activate() (
  if [ ! -t 0 ] || [ ! -t 1 ]; then
    printf '%s\n' 'devops: an interactive terminal is required' >&2
    return 1
  fi

  # This function executes in a subshell. Environment construction and the
  # nested interactive shell therefore cannot modify the ordinary caller.
  devops_de_apply_environment || return 1

  case "${SHELL:-}" in
    /bin/bash|/usr/bin/bash|/bin/zsh|/usr/bin/zsh)
      devops_de_shell=$SHELL
      ;;
    *)
      devops_de_shell=/bin/bash
      ;;
  esac
  if [ ! -x "$devops_de_shell" ]; then
    printf '%s\n' 'devops: no supported interactive shell is available' >&2
    return 1
  fi

  # Revalidate immediately before entering the nested shell so a malformed or
  # replaced runtime directory cannot be used after environment construction.
  devops_de_validate_runtime_directory || return 1

  # Foot, Kitty, and xterm-compatible fallbacks implement the xterm title
  # stack. Restore the caller's exact title when the nested shell ends instead
  # of guessing an ordinary-shell title.
  devops_de_title_pushed=0
  devops_de_restore_terminal_title_once() {
    case "${devops_de_title_pushed:-0}" in
      1)
        devops_de_title_pushed=0
        devops_de_restore_terminal_title
        ;;
      *) return 0 ;;
    esac
  }
  trap 'devops_de_restore_terminal_title_once' 0

  devops_de_push_terminal_title || return 1
  devops_de_title_pushed=1
  devops_de_set_terminal_title || return 1
  printf '%s\n' 'Entering DevOps environment; run devops or exit to return'

  "$devops_de_shell" -i
  devops_de_shell_status=$?
  devops_de_restore_terminal_title_once || {
    [ "$devops_de_shell_status" -ne 0 ] || devops_de_shell_status=1
  }
  trap - 0
  return "$devops_de_shell_status"
)

# Public interactive command.
devops() {
  case "$#" in
    0) ;;
    *)
      printf '%s\n' 'usage: devops' >&2
      return 64
      ;;
  esac

  # The active marker is inherited only by the nested shell started above.
  # shellcheck disable=SC2031
  case "${DEVOPS_DE_ACTIVE:-}" in
    1) devops_de_deactivate ;;
    '') devops_de_activate ;;
    *)
      printf '%s\n' 'devops: invalid DevOps activation marker' >&2
      return 1
      ;;
  esac
}

# Active-shell command shims.
# The marker comes from the parent process that execs this interactive shell.
# shellcheck disable=SC2031
case "${DEVOPS_DE_BAZELISK_ENABLED:-}" in
  1)
    bazel() {
      command /usr/local/lib/bazelisk/bazel \
        "--bazelrc=${XDG_CONFIG_HOME:-${HOME}/.config}/bazel/bazelrc" \
        "$@"
    }
    ;;
esac

devops_de_enable_zsh_terminal_title
