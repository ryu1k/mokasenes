#!/bin/bash


CMD="/opt/td-agent-bit/bin/td-agent-bit"
OPT="-c /opt/twelite_sensor/raspi/td-agent-bit/td-agent-bit.conf"
DBGOPT="-vv"
debug()
{
    LOGFILE=/tmp/senseapp_td-agent-bit_bootlog.txt
    echo "$0 : entry" > $LOGFILE
    sleep 2
    echo "$0 : pre launch wait complete" >> $LOGFILE
    setsid $CMD $OPT $DBGOPT < /dev/null >> $LOGFILE 2>&1 &
    echo "$0 : done" >> $LOGFILE
}

release()
{
    setsid $CMD $OPT < /dev/null > /dev/null 2>&1 &
}

# debug
release



