
#include <linux/module.h>
#include <linux/sched.h>
#include <linux/sched/task.h>
#include <linux/string.h>
#include <linux/kstrtox.h>
#define NV_API_CALL
#define NvU32 u32
typedef size_t NvLength;
typedef int NvlStatus;
#define NVSWITCH_REGKEY_VALUE_LEN 8
#define NVL_ERR_GENERIC 1
#define NVL_SUCCESS 0
static const char *NvSwitchRegDwords;
static int nvswitch_os_strtouint(char *s, unsigned *v) { return kstrtou32(s, 16, v); }
void os_get_current_process_name(char *buf, NvU32 len);
NvlStatus nvswitch_os_read_registry_dword(void *os_handle, const char *name, NvU32 *data);
char *nvswitch_os_strncpy(char *dest, const char *src, NvLength length);
char *nvkms_strncpy(char *dest, const char *src, size_t n);
#pragma GCC poison strncpy
void NV_API_CALL os_get_current_process_name(char *buf, NvU32 len)
{
    task_lock(current);
    /* NV_INSTALLER_NVIDIA_LEGACY_STRNCPY_COMPAT */
    strscpy_pad(buf, current->comm, len);
    task_unlock(current);
}


#include <linux/string.h>
NvlStatus nvswitch_os_read_registry_dword(void *os_handle, const char *name, NvU32 *data)
{
    char *regkey, *regkey_val_start, *regkey_val_end;
    char regkey_val[NVSWITCH_REGKEY_VALUE_LEN + 1];
    NvU32 regkey_val_len = 0;
    *data = 0;
    if (!NvSwitchRegDwords) return -NVL_ERR_GENERIC;
    regkey = strstr(NvSwitchRegDwords, name);
    if (!regkey) return -NVL_ERR_GENERIC;
    regkey = strchr(regkey, '=');
    if (!regkey) return -NVL_ERR_GENERIC;
    regkey_val_start = regkey + 1;
    regkey_val_end = strchr(regkey, ';');
    if (!regkey_val_end) regkey_val_end = strchr(regkey, '\0');
    regkey_val_len = regkey_val_end - regkey_val_start;
    if (regkey_val_len > NVSWITCH_REGKEY_VALUE_LEN || regkey_val_len == 0)
        return -NVL_ERR_GENERIC;
    memcpy(regkey_val, regkey_val_start, regkey_val_len);
    regkey_val[regkey_val_len] = '\0';
    if (nvswitch_os_strtouint(regkey_val, data) != 0) return -NVL_ERR_GENERIC;
    return NVL_SUCCESS;
}
char*
nvswitch_os_strncpy
(
    char *dest,
    const char *src,
    NvLength length
)
{
    /* NV_INSTALLER_NVIDIA_LEGACY_BOUNDED_COPY: preserve the binary ABI. */
    size_t copied;

    if (length == 0)
        return dest;
    copied = strnlen(src, length);
    if (copied != 0)
        memcpy(dest, src, copied);
    if (copied < length)
        memset(dest + copied, 0, length - copied);
    return dest;
}


#include <linux/string.h>
char* nvkms_strncpy(char *dest, const char *src, size_t n)
{
    /* NV_INSTALLER_NVIDIA_LEGACY_BOUNDED_COPY: preserve the binary ABI. */
    size_t copied;

    if (n == 0)
        return dest;
    copied = strnlen(src, n);
    if (copied != 0)
        memcpy(dest, src, copied);
    if (copied < n)
        memset(dest + copied, 0, n - copied);
    return dest;
}


#include <linux/string.h>
struct { char name[64]; } chunk_split_cache[2];
static void init_chunk_split_cache_level(unsigned level)
{
    strscpy_pad(chunk_split_cache[level].name, "uvm_gpu_chunk_t", sizeof(chunk_split_cache[level].name));
}

static int __init compatibility_probe_init(void)
{
    char task_name[32], buffer[64];
    NvU32 value;
    os_get_current_process_name(task_name, sizeof(task_name));
    nvswitch_os_strncpy(buffer, task_name, sizeof(buffer));
    nvkms_strncpy(buffer, task_name, sizeof(buffer));
    NvSwitchRegDwords = "Test=ffffffff;Other=1";
    if (nvswitch_os_read_registry_dword(NULL, "Test", &value))
        return -EINVAL;
    init_chunk_split_cache_level(0);
    return value == 0xffffffffU ? 0 : -EINVAL;
}
static void __exit compatibility_probe_exit(void) { }
module_init(compatibility_probe_init);
module_exit(compatibility_probe_exit);
MODULE_LICENSE("NVIDIA");
MODULE_DESCRIPTION("Compile-only compatibility probe, NOT the NVIDIA driver; do not load");
