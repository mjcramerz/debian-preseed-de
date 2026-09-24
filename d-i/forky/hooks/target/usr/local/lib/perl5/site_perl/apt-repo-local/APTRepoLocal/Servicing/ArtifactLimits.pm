package APTRepoLocal::Servicing::ArtifactLimits;

use strict;
use warnings;
use Exporter qw(import);

our @EXPORT_OK = qw(MAX_DEB_BYTES MAX_DOWNLOAD_BYTES);

# Publisher/transport policy and retained-archive policy are deliberately
# separate. Retained archives have extra headroom for local package rewrites;
# neither policy permits an unbounded file or an unbounded in-memory read.
# MAX_DOWNLOAD_BYTES must match MAX_DEB in the Python apt-repo-local.
# Application specifications may retain smaller, explicit transport budgets.
# The cross-language regression checks both actual values and their ordering.
use constant MAX_DOWNLOAD_BYTES => 2_147_483_648;  # 2 GiB
use constant MAX_DEB_BYTES      => 4_294_967_296;  # 4 GiB

1;
