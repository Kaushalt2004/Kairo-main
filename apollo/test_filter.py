import carla
c = carla.Client('172.31.128.1', 2000)
c.set_timeout(10.0)
world = c.get_world()
print("All actors:", len(world.get_actors()))
cams = world.get_actors().filter('sensor.camera.rgb')
print("Cameras found by filter:", len(cams))
