#!/usr/bin/env python3
"""Repair road widths in CARLA-converted Apollo HD maps.

The CARLA -> Apollo conversion used for these maps writes every lane's
`left_road_sample` / `right_road_sample` equal to the lane's own half width,
so Apollo believes each road is exactly one lane wide. Planning clamps its
path corridor to the road width, which makes every lane change infeasible
("lane change path optimize failed": the corridor never includes the lane
the car is in) and squeezes the corridor on curves.

This rewrites the road samples so the road spans the lane plus its
same-direction neighbours on each side (opposite-direction lanes are left
out on purpose). Lane geometry, topology and ids are untouched, so the
routing map stays valid.

Runs inside the Apollo container (Python 3.6):
    python3 fix_carla_road_width.py /apollo/modules/map/data/carla_town05 [...]
The original base_map.bin/.txt are kept as *.orig_kairo the first time.
Restart planning afterwards so it reloads the map.
"""

import os
import shutil
import sys

sys.path += ['/apollo/bazel-bin', '/apollo']

from google.protobuf import text_format  # noqa: E402
from modules.common_msgs.map_msgs.map_pb2 import Map  # noqa: E402


def lane_width(lane):
    """Average full width of a lane from its own samples."""
    left = [s.width for s in lane.left_sample]
    right = [s.width for s in lane.right_sample]
    if not left or not right:
        return 3.5
    return sum(left) / len(left) + sum(right) / len(right)


def neighbour_width(lanes, lane, side):
    """Total width of the same-direction lanes beyond `lane` on `side`."""
    total, seen = 0.0, {lane.id.id}
    current = lane
    while True:
        ids = (current.left_neighbor_forward_lane_id if side == 'left'
               else current.right_neighbor_forward_lane_id)
        nxt = next((lanes[i.id] for i in ids if i.id in lanes), None)
        if nxt is None or nxt.id.id in seen:
            return total
        seen.add(nxt.id.id)
        total += lane_width(nxt)
        current = nxt


def fix(map_dir):
    path = os.path.join(map_dir, 'base_map.bin')
    if not os.path.exists(path):
        print('%s: no base_map.bin, skipped' % map_dir)
        return
    hd_map = Map()
    with open(path, 'rb') as f:
        hd_map.ParseFromString(f.read())
    lanes = {l.id.id: l for l in hd_map.lane}

    changed = 0
    for lane in hd_map.lane:
        extra_left = neighbour_width(lanes, lane, 'left')
        extra_right = neighbour_width(lanes, lane, 'right')
        if extra_left == 0 and extra_right == 0:
            continue
        del lane.left_road_sample[:]
        del lane.right_road_sample[:]
        for s in lane.left_sample:
            lane.left_road_sample.add(s=s.s, width=s.width + extra_left)
        for s in lane.right_sample:
            lane.right_road_sample.add(s=s.s, width=s.width + extra_right)
        changed += 1

    for name in ('base_map.bin', 'base_map.txt'):
        p = os.path.join(map_dir, name)
        if os.path.exists(p) and not os.path.exists(p + '.orig_kairo'):
            shutil.copy2(p, p + '.orig_kairo')
    with open(path, 'wb') as f:
        f.write(hd_map.SerializeToString())
    txt = os.path.join(map_dir, 'base_map.txt')
    if os.path.exists(txt):
        with open(txt, 'w') as f:
            f.write(text_format.MessageToString(hd_map))
    print('%s: widened the road for %d of %d lanes'
          % (os.path.basename(map_dir.rstrip('/')), changed, len(hd_map.lane)))


if __name__ == '__main__':
    for d in sys.argv[1:]:
        fix(d)
