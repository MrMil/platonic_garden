import asyncio
import math
import random
import utime
from utils import SharedState
from shape import Shape

# Physics parameters
G = 4.0  # m/s² (acts in −y)
INITIAL_VX = 1.0  # m/s
INITIAL_VZ = 3.0  # m/s
DT = 0.05  # 1/20 s
FRAME_TIME_MS = int(DT * 1000)

# Animation parameters
SENSOR_INFLUENCE = 0.5  # How much sensor data affects the ball's trajectory
MIN_SENSOR_DISTANCE = 50  # mm
MAX_SENSOR_DISTANCE = 200  # mm

def step(x, z, y, vx, vz):
    """Advance the ball by one time slice (dt) and apply the
    ground/reset rules you specified."""

    # 1. Integrate motion for dt
    x += vx * DT
    z += vz * DT - 0.5 * G * DT * DT
    vz -= G * DT

    # 2. Check for contact with the ground (z ≤ 0)
    if x <= 0:  # left side or overshoot
        x, z, y = 0.0, 0.0, 0.5
        vx, vz = INITIAL_VX, INITIAL_VZ
    elif x >= 1:  # right side or overshoot
        x, z, y = 1.0, 0.0, 0.5
        vx, vz = -INITIAL_VX, INITIAL_VZ
    elif z < -1:  # Reset if ball falls too far
        x, z, y = 0.0, 0.0, 0.5
        vx, vz = INITIAL_VX, INITIAL_VZ

    return x, z, y, vx, vz

async def animate(
        shape: Shape,
        stop_event: asyncio.Event,
        state: SharedState
    ) -> None:
    # Randomly select color channels for different visual elements
    color_channels = list(range(3))
    max_color_channel = color_channels.pop(random.randint(0, len(color_channels) - 1))
    ball_channel = color_channels.pop(random.randint(0, len(color_channels) - 1))
    sensor_channel = color_channels[0]

    # Initialize ball state
    x, z, y = 0.0, 0.0, 0.5
    vx, vz = INITIAL_VX, INITIAL_VZ

    while not stop_event.is_set():
        frame_start = utime.ticks_ms()
        distances = (await state.get()).get('distances', [])

        # Update ball physics
        x, z, y, vx, vz = step(x, z, y, vx, vz)

        # Process each face
        for face_id, face_pos in enumerate(shape.face_positions):
            # Calculate distance from ball to face
            distance = max(0, min(1.0, math.sqrt(
                (x - face_pos[0])**2 + 
                (z - face_pos[1])**2 + 
                (y - face_pos[2])**2
            )))

            # Initialize color array
            color = [0, 0, 0]
            color[max_color_channel] = 255  # Base color channel always at max

            # Ball influence on color (inverse of distance)
            color[ball_channel] = int(255 * (1 - distance))

            # Process sensor data for this face
            if face_id < len(shape.face_to_sensors) and shape.face_to_sensors[face_id]:
                # Get maximum sensor value for this face
                sensor_values = [
                    distances[sensor][1] if (
                        sensor < len(distances) and 
                        distances[sensor] is not None and 
                        distances[sensor][1] is not None
                    ) else 0
                    for sensor in shape.face_to_sensors[face_id]
                ]
                max_sensor = max(sensor_values) if sensor_values else 0
                
                # Apply sensor value to color
                color[sensor_channel] = max_sensor

                # Adjust ball trajectory based on sensor data
                if max_sensor > 0:
                    # Calculate influence factor based on sensor value
                    sensor_factor = min(1.0, max_sensor / 255.0) * SENSOR_INFLUENCE
                    
                    # Apply subtle influence to ball velocity
                    if abs(face_pos[0] - x) > 0.1:  # Only influence if not directly above
                        vx += math.copysign(sensor_factor * DT, face_pos[0] - x)
                    if z > 0:  # Only boost upward velocity when ball is above ground
                        vz += sensor_factor * DT * 2
            else:
                color[sensor_channel] = 0

            # Set face color
            shape.set_face_color(face_id, tuple(color))

        # Update display
        shape.write()

        # Frame timing
        frame_duration = utime.ticks_diff(utime.ticks_ms(), frame_start)
        await asyncio.sleep_ms(max(10, FRAME_TIME_MS - frame_duration))

