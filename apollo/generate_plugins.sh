#!/bin/bash
cd /apollo
mkdir -p share/cyber_plugin_index
rm -rf share/cyber_plugin_index/*
find modules cyber -type f -name '*.xml' | while read -r xml; do
    if grep -q '<class' "$xml"; then
        filename=$(echo "$xml" | sed 's/\//__/g')
        cp "$xml" "share/cyber_plugin_index/$filename"
    fi
done
echo "Copied $(ls -1 share/cyber_plugin_index | wc -l) plugin index xml files."