import asyncio
import time
import math
from utils import SharedState
from shape import Shape

RAINBOW_COLORS = [
    (255, 0, 0), # Red
    (255, 127, 0), # Orange
    (255, 255, 0), # Yellow
    (0, 255, 0), # Green
    (0, 255, 255), # Cyan
    (0, 0, 255), # Blue
    (127, 0, 255), # Violet
]
COLOR_CHANGE_INTERVAL = 300
FRAME_TIME = 50

# Temperature thresholds and frequency scaling for pulsing
TEMP_MIN_PULSE = 30  # Temp at which pulsing starts
FREQ_HZ_MIN = 1/3  # Frequency (Hz) at TEMP_MIN_PULSE
FREQ_HZ_MAX = 2.0  # Frequency (Hz) at TEMP_MAX_SENSOR_VAL
TEMP_MAX_SENSOR_VAL = 255  # Max value for temperature from sensor (0-255 range)
BASE_BRIGHTNESS = 0.5  # Default brightness for faces with no pulse

def interpolate_colors(color1: tuple[int, int, int], color2: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Smoothly interpolate between two colors."""
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
    # Initial fill with 0.5 brightness of the first rainbow color
    initial_base_color = RAINBOW_COLORS[0]
    initial_bright_color = tuple(int(c * BASE_BRIGHTNESS) for c in initial_base_color)
    shape.fill(initial_bright_color)
    shape.write()
    
    # Animation state
    current_color_index = 0
    last_color_sweep_time_ms = time.ticks_ms()
    
    # Phase for brightness oscillation for each face (radians)
    face_phases = [0.0] * shape.num_faces
    face_frequencies = [FREQ_HZ_MIN] * shape.num_faces
    
    # Color transition state for each face
    face_colors = [initial_bright_color] * shape.num_faces
    face_target_colors = [initial_bright_color] * shape.num_faces
    color_transition_progress = [1.0] * shape.num_faces
    
    # Variables for the rainbow color sweep effect
    current_layer_for_sweep = 0
    current_face_in_layer_for_sweep = 0
    
    # Animation loop timing
    last_frame_time = time.ticks_ms()
    
    while not stop_event.is_set():
        frame_start_ms = time.ticks_ms()
        
        # Calculate frame time delta in seconds
        dt_seconds = time.ticks_diff(frame_start_ms, last_frame_time) / 1000.0
        last_frame_time = frame_start_ms
        
        # Get sensor data
        sensor_readings_tuples = (await state.get()).get("distances", [])
        
        # Logic for sweeping base rainbow colors across layers/faces
        if time.ticks_diff(frame_start_ms, last_color_sweep_time_ms) > COLOR_CHANGE_INTERVAL:
            if (current_layer_for_sweep == len(shape.layers) - 1 and
                current_face_in_layer_for_sweep == len(shape.layers[current_layer_for_sweep]) - 1):
                current_layer_for_sweep = 0
                current_face_in_layer_for_sweep = 0
                current_color_index = (current_color_index + 1) % len(RAINBOW_COLORS)
            elif current_face_in_layer_for_sweep == len(shape.layers[current_layer_for_sweep]) - 1:
                current_layer_for_sweep += 1
                current_face_in_layer_for_sweep = 0
            else:
                current_face_in_layer_for_sweep += 1
            last_color_sweep_time_ms = frame_start_ms
        
        # Process each face in each layer
        for layer_idx, layer_content in enumerate(shape.layers):
            for face_idx_in_layer, actual_face_idx in enumerate(layer_content):
                # Determine base color based on sweep progression
                if (layer_idx < current_layer_for_sweep or
                    (layer_idx == current_layer_for_sweep and 
                     face_idx_in_layer <= current_face_in_layer_for_sweep)):
                    target_base_color = RAINBOW_COLORS[(current_color_index + 1) % len(RAINBOW_COLORS)]
                else:
                    target_base_color = RAINBOW_COLORS[current_color_index]
                
                # Get maximum temperature from sensors for this face
                face_temp = 0
                if actual_face_idx < len(shape.face_to_sensors):
                    for sensor_idx in shape.face_to_sensors[actual_face_idx]:
                        if (sensor_idx < len(sensor_readings_tuples) and 
                            sensor_readings_tuples[sensor_idx] is not None and
                            sensor_readings_tuples[sensor_idx][1] is not None):
                            face_temp = max(face_temp, sensor_readings_tuples[sensor_idx][1])
                
                # Update face frequency based on temperature
                pulse_active = False
                frequency_hz = FREQ_HZ_MIN
                
                if face_temp >= TEMP_MIN_PULSE:
                    pulse_active = True
                    # Clamp temperature for frequency calculation
                    clamped_temp = min(face_temp, TEMP_MAX_SENSOR_VAL)
                    
                    # Calculate normalized temperature factor
                    if TEMP_MAX_SENSOR_VAL > TEMP_MIN_PULSE:
                        temp_factor = (clamped_temp - TEMP_MIN_PULSE) / (TEMP_MAX_SENSOR_VAL - TEMP_MIN_PULSE)
                        frequency_hz = FREQ_HZ_MIN + (FREQ_HZ_MAX - FREQ_HZ_MIN) * temp_factor
                
                # Update face frequency
                face_frequencies[actual_face_idx] = frequency_hz
                
                # Update phase for pulsing effect
                if pulse_active:
                    face_phases[actual_face_idx] += 2 * math.pi * frequency_hz * dt_seconds
                    face_phases[actual_face_idx] %= (2 * math.pi)
                    brightness_factor = 0.75 + 0.25 * math.sin(face_phases[actual_face_idx])
                else:
                    brightness_factor = BASE_BRIGHTNESS
                
                # Calculate final color with brightness modulation
                base_color = target_base_color
                
                # Add subtle glow to zero channels based on brightness
                glow_value = int((brightness_factor - BASE_BRIGHTNESS) * 50.0)
                final_color = []
                for channel_value in base_color:
                    if channel_value == 0:
                        # Add glow to dark channels
                        final_value = glow_value
                    else:
                        # Scale bright channels by brightness
                        final_value = int(channel_value * brightness_factor)
                    final_color.append(max(0, min(255, final_value)))
                
                # Smooth transition to new color
                if color_transition_progress[actual_face_idx] >= 1.0:
                    face_colors[actual_face_idx] = face_target_colors[actual_face_idx]
                    face_target_colors[actual_face_idx] = tuple(final_color)
                    color_transition_progress[actual_face_idx] = 0.0
                
                # Interpolate between current and target colors
                transition_speed = 0.1
                color_transition_progress[actual_face_idx] += transition_speed
                color_transition_progress[actual_face_idx] = min(1.0, color_transition_progress[actual_face_idx])
                
                current_color = face_colors[actual_face_idx]
                target_color = face_target_colors[actual_face_idx]
                
                display_color = interpolate_colors(
                    current_color,
                    target_color,
                    color_transition_progress[actual_face_idx]
                )
                
                # Set the face color
                shape.set_face_color(actual_face_idx, display_color)
        
        # Write all LED changes to the strip
        shape.write()
        
        # Frame timing
        frame_duration = time.ticks_diff(time.ticks_ms(), frame_start_ms)
        await asyncio.sleep_ms(max(10, FRAME_TIME - frame_duration))
            

