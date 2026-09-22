import time

from dronekit import VehicleMode, connect

# Connect to the vehicle.
# '127.0.0.1:14550' is a typical connection string for a local simulator (like SITL).
# For a physical drone, it might be a serial port (e.g., '/dev/ttyUSB0') or a UDP address.
print("Connecting to vehicle on: 127.0.0.1:14550")
vehicle = connect('127.0.0.1:14550', wait_ready=True)

def arm_and_takeoff(target_altitude):
    """
    Arms vehicle and fly to a specified target altitude.
    """
    print("Basic pre-arm checks")

    # Wait until the vehicle is ready to be armed.
    # vehicle.is_armable ensures the autopilot has GPS lock and passed system checks.
    while not vehicle.is_armable:
        print(" Waiting for vehicle to initialise...")
        time.sleep(1)

    print("Arming motors")
    # Set the vehicle mode to GUIDED, which is required for autonomous script control.
    # En simuladores a veces rechaza el cambio si no está 100% listo, así que lo intentamos en bucle
    while vehicle.mode.name != 'GUIDED':
        print(" Intentando cambiar a modo GUIDED...")
        vehicle.mode = VehicleMode("GUIDED")
        time.sleep(1)

    # Arm the drone (start the motors turning).
    vehicle.armed = True

    # Loop to confirm the vehicle is actually armed before attempting to take off.
    while not vehicle.armed:
        print(" Waiting for arming...")
        time.sleep(1)

    print("Arming motors")
    time.sleep(2)

    print("Taking off!")
    # Command the drone to take off vertically to the target altitude.
    vehicle.simple_takeoff(target_altitude)

    # Loop to monitor the altitude during ascent.
    while True:
        # Print the current altitude relative to the home location.
        print(" Altitude: ", vehicle.location.global_relative_frame.alt)

        # Check if the current altitude is at least 95% of the target altitude.
        if vehicle.location.global_relative_frame.alt >= target_altitude * 0.95:
            print("Reached target altitude")
            break # Exit the loop once the target is reached.

        # Wait 1 second before checking again.
        time.sleep(1)

# Execute the takeoff function, instructing the drone to climb to 10 meters.
arm_and_takeoff(10)

print("Hovering for 10 seconds...")
# Pause the script for 10 seconds while the drone holds its position.
time.sleep(10)

print("Returning to Launch")
# Change the mode to RTL (Return To Launch) to make the drone fly back to its starting point and land.
vehicle.mode = VehicleMode("RTL")

print("Closing vehicle object")
# Close the connection to the vehicle to free up resources.
vehicle.close()
