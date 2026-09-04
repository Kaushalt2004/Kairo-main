#!/bin/bash
echo '============================================='
echo '  Apollo Module Library Availability Check'
echo '============================================='
echo ''

# Key modules for CARLA simulation
MODULES=(
  "planning:modules/planning/planning_component/libplanning_component.so"
  "routing:modules/routing/librouting_component.so"
  "prediction:modules/prediction/libprediction_component.so"
  "localization_rtk:modules/localization/rtk/librtk_localization_component.so"
  "control:modules/control/control_component/libcontrol_component.so"
  "monitor:modules/monitor/libmonitor.so"
  "transform:modules/transform/libstatic_transform_component.so"
  "task_manager:modules/task_manager/libtask_manager_component.so"
  "guardian:modules/guardian/libguardian_component.so"
  "storytelling:modules/storytelling/libstorytelling_component.so"
  "external_command:modules/external_command/process_component/libexternal_command_process_component.so"
  "perception_fusion:modules/perception/multi_sensor_fusion/libmulti_sensor_fusion.so"
)

for entry in "${MODULES[@]}"; do
  name="${entry%%:*}"
  lib="${entry##*:}"

  # Check in source dir, bazel-bin, and bazel-apollo
  found="NO"
  location=""
  if [ -f "/apollo/$lib" ]; then
    found="YES"
    location="/apollo/$lib"
  elif [ -f "/apollo/bazel-bin/$lib" ]; then
    found="YES"
    location="/apollo/bazel-bin/$lib"
  elif [ -f "/apollo/bazel-apollo/$lib" ]; then
    found="YES"
    location="/apollo/bazel-apollo/$lib"
  fi

  if [ "$found" = "YES" ]; then
    printf "[OK]   %-25s %s\n" "$name" "$location"
  else
    printf "[MISS] %-25s %s\n" "$name" "$lib"
  fi
done

echo ''
echo '============================================='
echo '  Currently Running Modules'
echo '============================================='
ps aux | grep mainboard | grep -v grep | awk '{
  for(i=11;i<=NF;i++) printf "%s ", $i;
  print ""
}'
