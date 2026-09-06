package Zram::Command::Reset;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Exporter qw(import);
use Zram::Budget qw(budget_state_file);
use Zram::Config qw(cfg);
use Zram::Error qw(fatal);
use Zram::Logger qw(log_msg);
use Zram::Metrics qw(snapshot_file);

our @EXPORT_OK = qw(run);

sub _state_paths {
    my $runtime_dir = cfg('ZRAM_RUNTIME_DIR');
    my %seen;
    my @paths = grep { defined $_ && $_ ne '' && !$seen{$_}++ } (
        snapshot_file(),
        budget_state_file(),
    );

    return @paths if !-d $runtime_dir;

    opendir my $dh, $runtime_dir or fatal("failed to read zram runtime dir $runtime_dir: $!");
    while (my $entry = readdir $dh) {
        next if $entry eq '.' || $entry eq '..';
        next if $entry !~ /\.(?:metrics|budget|snapshot|state)\z/;
        my $path = "$runtime_dir/$entry";
        next if $seen{$path}++;
        push @paths, $path;
    }
    closedir $dh or fatal("failed to close zram runtime dir $runtime_dir: $!");

    return @paths;
}

sub run {
    return __PACKAGE__->new()->execute(@_);
}

sub execute {
    my ($self, @args) = @_;
    @args and fatal('usage: zram-writeback reset-state');

    my $removed = 0;
    for my $path (_state_paths()) {
        next if !-e $path && !-l $path;
        if (-d $path) {
            log_msg('warning', "skipping unexpected directory in zram runtime state cleanup: $path");
            next;
        }
        unlink $path or fatal("failed to remove zram runtime state $path: $!");
        $removed++;
    }

    log_msg('info', "removed $removed zram runtime state file(s)");
    return 0;
}

1;
