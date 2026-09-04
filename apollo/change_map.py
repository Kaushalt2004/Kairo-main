import carla
import sys

def main():
    client = carla.Client("172.31.128.1", 2000)
    client.set_timeout(60.0)
    print("Loading Town03...")
    client.load_world('Town03')
    print("Town03 loaded successfully.")

if __name__ == '__main__':
    main()
