import carla
c = carla.Client('172.31.128.1', 2000)
c.set_timeout(10.0)
world = c.get_world()
for a in world.get_actors():
    if 'vehicle' in a.type_id:
        print(a.type_id, a.attributes.get('role_name'))
    if 'sensor' in a.type_id:
        print(a.type_id)
