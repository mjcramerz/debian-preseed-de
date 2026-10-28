#!/usr/bin/perl
# Retain the installed entrypoint while replacing the Sleek text-file daemon.
# The root-owned policy /etc/labwc/plans.conf is read by the delegate.
use strict;
use warnings;
@ARGV == 0 or die "usage: labwc-plans.pl\n";
exec { '/usr/local/libexec/labwc-calendar-worker' }
    '/usr/local/libexec/labwc-calendar-worker', '--reminders';
die "labwc-plans: calendar reminder worker unavailable\n";
