# POSIX awk. Substitute literal LOG_* values without replacement evaluation.
FILENAME == ARGV[1] {
    pos=index($0,"="); if (pos<2) exit 1
    key=substr($0,1,pos-1); value[key]=substr($0,pos+1); next
}
{
    line=$0
    while (match(line,/__INSTALLER_LOG_[A-Z0-9_]+__/)) {
        token=substr(line,RSTART,RLENGTH)
        key=substr(token,13,length(token)-14)
        if (!(key in value)) {
            print "logging: unknown token " token > "/dev/stderr"; exit 1
        }
        line=substr(line,1,RSTART-1) value[key] substr(line,RSTART+RLENGTH)
    }
    if (index(line,"__INSTALLER_LOG_") != 0) {
        print "logging: malformed/unresolved logging token" > "/dev/stderr"; exit 1
    }
    print line
}
