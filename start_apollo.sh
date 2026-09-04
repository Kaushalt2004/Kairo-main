#!/bin/bash
# 1. Start Apollo Bridge
docker exec -d apollo_dev_kairo_it37 bash -c "source /apollo/cyber/setup.bash && bash /apollo/carla_apollo_bridge/start_bridge_apollo9.sh"

# 2. Start Dreamview Plus
docker exec -d apollo_dev_kairo_it37 bash -c "source /apollo/cyber/setup.bash && bash /apollo/scripts/dreamview_plus.sh restart"

echo "Bridge and Dreamview Plus have been started!"
echo "Please open http://localhost:8888"
