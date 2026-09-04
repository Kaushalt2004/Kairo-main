#!/bin/bash
source /apollo/cyber/setup.bash
export LD_LIBRARY_PATH=/apollo/bazel-bin/modules/routing:/apollo/bazel-bin/modules/planning:/apollo/bazel-bin/modules/prediction:/apollo/bazel-bin/modules/localization:/apollo/bazel-bin/modules/common_msgs:/usr/local/lib:$LD_LIBRARY_PATH

echo "Starting Localization..."
nohup cyber_launch start modules/localization/launch/localization.launch > /tmp/loc.log 2>&1 &
sleep 1

echo "Starting Routing..."
nohup cyber_launch start modules/routing/launch/routing.launch > /tmp/routing.log 2>&1 &
sleep 1

echo "Starting Prediction..."
nohup cyber_launch start modules/prediction/launch/prediction.launch > /tmp/pred.log 2>&1 &
sleep 1

echo "Starting Planning..."
nohup cyber_launch start modules/planning/launch/planning.launch > /tmp/plan.log 2>&1 &
sleep 1

echo "All modules launched! Check Dreamview Plus for data."
