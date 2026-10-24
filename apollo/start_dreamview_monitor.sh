#!/usr/bin/env bash
# Start Apollo Monitor + PnC modules and Dreamview Plus inside apollo_dev_kairo_it37.
# Unlike start_pnc_modules.sh, this does not depend on a user-specific bazel cache
# path and leaves /apollo/share/cyber_plugin_index untouched.
source /apollo/cyber/setup.bash
# setup.bash hardcodes the docker0 gateway; Cyber must bind to this container's IP.
export CYBER_IP=$(hostname -I | awk '{print $1}')
mkdir -p /apollo/data/log

echo "=== 1. Preparing CARLA maps (routing_map / sim_map) ==="
for dir in /apollo/modules/map/data/carla_town0*; do
  if [ ! -f "$dir/routing_map.bin" ] && [ ! -f "$dir/routing_map.txt" ]; then
    echo "Generating routing map for $(basename $dir)"
    /apollo/bazel-bin/modules/routing/topo_creator \
      --flagfile=/apollo/modules/routing/conf/routing.conf --map_dir="$dir" \
      > /apollo/data/log/topo_$(basename $dir).log 2>&1
  fi
  if [ ! -f "$dir/sim_map.bin" ] && [ ! -f "$dir/sim_map.txt" ]; then
    echo "Generating sim map for $(basename $dir)"
    /apollo/bazel-bin/modules/map/tools/sim_map_generator \
      --map_dir="$dir" --output_dir="$dir" \
      > /apollo/data/log/simmap_$(basename $dir).log 2>&1
  fi
done

echo "=== 2. Starting Monitor, Routing, Planning, Control ==="
pkill -f "mainboard -d /apollo/modules/monitor" || true
pkill -f "mainboard -d /apollo/modules/routing" || true
pkill -f "mainboard -d /apollo/modules/planning" || true
pkill -f "mainboard -d /apollo/modules/control" || true
sleep 1

nohup mainboard -d /apollo/modules/monitor/dag/monitor.dag > /apollo/data/log/monitor_run.log 2>&1 &
nohup mainboard -d /apollo/modules/routing/dag/routing.dag > /apollo/data/log/routing_run.log 2>&1 &
nohup mainboard -d /apollo/modules/planning/planning_component/dag/planning.dag \
  -d /apollo/modules/external_command/process_component/dag/external_command_process.dag \
  > /apollo/data/log/planning_run.log 2>&1 &
nohup mainboard -d /apollo/modules/control/control_component/dag/control.dag > /apollo/data/log/control_run.log 2>&1 &

echo "=== 3. Starting Dreamview Plus ==="
bash /apollo/scripts/dreamview_plus.sh restart

echo "Done. Open http://localhost:8888"
