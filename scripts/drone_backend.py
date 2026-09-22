import math
import time

from dronekit import LocationGlobalRelative, VehicleMode, connect

# Connect to the vehicle.
# '127.0.0.1:14550' is a typical connection string for a local simulator (like SITL).
# For a physical drone, it might be a serial port (e.g., '/dev/ttyUSB0') or a UDP address.
print("Connecting to vehicle on: 127.0.0.1:14550")
vehicle = connect("127.0.0.1:14550", wait_ready=True)

print("Disabling Geofence and Pre-arm checks for SITL...")
vehicle.parameters['FENCE_ENABLE'] = 0
vehicle.parameters['ARMING_CHECK'] = 0

def get_location_metres(original_location, dNorth, dEast):
    """
    Devuelve un objeto LocationGlobalRelative con las coordenadas desplazadas
    dNorth y dEast (en metros) desde la posición original.
    """
    earth_radius = 6378137.0 # Radio de la Tierra en metros
    # Desplazamientos en radianes
    dLat = dNorth / earth_radius
    dLon = dEast / (earth_radius * math.cos(math.pi * original_location.lat / 180))

    # Nueva posición en grados decimales
    newlat = original_location.lat + (dLat * 180 / math.pi)
    newlon = original_location.lon + (dLon * 180 / math.pi)
    
    return LocationGlobalRelative(newlat, newlon, original_location.alt)


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
    while vehicle.mode.name != "GUIDED":
        print(" Intentando cambiar a modo GUIDED...")
        # Hack para ArduCopter 3.3: DroneKit envía un comando incorrecto para cambiar de modo.
        # Enviamos el mensaje SET_MODE directamente:
        vehicle._master.mav.set_mode_send(
            vehicle._master.target_system,
            209, # MAV_MODE_FLAG_CUSTOM_MODE_ENABLED (1) | MAV_MODE_FLAG_SAFETY_ARMED (128) | etc
            4    # 4 es el número de modo para GUIDED en ArduCopter
        )
        time.sleep(1)

    # Loop to confirm the vehicle is actually armed before attempting to take off.
    while not vehicle.armed:
        print(" Waiting for arming...")
        vehicle.armed = True
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
            break  # Exit the loop once the target is reached.

        # Wait 1 second before checking again.
        time.sleep(1)


# Execute the takeoff function, instructing the drone to climb to 10 meters.
arm_and_takeoff(10)

print("Hovering for 5 seconds...")
time.sleep(5)

# Crear un waypoint a 350 metros al NORTE y 150 metros al OESTE de la posición actual
current_loc = vehicle.location.global_relative_frame
waypoint1 = get_location_metres(current_loc, dNorth=350, dEast=-150)

print("Navigating to Waypoint 1 (350m North, 150m West)...")
# Usamos simple_goto para mandar al dron a esas coordenadas GPS a su altitud actual
vehicle.simple_goto(waypoint1)

# Esperamos más tiempo para que el dron logre recorrer toda esa distancia
time.sleep(45)

print("Returning to Launch")
# Change the mode to RTL (Return To Launch) to make the drone fly back to its starting point and land.
vehicle._master.mav.set_mode_send(
    vehicle._master.target_system,
    209,
    6 # 6 es el número de modo para RTL en ArduCopter
)

print("Closing vehicle object")
# Close the connection to the vehicle to free up resources.
vehicle.close()
