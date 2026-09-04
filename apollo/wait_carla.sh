#!/bin/bash
i=0
while [ $i -lt 20 ]; do
    ps aux | grep -q '[C]arlaUE4' && echo "CARLA_RUNNING" && exit 0
    i=$((i+1))
    sleep 2
done
echo "CARLA_TIMEOUT"
