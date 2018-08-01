#!/bin/bash

#
# instant wrapper to launch senseapp as like a daemon.
#

APPPATH=/opt/twelite_sensor/raspi/senseapp.py

debug()
{
    LOGFILE=/tmp/senseapp_bootlog.txt
    echo "$0 : entry" > $LOGFILE
    sleep 15
    echo "$0 : pre launch wait complete" >> $LOGFILE
    setsid $APPPATH < /dev/null >> $LOGFILE 2>&1 &
    echo "$0 : done" >> $LOGFILE
}

release()
{
    # No logging as default to avoid wear out of SD card.
    setsid $APPPATH < /dev/null > /dev/null 2>&1 &
}

# debug
release



