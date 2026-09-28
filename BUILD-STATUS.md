# Build status

This archive contains the complete edited source tree. The three generated
artifacts (`d-i/forky/preseed.cfg`, `d-i/forky/payload.manifest`, and
`d-i/forky/payload.tar.gz`) are omitted because a validated build cannot be
completed in this workspace.

The current Fail2ban work installs Fail2ban and nftables with both security
profiles, keeps the SSH journal jail enabled independently of the SSH addon,
and limits repeat bans to one week with 14 days of retained ban history.
CrowdSec keeps its own SSH acquisition and nftables bouncer; Tailscale SSH uses
its own authentication path.

Verification: 8 focused policy tests and the native jail layout test passed;
`make audit` passed with 159 checks blocked by missing external dependencies;
`sh -n` accepted the edited shell file. `make build` and `make check` both
stopped at the project's required BusyBox ash syntax gate because BusyBox is
not installed here. The installed system and first-boot services have not been
run in this workspace.

On a trusted build host with BusyBox, run `make build`, `make check`,
`make test`, `make audit`, and `make validate` before serving this repository.
Then perform a Forky installation and exercise SSH bans, nftables service
reload, and any selected CrowdSec and Tailscale addons.
