#!/bin/bash
# 1. Start Apollo Bridge
docker exec -d apollo_dev_kairo_it37 bash -c "source /apollo/cyber/setup.bash && bash /apollo/carla_apollo_bridge/start_bridge_apollo9.sh"

# 1. Start Apollo Autonomous Modules & Dreamview Plus
docker exec -d apollo_dev_kairo_it37 bash -c "bash /apollo/start_pnc_modules.sh"

echo "Modules (Monitor, Routing, Planning, Control) and Dreamview Plus have been started!"
echo "Please open http://localhost:8888"
