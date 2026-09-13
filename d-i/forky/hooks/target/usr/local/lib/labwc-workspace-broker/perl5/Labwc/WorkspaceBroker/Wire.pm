package Labwc::WorkspaceBroker::Wire;
use strict;
use warnings;
use Exporter 'import';
use JSON::PP ();
use Encode qw(decode FB_CROAK);
use B ();
our @EXPORT_OK = qw(json_bytes decode_json frame take_frames exact_keys uint text);
use constant MAX_FRAME => 262144;
my $JSON = JSON::PP->new->utf8->canonical->max_depth(20)->allow_nonref(0);
my $SCALAR = JSON::PP->new->allow_nonref(1)->max_depth(20);

sub json_bytes { return $JSON->encode($_[0]); }

# JSON::PP otherwise accepts repeated keys. Scan the already syntax-validated
# document, retaining decoded object keys ("a" and "\u0061" are duplicates).
# No eval, recursive regular expression, or application-provided pattern.
sub _unique_keys {
    my ($s) = @_;
    my @stack;
    pos($s) = 0;
    while (pos($s) < length($s)) {
        $s =~ /\G\s*/gc;
        last if pos($s) == length($s);
        if ($s =~ /\G("(?:[^"\\]|\\.)*")/gcs) {
            if (@stack && $stack[-1]{object} && $stack[-1]{key}) {
                my $key = $SCALAR->decode($1);
                die "duplicate JSON key\n" if $stack[-1]{seen}{$key}++;
                $stack[-1]{key} = 0;
            }
        } elsif ($s =~ /\G([\{\[\}\],:])/gc) {
            my $c = $1;
            if ($c eq '{' || $c eq '[') {
                push @stack, { object => $c eq '{', key => $c eq '{', seen => {} };
            } elsif ($c eq '}' || $c eq ']') {
                pop @stack;
            } elsif ($c eq ',' && @stack && $stack[-1]{object}) {
                $stack[-1]{key} = 1;
            }
        } elsif ($s =~ /\G(true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/gc) {
            my $number = $1;
            die "noninteger JSON number\n" if $number =~ /[.eE]/ && $number !~ /\A(?:true|false)\z/;
            next;
        } else {
            die "invalid JSON token\n";
        }
    }
}

sub decode_json {
    my ($bytes, $limit) = @_;
    $limit //= MAX_FRAME;
    die "frame length\n" unless length($bytes) > 0 && length($bytes) <= $limit;
    my $copy = $bytes;
    my $unicode = decode('UTF-8', $copy, FB_CROAK);
    my $value = $JSON->decode($bytes);
    die "JSON root is not an object\n" unless ref($value) eq 'HASH';
    _unique_keys($unicode);
    return $value;
}

sub frame {
    my ($value, $limit) = @_;
    $limit //= MAX_FRAME;
    my $bytes = json_bytes($value);
    die "outbound frame length\n" unless length($bytes) && length($bytes) <= $limit;
    return pack('N', length($bytes)) . $bytes;
}

sub take_frames {
    my ($buffer, $limit, $budget) = @_;
    $limit //= MAX_FRAME;
    $budget //= 64;
    my @frames;
    while (length($$buffer) >= 4 && @frames < $budget) {
        my $n = unpack('N', substr($$buffer, 0, 4));
        die "invalid frame length\n" if !$n || $n > $limit;
        last if length($$buffer) < 4 + $n;
        substr($$buffer, 0, 4, '');
        push @frames, decode_json(substr($$buffer, 0, $n, ''), $limit);
    }
    return @frames;
}

sub exact_keys {
    my ($obj, @names) = @_;
    die "expected object\n" unless ref($obj) eq 'HASH';
    my %expected = map { $_ => 1 } @names;
    die "unexpected fields\n" if keys(%$obj) != @names;
    for my $name (keys %$obj) { die "unexpected field\n" unless $expected{$name}; }
    return $obj;
}

sub uint {
    my ($value, $max, $min) = @_;
    $min //= 0;
    # Reject strings and JSON booleans as numeric protocol identities.
    die "expected integer\n" if !defined($value) || ref($value);
    my $flags = B::svref_2object(\$value)->FLAGS;
    die "expected JSON number\n" unless $flags & (B::SVf_IOK() | B::SVf_NOK());
    die "integer range\n" unless $value >= $min && $value <= $max && int($value) == $value;
    return 0 + $value;
}

sub text {
    my ($value, $max) = @_;
    die "expected string\n" if !defined($value) || ref($value);
    my $flags = B::svref_2object(\$value)->FLAGS;
    die "expected JSON string\n" unless $flags & B::SVf_POK();
    die "string length\n" if length($value) > $max;
    return $value;
}
1;
