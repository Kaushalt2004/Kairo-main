#!/usr/bin/env bash
source /apollo/cyber/setup.bash

echo "=== 1. Ensuring Plugin Index and Binary Links ==="
HOME_BIN="/home/kairo_it37/.cache/bazel/540135163923dd7d5820f3ee4b306b32/execroot/apollo/bazel-out/k8-fastbuild/bin"

mkdir -p /apollo/share/cyber_plugin_index
rm -f /apollo/share/cyber_plugin_index/*.xml

# Install plugin index entries
for d in $(find $HOME_BIN -name "cyber_plugin_index" -type d); do
  cp -r "$d"/* /apollo/share/cyber_plugin_index/ 2>/dev/null
done

# Ensure planning module symlinks
mkdir -p /apollo/bazel-bin/modules/planning
for sub in planners pnc_map scenarios tasks traffic_rules; do
  if [ -d "$HOME_BIN/modules/planning/$sub" ]; then
    rm -rf "/apollo/bazel-bin/modules/planning/$sub"
    ln -sfn "$HOME_BIN/modules/planning/$sub" "/apollo/bazel-bin/modules/planning/$sub"
  fi
done

# Ensure control controllers symlinks
mkdir -p /apollo/bazel-bin/modules/control/controllers
if [ -d "$HOME_BIN/modules/control/controllers" ]; then
  for c in "$HOME_BIN/modules/control/controllers"/*; do
    name=$(basename "$c")
    rm -rf "/apollo/bazel-bin/modules/control/controllers/$name"
    ln -sfn "$c" "/apollo/bazel-bin/modules/control/controllers/$name"
  done
fi

echo "=== 2. Starting Apollo Autonomous Driving Modules ==="
pkill -f "mainboard -d /apollo/modules/routing/dag/routing.dag" || true
pkill -f "mainboard -d /apollo/modules/planning" || true
pkill -f "mainboard -d /apollo/modules/control" || true
pkill -f "mainboard -d /apollo/modules/monitor" || true

nohup mainboard -d /apollo/modules/monitor/dag/monitor.dag -p monitor -s CYBER_DEFAULT > /apollo/data/log/monitor_run.log 2>&1 &
nohup mainboard -d /apollo/modules/routing/dag/routing.dag > /apollo/data/log/routing_run.log 2>&1 &
nohup mainboard -d /apollo/modules/planning/planning_component/dag/planning.dag -d /apollo/modules/external_command/process_component/dag/external_command_process.dag > /apollo/data/log/planning_run.log 2>&1 &
nohup mainboard -d /apollo/modules/control/control_component/dag/control.dag > /apollo/data/log/control_run.log 2>&1 &

echo "=== 3. Starting Dreamview Plus ==="
bash /apollo/scripts/dreamview_plus.sh restart

echo "All modules (Monitor, Routing, Planning, Control, Dreamview Plus) started successfully!"
