"""Declarative managed-application and sandbox profile policy."""

from __future__ import annotations

from .browsers import browser_args
from .electron import electron_args, electron_js_flags, electron_privacy_args

INTEL_ACCELERATION_ENV = {
    "DRI_PRIME": "0",
    "LIBVA_DRIVER_NAME": "iHD",
}
NVIDIA_ACCELERATION_ENV = {
    "GBM_BACKEND": "nvidia-drm",
    "LIBVA_DRIVER_NAME": "nvidia",
    "NVD_BACKEND": "direct",
    "__GLX_VENDOR_LIBRARY_NAME": "nvidia",
    "__NV_PRIME_RENDER_OFFLOAD": "1",
}
TUTA_DBUS_NAMES = (
    "org.freedesktop.secrets",
)
DISCORD_SESSION_DBUS_NAMES = (
    "com.canonical.AppMenu.Registrar",
    "com.canonical.Unity",
    "com.canonical.indicator.application",
    "org.freedesktop.ScreenSaver",
    "org.freedesktop.secrets",
    "org.kde.StatusNotifierWatcher",
)
ZOOM_SESSION_DBUS_NAMES = (
    "org.freedesktop.ScreenSaver",
)
ZOOM_SESSION_DBUS_OWN_NAMES = (
    "org.kde.*",
)
CHATGPT_SESSION_DBUS_NAMES = (
    "org.freedesktop.secrets",
)
CHATGPT_SYSTEM_DBUS_NAMES = (
    "org.freedesktop.UPower",
)
TUTA_SYSTEM_DBUS_NAMES = (
    "org.freedesktop.UPower",
)
DISCORD_ROOT = "/opt/discord"
DISCORD_MODULES_ROOT = f"{DISCORD_ROOT}/modules"
DISCORD_RELEASE_FILE = f"{DISCORD_ROOT}/.managed-release"
DISCORD_MODULES_FILE = f"{DISCORD_MODULES_ROOT}/installed.json"
DISCORD_STATE_FILE = "/var/lib/software/state/discord.installed.json"
DISCORD_EXECUTABLE_FILES = (
    f"{DISCORD_ROOT}/Discord",
    f"{DISCORD_ROOT}/chrome-sandbox",
    f"{DISCORD_ROOT}/chrome_crashpad_handler",
)
DISCORD_REQUIRED_MODULES = (
    "discord_desktop_core",
    "discord_erlpack",
    "discord_spellcheck",
    "discord_utils",
    "discord_voice",
)
DISCORD_REQUIRED_FILES = (
    *DISCORD_EXECUTABLE_FILES,
    f"{DISCORD_ROOT}/discord.png",
    f"{DISCORD_ROOT}/libffmpeg.so",
    DISCORD_RELEASE_FILE,
)
WAYLAND_COMPAT_APPS = ("discord", "zoom")
WAYLAND_COMPAT_RUNTIME_ROOT = "/opt/xwayland"


APPS = {
    "chromium": {
        "exec": "/usr/bin/chromium",
        "env": {},
        "args": browser_args("chromium", "launch"),
        "intel_env": {},
        "intel_args": browser_args("chromium", "intel"),
        "nvidia_env": {},
        "nvidia_args": browser_args("chromium", "nvidia"),
        "bind_workspace": False,
        "pure_privacy": True,
    },
    "microsoft-edge": {
        "exec": "/usr/bin/microsoft-edge-stable",
        "env": {},
        "args": browser_args("microsoft-edge", "launch"),
        "intel_env": {},
        "intel_args": browser_args("microsoft-edge", "intel"),
        "nvidia_env": {},
        "nvidia_args": browser_args("microsoft-edge", "nvidia"),
        "bind_workspace": False,
        "pure_privacy": True,
    },
    "vivaldi": {
        "exec": "/usr/bin/vivaldi-stable",
        "env": {
            "VIVALDI_FFMPEG_AUTO": "0",
        },
        "args": browser_args("vivaldi", "launch"),
        "intel_env": {},
        "intel_args": browser_args("vivaldi", "intel"),
        "nvidia_env": {},
        "nvidia_args": browser_args("vivaldi", "nvidia"),
        "bind_workspace": False,
        "pure_privacy": True,
    },
    "code": {
        "exec": "/usr/bin/code",
        "library_dirs": ("/usr/share/code",),
        "required_runtime_files": ("/usr/share/code/libffmpeg.so",),
        "env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
        },
        "args": electron_args("code", "launch"),
        "intel_env": {},
        "intel_args": electron_args("code", "intel"),
        "nvidia_env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
        },
        "nvidia_args": electron_args("code", "nvidia"),
        "privacy_args": electron_privacy_args("code"),
        "bind_workspace": True,
        "pure_privacy": True,
    },
    "mullvad-browser": {
        "exec": "/usr/bin/mullvad-browser",
        "env": {
            "MOZ_ENABLE_WAYLAND": "1",
        },
        "args": [],
        "intel_env": {
            "LIBVA_DRIVER_NAME": "iHD",
            "MOZ_WEBRENDER": "1",
        },
        "intel_args": [],
        "nvidia_env": {
            "MOZ_DISABLE_RDD_SANDBOX": "1",
            "MOZ_ENABLE_WAYLAND": "1",
            "MOZ_WEBRENDER": "1",
        },
        "nvidia_args": [],
        "bind_workspace": False,
        "pure_privacy": True,
    },
    "bitwarden": {
        "exec": "/opt/Bitwarden/bitwarden",
        "library_dirs": ("/opt/Bitwarden",),
        "required_runtime_files": ("/opt/Bitwarden/libffmpeg.so",),
        "env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
        },
        "args": electron_args("bitwarden", "launch"),
        "intel_env": {},
        "intel_args": electron_args("bitwarden", "intel"),
        "nvidia_env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
        },
        "nvidia_args": electron_args("bitwarden", "nvidia"),
        "privacy_args": electron_privacy_args("bitwarden"),
        "bind_workspace": False,
        "pure_privacy": True,
    },
    "chatgpt": {
        "exec": "/usr/lib/chatgpt/ChatGPT",
        "library_dirs": ("/usr/lib/chatgpt",),
        "required_runtime_files": (
            "/usr/lib/chatgpt/codex-launcher",
            "/usr/lib/chatgpt/resources/codex",
            "/usr/lib/chatgpt/resources/codex-code-mode-host",
        ),
        "env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "args": electron_args("chatgpt", "launch"),
        "intel_env": {},
        "intel_args": electron_args("chatgpt", "intel"),
        "nvidia_env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": electron_args("chatgpt", "nvidia"),
        "bind_workspace": True,
        "pure_privacy": False,
        "persistent_sandbox": True,
        "requires_devops_environment": True,
    },
    "obsidian": {
        "exec": "/opt/Obsidian/obsidian",
        "exec_candidates": ("/usr/bin/obsidian",),
        "library_dirs": ("/opt/Obsidian",),
        "required_runtime_files": ("/opt/Obsidian/libffmpeg.so",),
        "env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "args": electron_args("obsidian", "launch"),
        "intel_env": {},
        "intel_args": electron_args("obsidian", "intel"),
        "nvidia_env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": electron_args("obsidian", "nvidia"),
        "bind_workspace": False,
        "pure_privacy": False,
    },
    "qoredb": {
        "exec": "/usr/bin/qoredb",
        "env": {
            "GTK_USE_PORTAL": "1",
        },
        "args": [],
        "intel_env": {},
        "intel_args": [],
        "nvidia_env": {
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": [],
        "bind_workspace": False,
        "pure_privacy": False,
        "database_state_directory": "qoredb",
    },
    "postman": {
        "exec": "/opt/postman/app/Postman",
        "library_dirs": ("/opt/postman/app",),
        "required_runtime_files": ("/opt/postman/app/libffmpeg.so",),
        "env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "args": electron_args("postman", "launch"),
        "intel_env": {},
        "intel_args": electron_args("postman", "intel"),
        "nvidia_env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": electron_args("postman", "nvidia"),
        "bind_workspace": False,
        "pure_privacy": False,
    },
    "keepassxc": {
        "exec": "/usr/bin/keepassxc",
        "env": {
            "GTK_USE_PORTAL": "1",
            "QT_QPA_PLATFORM": "wayland",
            "QT_WAYLAND_DISABLE_WINDOWDECORATION": "1",
        },
        "args": [],
        "intel_env": {},
        "intel_args": [],
        "nvidia_env": {
            "GTK_USE_PORTAL": "1",
            "QT_QPA_PLATFORM": "wayland",
            "QT_WAYLAND_DISABLE_WINDOWDECORATION": "1",
        },
        "nvidia_args": [],
        "bind_workspace": False,
        "pure_privacy": True,
        "privacy_share_net": False,
    },
    "sleek": {
        "exec": "/opt/sleek/sleek",
        "exec_candidates": ("/usr/bin/sleek",),
        "library_dirs": ("/opt/sleek",),
        "required_runtime_files": ("/opt/sleek/libffmpeg.so",),
        "env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "args": electron_args("sleek", "launch"),
        "intel_env": {},
        "intel_args": electron_args("sleek", "intel"),
        "nvidia_env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": electron_args("sleek", "nvidia"),
        "bind_workspace": False,
        "pure_privacy": False,
    },
    "spotify": {
        "exec": "/usr/bin/spotify",
        "env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "args": electron_args("spotify", "launch"),
        "intel_env": {},
        "intel_args": electron_args("spotify", "intel"),
        "nvidia_env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": electron_args("spotify", "nvidia"),
        "bind_workspace": False,
        "pure_privacy": False,
    },
    "filen": {
        "exec": "/opt/Filen/Filen",
        "exec_candidates": ("/usr/bin/filen", "/usr/bin/filen-desktop"),
        "library_dirs": ("/opt/Filen",),
        "required_runtime_files": ("/opt/Filen/libffmpeg.so",),
        "env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "args": electron_args("filen", "launch"),
        "intel_env": {},
        "intel_args": electron_args("filen", "intel"),
        "nvidia_env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": electron_args("filen", "nvidia"),
        "privacy_args": electron_privacy_args("filen"),
        "bind_workspace": False,
        "pure_privacy": True,
    },
    "discord": {
        "exec": "/opt/discord/Discord",
        "library_dirs": (DISCORD_ROOT,),
        "required_runtime_files": DISCORD_REQUIRED_FILES,
        "env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "args": electron_args("discord", "launch"),
        "intel_env": {},
        "intel_args": electron_args("discord", "intel"),
        "nvidia_env": {
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": electron_args("discord", "nvidia"),
        "bind_workspace": False,
        "pure_privacy": False,
        "persistent_sandbox": True,
    },
    "ledger-live": {
        "exec": "/opt/ledger-live/AppRun",
        "env": {
            "APPDIR": "/opt/ledger-live",
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "args": [
            *electron_args("ledger-live", "launch"),
            electron_js_flags("ledger-live"),
        ],
        "intel_env": {},
        "intel_args": electron_args("ledger-live", "intel"),
        "nvidia_env": {
            "APPDIR": "/opt/ledger-live",
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": electron_args("ledger-live", "nvidia"),
        "privacy_args": electron_privacy_args("ledger-live"),
        "bind_workspace": False,
        "pure_privacy": False,
    },
    "tutanota": {
        "exec": "/opt/tuta-mail/AppRun",
        "env": {
            "APPDIR": "/opt/tuta-mail",
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "args": electron_args("tutanota", "launch"),
        "intel_env": {},
        "intel_args": electron_args("tutanota", "intel"),
        "nvidia_env": {
            "APPDIR": "/opt/tuta-mail",
            "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
            "GTK_USE_PORTAL": "1",
        },
        "nvidia_args": electron_args("tutanota", "nvidia"),
        "bind_workspace": False,
        "pure_privacy": False,
        "persistent_sandbox": True,
    },
    "zoom": {
        "exec": "/usr/bin/zoom",
        "env": {
            "GTK_USE_PORTAL": "1",
        },
        "args": [],
        "intel_env": {},
        "intel_args": [],
        "nvidia_env": {},
        "nvidia_args": [],
        "bind_workspace": False,
        "pure_privacy": False,
        "persistent_sandbox": True,
    },
    "telegram-desktop": {
        "exec": "/usr/bin/telegram-desktop",
        "env": {
            "QT_QPA_PLATFORM": "wayland",
            "QT_WAYLAND_DISABLE_WINDOWDECORATION": "1",
        },
        "args": [],
        "intel_env": {},
        "intel_args": [],
        "nvidia_env": {
            "QT_QPA_PLATFORM": "wayland",
            "QT_WAYLAND_DISABLE_WINDOWDECORATION": "1",
        },
        "nvidia_args": [],
        "bind_workspace": False,
        "pure_privacy": True,
    },
    "retroarch": {
        "exec": "/usr/bin/retroarch",
        "env": {
            "SDL_VIDEODRIVER": "wayland",
        },
        "args": [],
        "intel_env": {},
        "intel_args": [],
        "nvidia_env": {
            "SDL_VIDEODRIVER": "wayland",
        },
        "nvidia_args": [],
        "bind_workspace": False,
        "pure_privacy": True,
        "privacy_share_net": False,
        "privacy_home_ro_paths": (".config/retroarch/retroarch.cfg",),
    },
    "qbittorrent": {
        "exec": "/usr/local/bin/labwc-qbittorrent",
        "privacy_exec": "/usr/bin/qbittorrent",
        "env": {
            "QT_QPA_PLATFORM": "wayland",
        },
        "args": [],
        "intel_env": {},
        "intel_args": ("--managed-acceleration=intel",),
        "nvidia_env": {
            "QT_QPA_PLATFORM": "wayland",
        },
        "nvidia_args": ("--managed-acceleration=nvidia",),
        "bind_workspace": False,
        "pure_privacy": True,
    },
}

MAX_DBUS_ADDRESS_LENGTH = 4096
NOTIFICATIONS_DBUS_NAME = "org.freedesktop.Notifications"
PORTAL_DBUS_NAMESPACE = "org.freedesktop.portal.*"
PORTAL_DBUS_BROADCAST_RULE = "@/org/freedesktop/portal/*"
TUTA_PERSISTENT_PATHS = (
    ".cache/tutanota-desktop",
    ".config/tutanota-desktop",
    ".local/share/tutanota-desktop",
    ".local/state/tutanota-desktop",
)
TUTA_ATTACHMENT_READ_ONLY_PATHS = (
    "Desktop",
    "Documents",
    "Music",
    "Pictures",
    "Public",
    "Templates",
    "Videos",
)
TUTA_ATTACHMENT_READ_WRITE_PATHS = ("Downloads",)
DISCORD_PERSISTENT_PATHS = (
    ".cache/discord",
    ".config/discord",
    ".local/share/discord",
    ".local/state/discord",
)
ZOOM_PERSISTENT_PATHS = (
    ".cache/zoom",
    ".local/share/zoom",
    ".zoom",
)
ZOOM_CONFIG_SOURCE = ".config/zoom"
CHATGPT_PERSISTENT_PATHS = (
    ".cache/Codex",
    ".config/Codex",
    ".local/share/Codex",
    ".local/state/Codex",
)
# Keep managed host policy inspectable from ChatGPT without exposing
# privileged service sockets to the sandbox.
CHATGPT_DEVOPS_READ_ONLY_HOME_DIRECTORIES = (
    ".cmake/packages",
    ".config/Code/User/snippets",
    ".config/bat",
    ".config/bazel",
    ".config/clangd",
    ".config/direnv",
    ".config/featherpad",
    ".config/fzf",
    ".config/git",
    ".config/micro",
    ".config/mise",
    ".config/nano",
    ".config/nvim",
    ".config/pip",
    ".config/powershell",
    ".config/retroarch",
    ".config/satty",
    ".config/sleek",
    ".config/task",
    ".config/vim",
    ".config/yamllint",
    ".local/bin",
    ".local/lib",
    ".local/share/powershell/Modules",
)
CHATGPT_DEVOPS_READ_ONLY_HOME_FILES = (
    ".bash_aliases",
    ".bash_logout",
    ".bash_profile",
    ".bashrc",
    ".config/Code/User/keybindings.json",
    ".config/Code/User/settings.json",
    ".config/cargo/config.toml",
    ".config/containers/containers.conf",
    ".config/containers/mounts.conf",
    ".config/containers/policy.json",
    ".config/containers/registries.conf",
    ".config/containers/seccomp.json",
    ".config/containers/storage.conf",
    ".config/gh/config.yml",
    ".config/go/env",
    ".config/mimeapps.list",
    ".config/obsidian/obsidian.json",
    ".config/starship.toml",
    ".config/user-dirs.dirs",
    ".config/uv/uv.toml",
    ".config/xdg-terminals.list",
    ".dircolors",
    ".gitconfig",
    ".gitlint",
    ".lldbinit",
    ".markdownlint-cli2.cjs",
    ".markdownlint-cli2.jsonc",
    ".markdownlint-cli2.mjs",
    ".markdownlint-cli2.yaml",
    ".markdownlint.json",
    ".markdownlint.yaml",
    ".markdownlint.yml",
    ".profile",
    ".profile.d/71-devops-de.sh",
    ".profile.d/72-incus.sh",
    ".profile.d/75-firmware-workspace.sh",
    ".recoll/recoll.conf",
    ".ripgreprc",
    ".rustfmt.toml",
    ".shellcheckrc",
    ".vimrc",
    ".zlogin",
    ".zlogout",
    ".zprofile",
    ".zsh_aliases",
    ".zshenv",
    ".zshrc",
)
CHATGPT_VIRTUALIZATION_READ_ONLY_SYSTEM_PATHS = (
    "/etc/default/incus-host-managed",
    "/etc/incus",
    "/etc/modprobe.d",
    "/etc/modules-load.d",
    "/etc/qemu",
    "/etc/systemd/system/incus-host-managed.service",
    "/etc/tmpfiles.d/85-qemu-incus-storage.conf",
)
CHATGPT_DEVOPS_READ_WRITE_HOME_DIRECTORIES = (
    "Downloads",
    "Workspace",
)
CHATGPT_DEVOPS_READ_WRITE_PATHS = (
    "/pool",
    "/data/codex",
    "/data/downloads",
)
PERSISTENT_SANDBOX_CONFIG = {
    "chatgpt": {
        "chdir": "Workspace",
        "config_args": (),
        "dbus_names": CHATGPT_SESSION_DBUS_NAMES,
        "dbus_own_names": (),
        "inner_sandbox_args": (),
        "persistent_paths": CHATGPT_PERSISTENT_PATHS,
        "require_session_bus": True,
        "require_system_bus": True,
        "required_runtime_sockets": ("pipewire-0", "pulse/native"),
        "ro_bind_home_directories": CHATGPT_DEVOPS_READ_ONLY_HOME_DIRECTORIES,
        "ro_bind_home_optional_files": CHATGPT_DEVOPS_READ_ONLY_HOME_FILES,
        "ro_bind_directory_paths": (
            "/data",
            "/opt",
            "/var/cache/apt",
            "/var/lib/apt/lists",
            "/var/lib/dpkg",
        ),
        "ro_bind_paths": (
            *CHATGPT_VIRTUALIZATION_READ_ONLY_SYSTEM_PATHS,
            "/etc/codex",
            "/etc/llama",
        ),
        "rw_bind_home_directories": CHATGPT_DEVOPS_READ_WRITE_HOME_DIRECTORIES,
        "rw_bind_paths": CHATGPT_DEVOPS_READ_WRITE_PATHS,
        "rw_bind_directory_pairs": (
            (
                "/var/log/managed/openai/chatgpt/runtime",
                "/data/codex/log",
            ),
        ),
        "preserve_working_directory": True,
        "runtime_directories": ("doc",),
        "runtime_sockets": (
            "pipewire-0",
            "pulse/native",
        ),
        "share_net": False,
        "shared_temp_directory": "labwc-chatgpt-tmp",
        "slirp4netns": True,
        "synthetic_identity": True,
        "system_dbus_names": CHATGPT_SYSTEM_DBUS_NAMES,
    },
    "discord": {
        "camera_devices": True,
        "chdir": ".",
        "config_args": (),
        "dbus_names": DISCORD_SESSION_DBUS_NAMES,
        "dbus_own_names": (),
        "inner_sandbox_args": (),
        "persistent_paths": DISCORD_PERSISTENT_PATHS,
        "require_session_bus": True,
        "require_system_bus": True,
        "required_runtime_sockets": ("pipewire-0", "pulse/native"),
        "ro_bind_paths": (
            DISCORD_ROOT,
            WAYLAND_COMPAT_RUNTIME_ROOT,
        ),
        "rw_bind_home_directories": ("Downloads",),
        "runtime_directories": ("doc",),
        "runtime_sockets": ("pipewire-0", "pulse/native"),
        "share_net": False,
        "slirp4netns": True,
        "system_dbus_names": (),
    },
    "tutanota": {
        "chdir": ".",
        "config_args": (),
        "dbus_names": TUTA_DBUS_NAMES,
        "inner_sandbox_args": ("--no-sandbox",),
        "persistent_paths": TUTA_PERSISTENT_PATHS,
        "require_session_bus": True,
        "require_system_bus": True,
        "ro_bind_paths": ("/opt/tuta-mail",),
        "ro_bind_home_directories": TUTA_ATTACHMENT_READ_ONLY_PATHS,
        "rw_bind_home_directories": TUTA_ATTACHMENT_READ_WRITE_PATHS,
        "ro_bind_home_paths": (
            ".config/mimeapps.list",
            ".config/user-dirs.dirs",
            ".local/share/applications/tutanota-desktop.desktop",
        ),
        "runtime_directories": ("doc",),
        "runtime_sockets": ("pipewire-0", "pulse/native"),
        "share_net": True,
        "system_dbus_names": TUTA_SYSTEM_DBUS_NAMES,
    },
    "zoom": {
        "chdir": ".",
        "camera_devices": True,
        "config_args": (),
        "dbus_names": ZOOM_SESSION_DBUS_NAMES,
        "dbus_own_names": ZOOM_SESSION_DBUS_OWN_NAMES,
        "inner_sandbox_args": (),
        "persistent_paths": ZOOM_PERSISTENT_PATHS,
        "persistent_directory_binds": (
            (ZOOM_CONFIG_SOURCE, ".config"),
        ),
        "require_session_bus": True,
        "require_system_bus": True,
        "required_runtime_sockets": ("pipewire-0", "pulse/native"),
        "ro_bind_paths": (
            "/opt/zoom",
            WAYLAND_COMPAT_RUNTIME_ROOT,
        ),
        "rw_bind_home_directories": (
            "Documents",
            "Downloads",
        ),
        "runtime_directories": ("doc",),
        "runtime_sockets": ("pipewire-0", "pulse/native"),
        "share_net": False,
        "slirp4netns": True,
        "system_dbus_names": (),
    },
}

OBSIDIAN_VAULT_RELATIVE_PATH = "Syncthing/obsidian-md"
OBSIDIAN_REGISTRY_MAX_BYTES = 1024 * 1024

MANAGED_RUNTIME_STATE = {
    "bitwarden": {
        "directories": (
            (".config/autostart", 0o700),
            (".config/chromium/NativeMessagingHosts", 0o700),
            (".config/google-chrome/NativeMessagingHosts", 0o700),
            (".config/microsoft-edge/NativeMessagingHosts", 0o700),
            (".config/vivaldi/NativeMessagingHosts", 0o700),
            (".mozilla/native-messaging-hosts", 0o700),
            (
                ".var/app/org.mozilla.firefox/.mozilla/native-messaging-hosts",
                0o700,
            ),
            (
                ".var/app/com.google.Chrome/config/google-chrome/NativeMessagingHosts",
                0o700,
            ),
            (
                ".var/app/org.chromium.Chromium/config/chromium/NativeMessagingHosts",
                0o700,
            ),
            (
                ".var/app/com.microsoft.Edge/config/microsoft-edge/NativeMessagingHosts",
                0o700,
            ),
        ),
    },
    "chatgpt": {
        "directories": tuple((path, 0o700) for path in CHATGPT_PERSISTENT_PATHS),
    },
    "discord": {
        "directories": tuple((path, 0o700) for path in DISCORD_PERSISTENT_PATHS),
    },
    "keepassxc": {
        "directories": (
            (".cache/keepassxc", 0o700),
            (".config/keepassxc", 0o700),
            (".local/share/keepassxc", 0o700),
            ("Syncthing", 0o700),
            ("Syncthing/keepassxc", 0o700),
            ("Syncthing/keepassxc/backups", 0o700),
        ),
        "files": (
            (
                ".config/keepassxc/keepassxc.ini",
                0o600,
                "/etc/skel-desktop/.config/keepassxc/keepassxc.ini",
            ),
        ),
    },
    "telegram-desktop": {
        "directories": (
            (".cache/telegram-desktop", 0o700),
            (".config/telegram-desktop", 0o700),
            (".local/share/TelegramDesktop", 0o700),
        ),
        "files": (
            (".local/share/TelegramDesktop/log.txt", 0o600, None),
        ),
    },
    "zoom": {
        "directories": tuple(
            (path, 0o700)
            for path in (*ZOOM_PERSISTENT_PATHS, ZOOM_CONFIG_SOURCE)
        ),
    },
}
