import asyncio
import math
import random
import time
from animations.utils import get_all_colors
from utils import SharedState
from shape import Shape

# Physics parameters
G = 8.0  # m/s² (acts in -z_orb direction, which is vertical)
INITIAL_VX_ORB = 0.5  # m/s
INITIAL_VZ_ORB_VERTICAL = 2.0  # m/s
DT = 0.05  # 1/20 s
FRAME_TIME_MS = int(DT * 1000)

# Animation parameters
ORB_BASE_COLOR_CYCLE_TIME_S = 5.0  # Time between orb color changes
ORB_Y_DEPTH = 0.5  # Fixed y-depth for orb
ORB_MAX_EFFECT_DISTANCE = 1.0  # Maximum distance at which orb affects faces

# Sensor parameters
SENSOR_DIST_FOR_MAX_FREQ = 50  # mm (sensor units, e.g., object at 50mm for max frequency)
SENSOR_DIST_FOR_MIN_FREQ = 200  # mm (sensor units, e.g., object at 200mm for min frequency)
PULSE_FREQ_MIN_HZ = 0.5  # Minimum pulse frequency in Hz
PULSE_FREQ_MAX_HZ = 2.0  # Maximum pulse frequency in Hz
MAX_SENSOR_DISTANCE_MM = 255

def step_orb_motion(x_orb, z_orb_vertical, vx_orb, vz_orb_vertical):
    """
    Advance the orb's position and velocity by one time slice (DT).
    Handles bounces and resets based on predefined boundaries.
    Matches parabola.py's physics logic, with z_orb_vertical being the vertical axis.
    """
    # 1. Integrate motion for DT
    x_orb += vx_orb * DT
    z_orb_vertical += vz_orb_vertical * DT - 0.5 * G * DT * DT
    vz_orb_vertical -= G * DT

    # 2. Check for contact with the "ground" (z_orb_vertical <= 0) and boundaries (x_orb)
    if z_orb_vertical <= 0.0:
        if x_orb <= 0.0:  # Hit ground on left side or overshoot
            x_orb, z_orb_vertical = 0.0, 0.0
            vx_orb, vz_orb_vertical = INITIAL_VX_ORB, INITIAL_VZ_ORB_VERTICAL
        elif x_orb >= 1.0:  # Hit ground on right side or overshoot
            x_orb, z_orb_vertical = 1.0, 0.0
            vx_orb, vz_orb_vertical = -INITIAL_VX_ORB, INITIAL_VZ_ORB_VERTICAL
        else:  # Landed on the ground within x boundaries
            z_orb_vertical = 0.0
            vz_orb_vertical = INITIAL_VZ_ORB_VERTICAL  # Bounce with initial velocity

    return x_orb, z_orb_vertical, vx_orb, vz_orb_vertical

def interpolate_colors(color1, color2, factor):
    """Interpolate between two colors based on a factor (0 to 1)."""
    r1, g1, b1 = color1
    r2, g2, b2 = color2
    r = int(r1 + (r2 - r1) * factor)
    g = int(g1 + (g2 - g1) * factor)
    b = int(b1 + (b2 - b1) * factor)
    return (r, g, b)

def get_pulse_frequency(distance_mm):
    """Convert sensor distance to pulse frequency."""
    # Clamp distance to valid range
    distance_mm = max(SENSOR_DIST_FOR_MAX_FREQ, min(distance_mm, SENSOR_DIST_FOR_MIN_FREQ))
    
    # Normalize distance to 0-1 range (inverted so closer = higher value)
    dist_factor = 1.0 - ((distance_mm - SENSOR_DIST_FOR_MAX_FREQ) / 
                        (SENSOR_DIST_FOR_MIN_FREQ - SENSOR_DIST_FOR_MAX_FREQ))
    
    # Interpolate between min and max frequency
    return PULSE_FREQ_MIN_HZ + (PULSE_FREQ_MAX_HZ - PULSE_FREQ_MIN_HZ) * dist_factor

async def animate(
    shape: Shape,
    stop_event: asyncio.Event,
    state: SharedState
) -> None:
    all_colors = get_all_colors()
    if not all_colors:
        all_colors = [(100, 100, 100)]  # Fallback color
    
    # Shuffle all_colors for variety each time animation starts (Fisher-Yates shuffle)
    n = len(all_colors)
    if n > 1:  # No need to shuffle if 0 or 1 elements
        for i in range(n - 1, 0, -1):
            j = random.randint(0, i)  # random.randint is inclusive for both ends
            all_colors[i], all_colors[j] = all_colors[j], all_colors[i]

    current_orb_color_index = 0
    # Determine initial pulse target color index
    # Ensure it's different if possible, otherwise it will be the same if only one color exists
    current_pulse_target_color_index = (current_orb_color_index + 1) % len(all_colors)
    
    orb_base_color = all_colors[current_orb_color_index]
    pulse_target_color = all_colors[current_pulse_target_color_index]
    
    last_orb_color_change_time_ms = time.ticks_ms()

    # Initialize orb state
    orb_x, orb_z_vertical = 0.0, 0.01  # Start slightly above ground
    vx_orb, vz_orb_vertical = INITIAL_VX_ORB, INITIAL_VZ_ORB_VERTICAL
    
    # Initialize face states
    face_pulse_phases = [0.0] * shape.num_faces
    face_pulse_freqs = [PULSE_FREQ_MIN_HZ] * shape.num_faces
    face_colors = [(0, 0, 0)] * shape.num_faces
    face_target_colors = [(0, 0, 0)] * shape.num_faces
    color_transition_factors = [0.0] * shape.num_faces
    
    while not stop_event.is_set():
        frame_start = time.ticks_ms()
        
        # Get sensor data
        sensor_data = (await state.get()).get("distances", [])
        
        # Update orb physics
        orb_x, orb_z_vertical, vx_orb, vz_orb_vertical = step_orb_motion(
            orb_x, orb_z_vertical, vx_orb, vz_orb_vertical
        )
        
        # Check for orb color change
        current_time_ms = time.ticks_ms()
        if time.ticks_diff(current_time_ms, last_orb_color_change_time_ms) >= ORB_BASE_COLOR_CYCLE_TIME_S * 1000:
            # Update color indices
            current_orb_color_index = (current_orb_color_index + 1) % len(all_colors)
            current_pulse_target_color_index = (current_pulse_target_color_index + 1) % len(all_colors)
            
            # Update colors
            orb_base_color = all_colors[current_orb_color_index]
            pulse_target_color = all_colors[current_pulse_target_color_index]
            
            last_orb_color_change_time_ms = current_time_ms
        
        # Calculate frame time delta
        dt = time.ticks_diff(frame_start, time.ticks_ms()) / 1000.0  # Convert to seconds
        
        # Update each face
        for face_idx in range(shape.num_faces):
            face_pos = shape.face_positions[face_idx]
            
            # Calculate distance from orb to face
            dist_sq = ((orb_x - face_pos[0])**2 + 
                      (orb_z_vertical - face_pos[1])**2 + 
                      (ORB_Y_DEPTH - face_pos[2])**2)
            dist = math.sqrt(dist_sq)
            
            # Calculate orb influence (inverse of distance, clamped)
            orb_factor = max(0.0, min(1.0, 1.0 - dist / ORB_MAX_EFFECT_DISTANCE))
            
            # Get sensor data for this face
            max_temp = 0
            min_sensor_dist = MAX_SENSOR_DISTANCE_MM
            if face_idx < len(shape.face_to_sensors):
                for sensor_idx in shape.face_to_sensors[face_idx]:
                    if (sensor_idx < len(sensor_data) and 
                        sensor_data[sensor_idx] is not None):
                        sensor_dist, sensor_temp = sensor_data[sensor_idx]
                        if sensor_temp is not None:
                            max_temp = max(max_temp, sensor_temp)
                        if sensor_dist is not None:
                            min_sensor_dist = min(min_sensor_dist, sensor_dist)
            
            # Update pulse frequency based on closest sensor distance
            face_pulse_freqs[face_idx] = get_pulse_frequency(min_sensor_dist)
            
            # Update pulse phase
            face_pulse_phases[face_idx] += face_pulse_freqs[face_idx] * 2 * math.pi * dt
            face_pulse_phases[face_idx] %= (2 * math.pi)
            
            # Calculate pulse factor (0 to 1)
            pulse_factor = 0.5 + 0.5 * math.sin(face_pulse_phases[face_idx])
            
            # Calculate target color based on orb and sensor influence
            orb_influenced_color = interpolate_colors(orb_base_color, pulse_target_color, orb_factor)
            
            # Factor in temperature
            temp_factor = max_temp / 255.0  # Normalize to 0-1
            target_color = interpolate_colors(
                orb_influenced_color,
                pulse_target_color,
                temp_factor * pulse_factor
            )
            
            # Smooth transition to target color
            transition_speed = 0.1  # Adjust for faster/slower transitions
            color_transition_factors[face_idx] += transition_speed
            if color_transition_factors[face_idx] > 1.0:
                color_transition_factors[face_idx] = 1.0
                face_colors[face_idx] = face_target_colors[face_idx]
                face_target_colors[face_idx] = target_color
                color_transition_factors[face_idx] = 0.0
            
            # Interpolate between current and target color
            if face_colors[face_idx] == (0, 0, 0):  # Initial state
                final_color = target_color
                face_colors[face_idx] = target_color
            else:
                final_color = interpolate_colors(
                    face_colors[face_idx],
                    face_target_colors[face_idx],
                    color_transition_factors[face_idx]
                )
            
            # Set the face color
            shape.set_face_color(face_idx, final_color)
        
        # Update LEDs
        shape.write()
        
        # Frame timing
        frame_duration = time.ticks_diff(time.ticks_ms(), frame_start)
        await asyncio.sleep_ms(max(10, FRAME_TIME_MS - frame_duration)) 