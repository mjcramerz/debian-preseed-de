package ExternalSoftware::Servicing::Process;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Errno qw(ENOENT ESRCH);
use ExternalSoftware::Servicing::Atomic;

use constant MAX_PROCESS_ENTRIES => 1_048_576;
use constant MAX_PROTECTED_PATHS => 128;

sub _validated_paths {
    my ($label, $paths) = @_;
    ref $paths eq 'ARRAY'
        or die "$label must be an array reference\n";
    @{$paths} <= MAX_PROTECTED_PATHS
        or die "$label contains too many paths\n";
    my %validated;
    for my $path (@{$paths}) {
        ExternalSoftware::Servicing::Atomic->assert_absolute_path($label, $path);
        $validated{$path} = 1;
    }
    return \%validated;
}

sub application_running {
    my ($class, %args) = @_;
    for my $name (keys %args) {
        $name =~ /\A(?:executables|proc_root|roots)\z/
            or die "unsupported process guard argument: $name\n";
    }
    my $proc_root = $args{proc_root} // '/proc';
    ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        'process filesystem root',
        $proc_root,
    );
    -d $proc_root && !-l $proc_root
        or die "process filesystem root is not a real directory\n";

    my $executables = _validated_paths(
        'protected executable',
        $args{executables} // [],
    );
    my $roots = _validated_paths(
        'protected installation root',
        $args{roots} // [],
    );
    keys(%{$executables}) + keys(%{$roots}) > 0
        or die "process guard requires at least one protected path\n";

    opendir my $proc_dir, $proc_root
        or die "process filesystem root cannot be opened: $!\n";
    my $entries = 0;
    while (1) {
        $! = 0;
        my $entry = readdir $proc_dir;
        if (!defined $entry) {
            die "process filesystem root cannot be read: $!\n" if $!;
            last;
        }
        next if $entry !~ /\A[1-9][0-9]*\z/;
        ++$entries <= MAX_PROCESS_ENTRIES
            or die "process filesystem contains too many process entries\n";
        my $executable = readlink "$proc_root/$entry/exe";
        if (!defined $executable) {
            next if $! == ENOENT || $! == ESRCH;
            die "process executable cannot be inspected: $entry: $!\n";
        }
        $executable =~ s/ \(deleted\)\z//;
        if ($executables->{$executable}) {
            closedir $proc_dir
                or die "process filesystem root cannot be closed: $!\n";
            return 1;
        }
        for my $root (keys %{$roots}) {
            next if $executable ne $root && index($executable, "$root/") != 0;
            closedir $proc_dir
                or die "process filesystem root cannot be closed: $!\n";
            return 1;
        }
    }
    closedir $proc_dir
        or die "process filesystem root cannot be closed: $!\n";
    return 0;
}

1;
