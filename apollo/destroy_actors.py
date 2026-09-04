import carla
c = carla.Client('172.31.128.1', 2000)
c.set_timeout(5.0)
world = c.get_world()
for a in world.get_actors():
    if 'vehicle' in a.type_id or 'sensor' in a.type_id:
        a.destroy()
print("All vehicles and sensors destroyed.")
