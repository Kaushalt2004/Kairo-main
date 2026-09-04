#!/bin/bash
# Script to run Kairo API with Apollo Cyber environment
source /apollo/cyber/setup.bash
export PYTHONPATH=/apollo/bazel-bin/cyber/python/internal:/apollo/carla_apollo_bridge:/apollo/carla_apollo_bridge/carla_cyber_bridge:/apollo/bazel-bin:/home/kairo_it37/.cache/bazel/540135163923dd7d5820f3ee4b306b32/execroot/apollo/bazel-out/k8-fastbuild/bin:$PYTHONPATH
export CUDA_VISIBLE_DEVICES=""

cd /apollo/kairo_api
python3 -u main.py
