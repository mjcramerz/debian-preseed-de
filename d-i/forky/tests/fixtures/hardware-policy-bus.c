/* Test-only libsystemd protocol peer on a private bus; never installed.
 * Opaque declarations keep this fixture independent of development headers.
 * API declarations: systemd/src/systemd/sd-bus.h (LGPL-2.1-or-later API).
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
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
extern const char *sd_bus_message_get_path(sd_bus_message *);
extern int sd_bus_reply_method_return(sd_bus_message *, const char *, ...);
extern int sd_bus_reply_method_errorf(sd_bus_message *, const char *, const char *, ...);

static int property(sd_bus_message *m, void *userdata, sd_bus_error *error) {
    (void)error;
    const char *interface = NULL, *name = NULL, *path = sd_bus_message_get_path(m);
    if (!sd_bus_message_is_method_call(m, "org.freedesktop.DBus.Properties", "Get")) return 0;
    if (sd_bus_message_read(m, "ss", &interface, &name) < 0 ||
        strcmp(interface, "org.freedesktop.systemd1.Unit") || strcmp(name, "ActiveState")) return -22;
    if (strstr(path, "ondemand_2eservice"))
        return sd_bus_reply_method_errorf(m, "org.freedesktop.DBus.Error.UnknownObject", "fixture absent unit");
    const char *state = "inactive";
    if (strcmp(path, "/org/freedesktop/systemd1/unit/power_2dprofiles_2ddaemon_2eservice") == 0)
        state = (const char *)userdata;
    if (!strcmp(state, "denied"))
        return sd_bus_reply_method_errorf(m, "org.freedesktop.DBus.Error.AccessDenied", "fixture access denied");
    if (!strcmp(state, "timeout")) { sleep(2); return 1; }
    return sd_bus_reply_method_return(m, "v", "s", state);
}

int main(int argc, char **argv) {
    sd_bus *bus = NULL;
    if (argc != 2 || sd_bus_open_system(&bus) < 0) return 2;
    if (sd_bus_request_name(bus, "org.freedesktop.systemd1", 0) < 0 ||
        sd_bus_add_fallback(bus, NULL, "/org/freedesktop/systemd1/unit", property, argv[1]) < 0) return 3;
    puts("ready"); fflush(stdout);
    for (;;) {
        int r = sd_bus_process(bus, NULL);
        if (r < 0) return 4;
        if (r == 0 && sd_bus_wait(bus, UINT64_MAX) < 0) return 5;
    }
}
