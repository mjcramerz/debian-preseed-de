#!/usr/bin/perl
use strict;
use warnings;
use utf8;
use Test::More;
use File::Temp qw(tempdir);
use POSIX qw(mkfifo);
use Fcntl qw(:DEFAULT);
use JSON::PP ();
use Labwc::WorkspaceBroker::Wire qw(decode_json json_bytes frame take_frames uint text);
use Labwc::WorkspaceBroker::Policy ();
use Labwc::WorkspaceBroker::Render qw(badge clean escape_markup render picker_page);
use Labwc::WorkspaceBroker::Icons ();
use Labwc::WorkspaceBroker::Runtime qw(private_file read_private token now);
use Labwc::WorkspaceBroker::Client ();

sub rejects (&$) { my ($cb, $label) = @_; my $ok = eval { $cb->(); 1 }; ok(!$ok, $label); }
sub model { Labwc::WorkspaceBroker::Policy::new_model(4) }
sub ws {
    my ($active, $count) = @_; $count //= 4;
    return {kind=>'workspaces', groups=>[{id=>99, outputs=>[1,2],workspaces=>[1..$count]}],
        workspaces=>[map { {id=>$_, name=>"$_", stable_id=>"ws-$_", state=>defined($active) && $_==$active ? 1:0} } 1..$count]};
}
sub outputs { return {kind=>'outputs',outputs=>[{id=>1,name=>'eDP-1'},{id=>2,name=>'HDMI-A-1'}]}; }
sub commit { my ($m, $atoms, $time) = @_; Labwc::WorkspaceBroker::Policy::apply_batch($m, $atoms, $time // 10); }
sub born { return {kind=>'new',id=>$_[0]}; }
sub task {
    my ($id, $rev, $app, $state, $observed, $outs, $title) = @_;
    return {kind=>'task',id=>$id,revision=>$rev,app_id=>$app,state=>$state,observed_state=>$observed // 1,
        outputs=>$outs // [1],title=>$title // 'A <window> & "title"'};
}
sub view { Labwc::WorkspaceBroker::Policy::view_for($_[0], $_[1] // 1, $_[2] // 'eDP-1'); }
sub action { Labwc::WorkspaceBroker::Policy::action_for($_[0], $_[1] // 1, $_[2] // view($_[0])->{view}, $_[3] // 'primary', $_[4] // 20); }
sub choose { Labwc::WorkspaceBroker::Policy::picker_choose($_[0], $_[1], $_[1]{token}, $_[2] // 0, $_[3] // 21); }
my $cfg={group_slots=>4,picker_lines=>12,picker_width=>64,tooltip_windows=>8};

subtest 'strict interoperable framing' => sub {
    my $obj={n=>42,s=>"日本語\n<&>", a=>[JSON::PP::true,undef]};
    my $bytes=frame($obj); my $buffer=''; my @got;
    for my $byte (split //,$bytes) { $buffer.=$byte; push @got,take_frames(\$buffer); }
    is_deeply(\@got,[$obj],'byte-wise fragmentation preserves Unicode and data');
    is($buffer,'','complete frame consumed');
    $buffer=$bytes.$bytes; @got=take_frames(\$buffer,262144,1);
    is(scalar(@got),1,'fairness budget'); is($buffer,$bytes,'next frame retained');
    for my $bad ('', '[]', 'null', '{"a":1,"a":2}', '{"a":1,"\\u0061":2}',
                 '{"x":{"a":1,"a":2}}','{"n":NaN}','{"n":1.0}','{"n":1e0}',
                 '{"n":"\\ud800"}', '{"n":Infinity}', '{"n":true} trailing') {
        rejects { decode_json($bad) } "reject invalid/ambiguous JSON $bad";
    }
    rejects { decode_json("{\"x\":\"\xff\"}") } 'invalid UTF8';
    rejects { decode_json('{"n":'.('[' x 22).'0'.(']' x 22).'}') } 'depth bound';
    for my $n (0,262145,4294967295) { my $b=pack('N',$n); rejects { take_frames(\$b) } "length bound $n"; }
    my $s=decode_json('{"n":"1"}'); rejects { uint($s->{n},4) } 'numeric string is not an integer';
    my $n=decode_json('{"n":1}'); rejects { text($n->{n},4) } 'integer is not a string';
    rejects { uint(JSON::PP::true,4) } 'boolean is not an integer';
    is(uint(decode_json('{"n":9007199254740000}')->{n},9007199254740000),9007199254740000,'safe numeric limit');
};

subtest 'workspace learning and ordering' => sub {
    for my $count (1,3,4,5,12) {
        my $m=model(); commit($m,[outputs(),ws(1,$count),born(10),task(10,1,'foot',4)]);
        is(Labwc::WorkspaceBroker::Policy::diagnose($m)->{workspaces},$count,"dynamic $count workspaces");
        is($m->{tasks}{10}{workspace},1,'initial positive activation learned at fence');
    }
    my $m=model(); commit($m,[outputs(),ws(1),born(10),task(10,1,'foot',0)]);
    ok(!view($m)->{visible},'unfocused creation remains UNKNOWN');
    is(Labwc::WorkspaceBroker::Policy::diagnose($m)->{unknown_windows},1,'unknown diagnostic count');
    commit($m,[task(10,2,'foot',4)]); ok(view($m)->{visible},'activation learns task');
    my $old=view($m)->{view};
    commit($m,[task(10,3,'foot',0),ws(2)]);
    ok(!view($m)->{visible},'unused workspace is empty');
    is(action($m,1,$old)->{kind},'stale','old workspace lease rejected');
    commit($m,[born(11),task(11,1,'footclient',4)]);
    is(scalar(@{$m->{groups}{foot}{members}}),1,'same application across workspaces not merged');
    commit($m,[task(11,2,'footclient',0),ws(1),task(10,4,'foot',4)]);
    is($m->{groups}{foot}{members}[0]{id},10,'return to original workspace');
    my $lease=view($m)->{view};
    commit($m,[task(10,5,'foot',4,0,[1],'Renamed')]);
    is_deeply(view($m)->{view},$lease,'title-only update neither reorders nor revokes click lease');
    # State before the independent workspace-manager done is handled identically.
    commit($m,[task(10,6,'foot',4),ws(2)]);
    is($m->{tasks}{10}{workspace},2,'positive focus before workspace done learned at final fence');
    is(scalar(@{$m->{groups}{foot}{members}}),2,'followed move with fresh activation regroups');
    commit($m,[ws(3)]);
    ok(!defined($m->{tasks}{10}{workspace}),'focus-preserving ambiguous move invalidates cached active task');
    ok(!view($m)->{visible},'no cached active bit guessed onto destination');
    commit($m,[task(10,7,'foot',4,0)]);
    ok(!defined($m->{tasks}{10}{workspace}),'title-only done cannot turn cached active bit into evidence');
    commit($m,[task(10,8,'foot',0),task(10,9,'foot',4)]);
    is($m->{tasks}{10}{workspace},3,'real reactivation relearns ambiguous window');
    commit($m,[task(10,10,'foot',0),ws(1,1)]);
    ok(!defined($m->{tasks}{10}{workspace}),'removed workspace invalidates membership');
    rejects { commit($m,[{kind=>'workspaces',groups=>[],workspaces=>[
        {id=>1,name=>'1',stable_id=>'',state=>1},{id=>2,name=>'2',stable_id=>'',state=>1}]}]) } 'multiple active workspaces fail closed';
};

subtest 'group identity, multi-output and stable slots' => sub {
    my $m=model(); commit($m,[outputs(),ws(1),born(10),task(10,1,'foot',4)]);
    commit($m,[task(10,2,'foot',0),born(11),task(11,1,'footclient',4,1,[2])]);
    is(scalar(@{$m->{groups}{foot}{members}}),2,'explicit footclient alias merges');
    ok(view($m,1,'eDP-1')->{visible} && view($m,1,'HDMI-A-1')->{visible},'group on both actual outputs');
    ok(!view($m,1,'DP-8')->{visible},'unrelated output hides group');
    is(scalar(@{view($m,1,'eDP-1')->{groups}[0]{members}}),2,'count remains workspace-global');
    commit($m,[task(11,2,'footclient',0),born(12),task(12,1,'Foot',4)]);
    is(scalar(keys %{$m->{groups}}),2,'arbitrary IDs are case-sensitive');
    my $second=view($m,2)->{view};
    commit($m,[{kind=>'closed',id=>10},{kind=>'closed',id=>11}]);
    is_deeply(view($m,2)->{view},$second,'removing earlier group does not shift remaining button');
    commit($m,[task(12,2,'Foot',0),born(13),task(13,1,'org.xfce.Thunar',4)]);
    is($m->{slots}{1}{key},'thunar','free slot reused with new generation and explicit Thunar alias');
    commit($m,[task(13,2,'org.xfce.Thunar',0),born(14),task(14,1,'',4)]);
    commit($m,[task(14,2,'',0),born(15),task(15,1,'',4)]);
    is(scalar(grep {/\A\@anonymous:/} keys %{$m->{groups}}),2,'anonymous windows never grouped by equal title');
    commit($m,[task(15,2,'',0),born(16),task(16,1,'fifth-app',4)]);
    is(scalar(@{$m->{overflow}}),1,'overflow has all additional groups');
    is(action($m,0,view($m,0)->{view})->{kind},'picker','overflow remains selectable');
    commit($m,[{kind=>'outputs',outputs=>[{id=>2,name=>'HDMI-A-1'}]}]);
    ok(!view($m,1,'eDP-1')->{visible},'output removal hides output-local representation');
};

subtest 'single actions, snapshots and lifecycle races' => sub {
    my $m=model(); commit($m,[outputs(),ws(1),born(10),task(10,1,'foot',4)]);
    is_deeply(action($m)->{commands},[{id=>10,op=>'set_minimized'}],'single active toggles minimize');
    is(action($m,1,view($m)->{view},'primary',10.1)->{kind},'stale','settling gate rejects immediate click');
    is_deeply(action($m,1,undef,'close')->{commands},[{id=>10,op=>'close'}],'single middle requests exactly one close');
    is(scalar(keys %{$m->{tasks}}),1,'close request does not optimistically remove task');
    commit($m,[task(10,2,'foot',2)]);
    is_deeply(action($m)->{commands},[{id=>10,op=>'unset_minimized'},{id=>10,op=>'activate'}],'single minimized unminimizes then activates');
    commit($m,[task(10,3,'foot',0)]);
    is_deeply(action($m)->{commands},[{id=>10,op=>'activate'}],'single inactive raises');
    my $old=view($m)->{view};
    commit($m,[born(11),task(11,1,'foot',4)]);
    is(action($m,1,$old)->{kind},'stale','1-to-2 membership change revokes direct-action lease');
    my $snap=action($m)->{snapshot};
    is(scalar(@{$snap->{rows}}),2,'multi-window snapshot exact');
    is_deeply(choose($m,$snap),[{id=>11,op=>'activate'}],'MRU first; explicit selection never toggles active window');
    my $close=action($m,1,undef,'close')->{snapshot};
    is_deeply(choose($m,$close),[{id=>11,op=>'close'}],'multi middle closes only selected window');
    is_deeply(choose($m,$snap,1023),[],'out-of-range index rejected');
    is_deeply(choose($m,$snap,0,81),[],'expired picker rejected');
    is_deeply(Labwc::WorkspaceBroker::Policy::picker_choose($m,$snap,'0'x32,0,21),[],'wrong snapshot token rejected');
    commit($m,[task(11,2,'foot',4,0,[1],'Same token, changed title')]);
    is_deeply(choose($m,$snap),[{id=>11,op=>'activate'}],'title changes do not misdirect immutable snapshot');
    commit($m,[task(11,3,'other',4,0)]);
    is_deeply(choose($m,$snap),[],'app identity mutation invalidates selected row');
    commit($m,[task(11,4,'foot',0),task(10,4,'foot',4)]);
    my $before_switch=action($m)->{snapshot};
    commit($m,[task(10,5,'foot',0),ws(2)]);
    is_deeply(choose($m,$before_switch),[],'workspace change invalidates picker');
    commit($m,[ws(1),task(10,6,'foot',4)]);
    is_deeply(choose($m,$before_switch),[],'switch away-and-back does not resurrect picker');
    my $p=action($m)->{snapshot};
    my $selected=$m->{tokens}{$p->{rows}[0]{token}};
    commit($m,[{kind=>'closed',id=>$selected}]);
    is_deeply(choose($m,$p),[],'closed selected token cannot target a surviving sibling');
    rejects { commit($m,[born($selected)]) } 'adapter cannot reuse old task identity';
    rejects { commit($m,[task(999,1,'foot',4)]) } 'unannounced object cannot enter model';
    rejects { commit($m,[{kind=>'task',id=>11,revision=>9,app_id=>'foot',title=>'x',state=>0,observed_state=>1,outputs=>[1]}]) } 'nonconsecutive revisions rejected';
    my $reset=model(); commit($reset,[outputs(),ws(1)]);
    is(action($reset,1,view($m)->{view})->{kind},'stale','restart epoch invalidates old lease');
};

subtest 'badges, real image descriptors and hostile presentation data' => sub {
    is(badge(0),'','zero no badge'); is(badge(1),'','one no badge');
    for my $n (2..99) { is(badge($n),qq{<span size="x-small" rise="5000" weight="bold">$n</span>},"exact raised badge $n"); }
    like(badge(100),qr/>99\+</,'100 capped'); like(badge(137),qr/>99\+</,'137 capped');
    is(clean("<b>\nfoo\t\x{202e}bar\0",99),'<b> foo bar','controls and bidi presentation controls removed');
    is(escape_markup(q{<&>"'}),'&lt;&amp;&gt;&quot;&apos;','all markup metacharacters escaped');
    my $dir=tempdir(CLEANUP=>1); chmod 0700,$dir;
    my $icons=Labwc::WorkspaceBroker::Icons->new($dir);
    for my $value ('foot','org.xfce.Thunar','/usr/share/pixmaps/app.png') {
        is(Labwc::WorkspaceBroker::Icons::_safe_icon($value),$value,"safe image spec $value");
    }
    for my $bad ('../../etc/passwd','/home/u/icon.png','x"); color:red;','http://evil/image','/usr/share/icons/../secret') {
        is(Labwc::WorkspaceBroker::Icons::_safe_icon($bad),'application-x-executable','untrusted image path never enters CSS');
    }
    my $m=model(); commit($m,[outputs(),ws(1),born(10),task(10,1,'foot',4,1,[1],'<big>"$(touch /tmp/not-executed)" & `id`</big>')]);
    my $r=render(view($m),$icons,$cfg);
    is($r->{text},"\x{200b}",'single real-image label has no substitute font glyph or count');
    like(join(' ',@{$r->{class}}),qr/\bwbi-[0-9a-f]{64}\b/,'image class is an opaque digest');
    like($r->{tooltip},qr/&lt;big&gt;/,'hostile title rendered literally');
    unlike($r->{tooltip},qr/<big>/,'no raw application markup');
    my @batch=(task(10,2,'foot',0));
    for my $id (11..146) { push @batch,born($id),task($id,1,'foot',0); }
    # These are learned through positive activation in one stable-workspace batch.
    for my $a (@batch) { $a->{state}=4 if $a->{kind} eq 'task'; }
    commit($m,\@batch);
    $r=render(view($m),$icons,$cfg);
    like($r->{text},qr/>99\+</,'large group badge capped visually');
    like($r->{tooltip},qr/137 windows/,'tooltip retains exact count');
    my $snapshot=action($m)->{snapshot};
    my $first=picker_page($snapshot,0,$cfg); my $last=picker_page($snapshot,128,$cfg);
    is(@{$first->{rows}},128,'bounded first picker page'); is(@{$last->{rows}},9,'remaining rows accessible');
    is($last->{rows}[0]{index},128,'paging preserves immutable global index');
    rejects { picker_page($snapshot,1,$cfg) } 'unaligned pages rejected';
    Labwc::WorkspaceBroker::Client::_page($first); Labwc::WorkspaceBroker::Client::_page($last);
    pass('client validates real broker picker pages');
    my $css=read_private("$dir/icons.css",2097152);
    like($css,qr/-gtk-icontheme\("/,'real GTK theme images rather than glyph mapping');
    unlike($css,qr/touch \/tmp|<big>/,'hostile strings never enter stylesheet');
    my $inode=(stat("$dir/icons.css"))[1]; $icons->write_css;
    is((stat("$dir/icons.css"))[1],$inode,'stylesheet inode retained for Waybar close-write monitor');
};

subtest 'private file invariants' => sub {
    my $dir=tempdir(CLEANUP=>1); chmod 0700,$dir;
    my $path="$dir/private";
    my $f=private_file($path,O_WRONLY|O_CREAT|O_EXCL); print {$f} 'sentinel'; close $f;
    is(read_private($path,100),'sentinel','bounded owned 0600 file');
    symlink($path,"$dir/link") or die $!;
    rejects { private_file("$dir/link",O_WRONLY|O_TRUNC) } 'symlink writes rejected';
    is(read_private($path,100),'sentinel','rejected truncation did not modify target');
    link($path,"$dir/hardlink") or die $!;
    rejects { private_file($path,O_WRONLY|O_TRUNC) } 'multiply linked file rejected before truncate';
    unlink "$dir/hardlink"; chmod 0644,$path;
    rejects { private_file($path,O_WRONLY|O_TRUNC) } 'loose mode rejected';
    chmod 0600,$path;
    rejects { read_private($path,2) } 'file read limit';
    mkfifo("$dir/fifo",0600) == 0 or die $!;
    rejects { read_private("$dir/fifo",100) } 'FIFO rejected without blocking on open';
    like(token(),qr/\A[0-9a-f]{32}\z/,'128-bit opaque tokens');
};

subtest 'real Moo strict aggregate when installed' => sub {
    my $available=eval { require Labwc::WorkspaceBroker::State; 1 };
    plan skip_all=>'Debian Moo/MooX/Type::Tiny not installed in this test environment' unless $available;
    my $state=Labwc::WorkspaceBroker::State->new(config=>$cfg);
    $state->commit([outputs(),ws(1),born(10),task(10,1,'foot',4)],10);
    ok($state->view(1,'eDP-1')->{visible},'actual Moo aggregate owns reducer');
    rejects { Labwc::WorkspaceBroker::State->new(config=>$cfg,confg=>{}) } 'unknown Moo constructor key rejected';
    rejects { Labwc::WorkspaceBroker::State->new(config=>[]) } 'Type::Tiny rejects non-hash configuration';
    rejects { $state->config({}) } 'read-only aggregate configuration';
};
done_testing;
