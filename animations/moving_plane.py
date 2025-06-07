import asyncio
import time
import math
import random
from animations.utils import get_all_colors
from utils import SharedState
from read_sensor import TempratureSettings
from shape import Shape

# Animation timing constants
FRAME_TIME_MS = int(1000/20)  # 20 FPS
SPEED = 0.5  # Units per second for plane movement
DEBUG_PRINT_INTERVAL_MS = 500  # Print debug info every 500ms

def normalize_vector(v):
    """Normalize a vector to unit length."""
    magnitude = math.sqrt(sum(x*x for x in v))
    if magnitude == 0:
        return (0, 0, 0)
    return tuple(x/magnitude for x in v)

def distance_to_plane(point, plane_point, plane_normal):
    """Calculate signed distance from a point to a plane."""
    # Plane equation: ax + by + cz + d = 0
    # where (a,b,c) is the normal vector and d = -(ax0 + by0 + cz0)
    # for a point (x0,y0,z0) on the plane
    a, b, c = plane_normal
    x0, y0, z0 = plane_point
    d = -(a*x0 + b*y0 + c*z0)
    x, y, z = point
    return abs(a*x + b*y + c*z + d) / math.sqrt(a*a + b*b + c*c)


def interpolate_channel(channel1, channel2, t):
    if t > 1 or t < 0:
        print(f"t is {t}")
        return channel1
    distance = channel1 - channel2
    distance_to_cover = math.floor(distance * t)
    return channel1 - distance_to_cover

def interpolate_colors(color1, color2, t):
    return tuple(interpolate_channel(c1, c2, t) for c1, c2 in zip(color1, color2))

async def animate(
        shape: Shape,
        stop_event: asyncio.Event,
        state: SharedState
    ) -> None:
    temp_settings = TempratureSettings()
    temp_settings.TEMP_DELTA_UP=30
    temp_settings.TEMP_DELTA_DOWN=30
    
    # Get all available colors and randomly select three
    all_colors = get_all_colors()
    # Shuffle the colors list in place
    n = len(all_colors)
    for i in range(n - 1, 0, -1):
        j = random.randint(0, i)
        all_colors[i], all_colors[j] = all_colors[j], all_colors[i]
    
    # Take the first three colors after shuffling
    background_color = all_colors[0]
    foreground_color = all_colors[1]
    sensor_color = all_colors[2]
    
    print("\nSelected colors:")
    print(f"Background: {background_color}")
    print(f"Foreground: {foreground_color}")
    print(f"Sensor: {sensor_color}\n")
    
    # Choose a random point on the bounding box (0,0,0) to (1,1,1)
    # We'll randomly select one coordinate to be either 0 or 1, and others random
    fixed_dim = random.randint(0, 2)  # Choose which dimension will be fixed
    fixed_val = random.randint(0, 1)  # 0 or 1 for the fixed dimension
    
    point = [random.random(), random.random(), random.random()]
    point[fixed_dim] = fixed_val
    
    # Calculate vector towards center (0.5, 0.5, 0.5)
    center = (0.5, 0.5, 0.5)
    direction = normalize_vector((
        center[0] - point[0],
        center[1] - point[1],
        center[2] - point[2]
    ))
    
    print(f"Starting point: ({point[0]:.2f}, {point[1]:.2f}, {point[2]:.2f})")
    print(f"Direction vector: ({direction[0]:.2f}, {direction[1]:.2f}, {direction[2]:.2f})\n")
    
    # Initial plane position is at the chosen point
    plane_point = list(point)
    plane_normal = direction  # Normal vector is the direction vector
    moving_forward = True
    
    # Animation loop
    last_frame_time = time.ticks_ms()
    last_debug_print = last_frame_time
    
    while not stop_event.is_set():
        frame_start = time.ticks_ms()
        
        # Debug printing with rate limiting
        if False and time.ticks_diff(frame_start, last_debug_print) > DEBUG_PRINT_INTERVAL_MS:
            print(f"Plane position: ({plane_point[0]:.2f}, {plane_point[1]:.2f}, {plane_point[2]:.2f})")
            print(f"Moving {'forward' if moving_forward else 'backward'}\n")
            last_debug_print = frame_start
        
        dt = time.ticks_diff(frame_start, last_frame_time) / 1000.0  # Convert to seconds
        last_frame_time = frame_start
        
        # Move the plane
        movement = SPEED * dt
        if not moving_forward:
            movement = -movement
            
        # Update plane position
        plane_point[0] += direction[0] * movement
        plane_point[1] += direction[1] * movement
        plane_point[2] += direction[2] * movement
        
        # Check if plane is completely out of bounding box
        # We consider the plane "out" if its point is significantly outside the box
        out_of_bounds = (
            plane_point[0] < -1 or plane_point[0] > 2 or
            plane_point[1] < -1 or plane_point[1] > 2 or
            plane_point[2] < -1 or plane_point[2] > 2
        )
        
        if out_of_bounds:
            moving_forward = not moving_forward
            # Reset plane position to starting point
            plane_point = list(point if moving_forward else (
                1 - point[0],
                1 - point[1],
                1 - point[2]
            ))
            if False:
                print(f"\nPlane reversed direction! New position: ({plane_point[0]:.2f}, {plane_point[1]:.2f}, {plane_point[2]:.2f})")
        
        # Get sensor data
        sensor_data = (await state.get()).get("distances", [])
        
        # Start timing the calculation phase
        calc_start = time.ticks_ms()
        
        # Update each face's color
        for face_idx in range(shape.num_faces):
            face_pos = shape.face_positions[face_idx]
            
            # Calculate distance to plane
            dist = abs(distance_to_plane(face_pos, plane_point, plane_normal))
            # Clamp distance to 0-1 range
            dist = max(0.0, min(1.0, dist))
            # Interpolate between foreground and background based on distance
            color_by_plane = interpolate_colors(foreground_color, background_color, dist)
            
            # Get maximum temperature for this face
            max_temp = 0
            if face_idx < len(shape.face_to_sensors):
                for sensor_idx in shape.face_to_sensors[face_idx]:
                    if (sensor_idx < len(sensor_data) and 
                        sensor_data[sensor_idx] is not None and 
                        sensor_data[sensor_idx][1] is not None):
                        max_temp = max(max_temp, sensor_data[sensor_idx][1])
            
            # Normalize temperature to 0-1 range
            temp_factor = max_temp / 255.0
            
            # Final color interpolation between plane-based color and sensor color
            final_color = interpolate_colors(color_by_plane, sensor_color, temp_factor)
            
            # Set the face color
            shape.set_face_color(face_idx, final_color)
        
        # Update the LEDs
        shape.write()
        
        # Calculate how long the processing took
        calc_time = time.ticks_diff(time.ticks_ms(), calc_start)
        
        # Calculate remaining time in the frame after processing
        remaining_frame_time = FRAME_TIME_MS - calc_time
        
        # Only sleep if we have time remaining
        await asyncio.sleep_ms(max(10, remaining_frame_time)) 