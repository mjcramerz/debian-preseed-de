/* Test-only systemd D-Bus protocol peer. Never installed or run on the host bus.
 * Opaque declarations follow the public libsystemd API (LGPL-2.1-or-later).
 * This verifies wire signatures and error handling, not PID 1 implementation.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct sd_bus sd_bus;
typedef struct sd_bus_slot sd_bus_slot;
typedef struct sd_bus_message sd_bus_message;
typedef struct { const char *name; const char *message; int need_free; } sd_bus_error;
typedef int (*handler)(sd_bus_message *, void *, sd_bus_error *);
extern int sd_bus_open_system(sd_bus **);
extern int sd_bus_request_name(sd_bus *, const char *, uint64_t);
extern int sd_bus_add_fallback(sd_bus *, sd_bus_slot **, const char *, handler, void *);
extern int sd_bus_process(sd_bus *, sd_bus_message **);
extern int sd_bus_wait(sd_bus *, uint64_t);
extern int sd_bus_message_is_method_call(sd_bus_message *, const char *, const char *);
extern int sd_bus_message_read(sd_bus_message *, const char *, ...);
extern int sd_bus_message_enter_container(sd_bus_message *, char, const char *);
extern int sd_bus_message_exit_container(sd_bus_message *);
extern const char *sd_bus_message_get_path(sd_bus_message *);
extern const char *sd_bus_message_get_member(sd_bus_message *);
extern int sd_bus_reply_method_return(sd_bus_message *, const char *, ...);
extern int sd_bus_reply_method_errorf(sd_bus_message *, const char *, const char *, ...);

struct unit { const char *name, *path, *active; int enabled, runtime_mask, mask; };
static struct unit units[] = {
    {"power-profiles-daemon.service", "/org/freedesktop/systemd1/unit/power_2dprofiles_2ddaemon_2eservice", "active", 1, 0, 0},
    {"hardware-tuning-autostart.service", "/org/freedesktop/systemd1/unit/hardware_2dtuning_2dautostart_2eservice", "inactive", 0, 0, 0}
};
static const char *mode;
static FILE *trace;
static int pending;
static const char *manager = "org.freedesktop.systemd1.Manager";
static struct unit *named(const char *name) {
    for (unsigned i = 0; i < 2; i++) if (!strcmp(name, units[i].name)) return &units[i];
    return NULL;
}
static const char *file_state(struct unit *u) {
    return u->mask ? "masked" : u->runtime_mask ? "masked-runtime" : u->enabled ? "enabled" : "disabled";
}
static int absent(sd_bus_message *m) {
    return sd_bus_reply_method_errorf(m, "org.freedesktop.DBus.Error.UnknownObject", "fixture absent object");
}
static int invalid(sd_bus_message *m) {
    return sd_bus_reply_method_errorf(m, "org.freedesktop.DBus.Error.InvalidArgs", "fixture argument validation failed");
}
static int method(sd_bus_message *m, void *userdata, sd_bus_error *error) {
    (void)userdata; (void)error;
    const char *member = sd_bus_message_get_member(m), *path = sd_bus_message_get_path(m);
    const char *name = NULL, *iface = NULL, *jobmode = NULL;
    struct unit *u = NULL;
    if (!member) return 0;
    if (sd_bus_message_is_method_call(m, "org.freedesktop.DBus.Properties", "Get")) {
        if (sd_bus_message_read(m, "ss", &iface, &name) < 0) return invalid(m);
        if (!strcmp(iface, "org.freedesktop.systemd1.Manager") && !strcmp(name, "SystemState"))
            return sd_bus_reply_method_return(m, "v", "s", !strcmp(mode, "stopping") ? "stopping" : "running");
        if (!strcmp(iface, "org.freedesktop.systemd1.Job")) {
            if (pending && !strcmp(name, "State")) return sd_bus_reply_method_return(m, "v", "s", "waiting");
            return absent(m);
        }
        if (strcmp(iface, "org.freedesktop.systemd1.Unit")) return invalid(m);
        for (unsigned i = 0; i < 2; i++) if (!strcmp(path, units[i].path)) u = &units[i];
        if (!strcmp(name, "ActiveState")) {
            if (!strcmp(mode, "other-owner") && strstr(path, "/tlp_2eservice"))
                return sd_bus_reply_method_return(m, "v", "s", "active");
            return sd_bus_reply_method_return(m, "v", "s", u ? u->active : "inactive");
        }
        if (u && !strcmp(name, "LoadState"))
            return sd_bus_reply_method_return(m, "v", "s", u->mask || u->runtime_mask ? "masked" : "loaded");
        return invalid(m);
    }
    if (sd_bus_message_is_method_call(m, "org.freedesktop.systemd1.Job", "Cancel")) {
        fprintf(trace, "Cancel\n"); fflush(trace); pending = 0;
        return sd_bus_reply_method_return(m, "");
    }
    if (sd_bus_message_is_method_call(m, manager, "Reload")) {
        fprintf(trace, "Reload\n"); fflush(trace);
        return sd_bus_reply_method_return(m, "");
    }
    if (sd_bus_message_is_method_call(m, manager, "LoadUnit") ||
        sd_bus_message_is_method_call(m, manager, "GetUnitFileState")) {
        if (sd_bus_message_read(m, "s", &name) < 0 || !(u = named(name))) return invalid(m);
        if (u == &units[0] && !strcmp(mode, "missing-ppd"))
            return sd_bus_reply_method_errorf(m, "org.freedesktop.systemd1.NoSuchUnit", "fixture missing PPD");
        if (!strcmp(member, "LoadUnit")) return sd_bus_reply_method_return(m, "o", u->path);
        if (u == &units[0] && !strcmp(mode, "missing-file-state"))
            return sd_bus_reply_method_errorf(m, "org.freedesktop.systemd1.NoSuchUnitFile", "fixture missing file state");
        return sd_bus_reply_method_return(m, "s", file_state(u));
    }
    if (sd_bus_message_is_method_call(m, manager, "StartUnit") ||
        sd_bus_message_is_method_call(m, manager, "StopUnit")) {
        if (sd_bus_message_read(m, "ss", &name, &jobmode) < 0 || !(u = named(name)) || strcmp(jobmode, "replace")) return invalid(m);
        fprintf(trace, "%s %s\n", member, name); fflush(trace);
        if (!strcmp(mode, "deny-stop") && !strcmp(member, "StopUnit"))
            return sd_bus_reply_method_errorf(m, "org.freedesktop.DBus.Error.AccessDenied", "fixture denied stop");
        pending = !strcmp(mode, "pending-job");
        if (!strcmp(member, "StartUnit")) {
            if (u->mask || u->runtime_mask) return sd_bus_reply_method_errorf(m, "org.freedesktop.systemd1.UnitMasked", "fixture masked unit");
            u->active = !strcmp(mode, "start-fails") ? "failed" : "active";
        } else if (strcmp(mode, "stop-lies")) u->active = "inactive";
        return sd_bus_reply_method_return(m, "o", "/org/freedesktop/systemd1/job/1");
    }
    if (sd_bus_message_is_method_call(m, manager, "EnableUnitFiles") ||
        sd_bus_message_is_method_call(m, manager, "DisableUnitFiles") ||
        sd_bus_message_is_method_call(m, manager, "MaskUnitFiles") ||
        sd_bus_message_is_method_call(m, manager, "UnmaskUnitFiles")) {
        int runtime = -1, force = -1;
        const char *extra = NULL;
        if (sd_bus_message_enter_container(m, 'a', "s") <= 0 ||
            sd_bus_message_read(m, "s", &name) <= 0 || !(u = named(name)) ||
            sd_bus_message_read(m, "s", &extra) != 0 || sd_bus_message_exit_container(m) < 0 ||
            sd_bus_message_read(m, "b", &runtime) <= 0) return invalid(m);
        if (!strcmp(member, "EnableUnitFiles") || !strcmp(member, "MaskUnitFiles")) {
            if (sd_bus_message_read(m, "b", &force) <= 0 || force) return invalid(m);
        }
        fprintf(trace, "%s %s runtime=%d force=%d\n", member, name, runtime, force); fflush(trace);
        if (!strcmp(member, "EnableUnitFiles")) u->enabled = 1;
        if (!strcmp(member, "DisableUnitFiles") && !u->mask && !u->runtime_mask) u->enabled = 0;
        if (!strcmp(member, "MaskUnitFiles")) { if (runtime) u->runtime_mask = 1; else u->mask = 1; }
        if (!strcmp(member, "UnmaskUnitFiles")) { if (runtime) u->runtime_mask = 0; else u->mask = 0; }
        if (!strcmp(member, "EnableUnitFiles")) return sd_bus_reply_method_return(m, "ba(sss)", 1, 0);
        return sd_bus_reply_method_return(m, "a(sss)", 0);
    }
    return 0;
}
int main(int argc, char **argv) {
    sd_bus *bus = NULL;
    if (argc != 3 || !(trace = fopen(argv[2], "w")) || sd_bus_open_system(&bus) < 0) return 2;
    mode = argv[1];
    if (sd_bus_request_name(bus, "org.freedesktop.systemd1", 0) < 0 ||
        sd_bus_add_fallback(bus, NULL, "/org/freedesktop/systemd1", method, NULL) < 0) return 3;
    puts("ready"); fflush(stdout);
    for (;;) {
        int r = sd_bus_process(bus, NULL);
        if (r < 0) return 4;
        if (r == 0 && sd_bus_wait(bus, UINT64_MAX) < 0) return 5;
    }
}
