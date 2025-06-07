import asyncio
import time
import math
from utils import SharedState
from animations.utils import get_all_colors
from shape import Shape

FRAME_TIME_MS = int(1000/20)
BASE_CHANGE_COLOR_TIME_MS = int(1000/3)

# Maximum possible temperature value from a sensor (used for normalization)
MAX_SENSOR_TEMP_VALUE = 255.0

# Animation constants
SWIRL_SPEED = 0.5  # Rotations per second
TEMPERATURE_SENSITIVITY = 0.7  # How much temperature affects color
COLOR_TRANSITION_SPEED = 0.1  # Speed of color transitions

def interpolate_color(color1: tuple[int, int, int], color2: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Linearly interpolates between two colors."""
    r1, g1, b1 = color1
    r2, g2, b2 = color2
    r = int(r1 + (r2 - r1) * factor)
    g = int(g1 + (g2 - g1) * factor)
    b = int(b1 + (b2 - b1) * factor)
    return (r, g, b)

async def animate(
    shape: Shape,
    stop_event: asyncio.Event,
    state: SharedState
) -> None:
    """
    Creates a swirling color effect that responds to sensor data.
    The animation cycles through available colors, creating smooth transitions
    between them. Sensor data influences the brightness and color mixing.
    """
    # Get available colors
    colors = get_all_colors()
    if not colors:
        colors = [(255, 0, 0)]  # Fallback to red if no colors available
    
    # Animation state
    current_color_idx = 0
    next_color_idx = (current_color_idx + 1) % len(colors)
    swirl_phase = 0.0
    
    # State tracking for each face
    face_colors = [(0, 0, 0)] * shape.num_faces
    face_target_colors = [(0, 0, 0)] * shape.num_faces
    color_transition_progress = [1.0] * shape.num_faces
    face_temperature_factors = [0.0] * shape.num_faces
    face_swirl_offsets = [0.0] * shape.num_faces
    
    # Calculate initial swirl offsets based on face positions
    for face_idx in range(shape.num_faces):
        face_pos = shape.face_positions[face_idx]
        # Calculate angle in XZ plane
        angle = math.atan2(face_pos[2], face_pos[0])
        face_swirl_offsets[face_idx] = angle / (2 * math.pi)
    
    # Animation timing
    last_frame_time = time.ticks_ms()
    last_color_change = last_frame_time
    
    while not stop_event.is_set():
        frame_start = time.ticks_ms()
        
        # Calculate frame time delta
        dt = time.ticks_diff(frame_start, last_frame_time) / 1000.0  # Convert to seconds
        last_frame_time = frame_start
        
        # Update swirl phase
        swirl_phase += SWIRL_SPEED * dt * 2 * math.pi
        swirl_phase %= (2 * math.pi)
        
        # Check if it's time to change colors
        current_time = time.ticks_ms()
        time_since_last_change = time.ticks_diff(current_time, last_color_change)
        
        if time_since_last_change >= BASE_CHANGE_COLOR_TIME_MS:
            # Update color indices
            current_color_idx = next_color_idx
            next_color_idx = (next_color_idx + 1) % len(colors)
            last_color_change = current_time
            time_since_last_change = 0
        
        # Get sensor data
        sensor_data = (await state.get()).get('distances', [])
        
        # Update each face
        for face_idx in range(shape.num_faces):
            # Calculate swirl factor for this face
            swirl_factor = math.sin(swirl_phase + face_swirl_offsets[face_idx] * 2 * math.pi)
            swirl_factor = (swirl_factor + 1) / 2  # Normalize to 0-1
            
            # Get maximum temperature from sensors for this face
            max_temp = 0
            if face_idx < len(shape.face_to_sensors):
                for sensor_idx in shape.face_to_sensors[face_idx]:
                    if (sensor_idx < len(sensor_data) and 
                        sensor_data[sensor_idx] is not None and 
                        sensor_data[sensor_idx][1] is not None):
                        max_temp = max(max_temp, sensor_data[sensor_idx][1])
            
            # Smooth temperature factor transitions
            target_temp_factor = (max_temp / MAX_SENSOR_TEMP_VALUE) * TEMPERATURE_SENSITIVITY
            face_temperature_factors[face_idx] += (target_temp_factor - face_temperature_factors[face_idx]) * 0.1
            
            # Calculate base color transition progress
            color_transition_factor = time_since_last_change / BASE_CHANGE_COLOR_TIME_MS
            
            # Get current and next colors
            current_color = colors[current_color_idx]
            next_color = colors[next_color_idx]
            
            # Calculate base color with swirl effect
            base_color = interpolate_color(current_color, next_color, swirl_factor * color_transition_factor)
            
            # Calculate target color with temperature influence
            temp_factor = face_temperature_factors[face_idx]
            target_color = list(base_color)
            
            # Apply temperature effects
            for i in range(3):
                if target_color[i] == 0:
                    # Add glow to dark channels based on temperature
                    target_color[i] = int(temp_factor * 127)
                else:
                    # Enhance bright channels based on temperature
                    target_color[i] = min(255, int(target_color[i] * (1 + temp_factor)))
            
            target_color = tuple(target_color)
            
            # Smooth transition to new color
            if color_transition_progress[face_idx] >= 1.0:
                face_colors[face_idx] = face_target_colors[face_idx]
                face_target_colors[face_idx] = target_color
                color_transition_progress[face_idx] = 0.0
            
            # Update transition progress
            color_transition_progress[face_idx] += COLOR_TRANSITION_SPEED
            color_transition_progress[face_idx] = min(1.0, color_transition_progress[face_idx])
            
            # Calculate final color
            if face_colors[face_idx] == (0, 0, 0):  # Initial state
                final_color = target_color
                face_colors[face_idx] = target_color
            else:
                final_color = interpolate_color(
                    face_colors[face_idx],
                    face_target_colors[face_idx],
                    color_transition_progress[face_idx]
                )
            
            # Set the face color
            shape.set_face_color(face_idx, final_color)
        
        # Update LEDs
        shape.write()
        
        # Frame timing
        frame_duration = time.ticks_diff(time.ticks_ms(), frame_start)
        await asyncio.sleep_ms(max(10, FRAME_TIME_MS - frame_duration))
