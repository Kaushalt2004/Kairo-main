import carla
c = carla.Client("172.31.128.1", 2000)
c.set_timeout(5.0)
w = c.get_world()
loc = w.get_map().get_spawn_points()[0].location
print("Spawn 0 is at: X=%f, Y=%f, Z=%f" % (loc.x, loc.y, loc.z))

actors = w.get_actors().filter('vehicle.*')
print("Currently spawned vehicles:")
for a in actors:
    l = a.get_location()
    print("ID %d: %s at X=%f, Y=%f, Z=%f" % (a.id, a.type_id, l.x, l.y, l.z))
