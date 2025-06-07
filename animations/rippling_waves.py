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
COLOR_TRANSITION_TIME_MS = 2000  # Time to transition between base colors

# Ripple effect constants
RIPPLE_DECAY_RATE = 0.95  # Slower decay for more visible propagation
RIPPLE_PROPAGATION_RATE = 0.7  # Reduced to prevent infinite circulation
MAX_RIPPLE_INTENSITY = 1.0  # Full intensity
MIN_TEMP_THRESHOLD = 40  # Temperature threshold on 0-255 scale
MAX_TEMP = 255  # Maximum temperature value (full sensor range)
TEMP_SENSITIVITY = 0.3  # How much of the range above threshold triggers full intensity
BASE_COLOR_DIMMING = 0.6  # Much dimmer base state for contrast
RIPPLE_PULSE_FREQ = 1.0  # Faster pulses
DEBUG_PRINT_INTERVAL_MS = 500  # Only print debug every 500ms to avoid spam

class RippleState:
    def __init__(self, num_faces: int):
        self.intensities = [0.0] * num_faces  # Ripple intensity per face
        self.target_intensities = [0.0] * num_faces  # Target intensity for smooth transitions
        self.phase = 0.0  # Phase for pulsing effect
        self.propagation_phase = 0.0  # Separate phase for propagation effect
        self.active_sensors = [False] * num_faces  # Tracks which faces have active sensors
        self.propagation_levels = [0] * num_faces  # Tracks how many steps away from sensor
        self.last_debug_print = 0  # Track last debug print time
        self.prev_sensor_temps = [0.0] * num_faces  # Previous temperature readings
        self.propagation_sources = [set() for _ in range(num_faces)]  # Track propagation sources

def get_adjacent_faces_in_layer(face_index: int, layers: tuple[tuple[int, ...], ...]) -> list[int]:
    """Find adjacent faces in the same layer as the given face."""
    for layer in layers:
        if face_index in layer:
            layer_list = list(layer)
            face_pos = layer_list.index(face_index)
            adjacent = []
            
            # Check left neighbor (wrap around)
            left_pos = (face_pos - 1) % len(layer)
            adjacent.append(layer_list[left_pos])
            
            # Check right neighbor (wrap around)
            right_pos = (face_pos + 1) % len(layer)
            adjacent.append(layer_list[right_pos])
            
            return adjacent
    return []

def interpolate_colors(color1: tuple[int, int, int], color2: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Smoothly interpolate between two colors."""
    r1, g1, b1 = color1
    r2, g2, b2 = color2
    r = int(r1 + (r2 - r1) * factor)
    g = int(g1 + (g2 - g1) * factor)
    b = int(b1 + (b2 - b1) * factor)
    return (r, g, b)

def apply_ripple_to_color(
    base_color: tuple[int, int, int],
    ripple_intensity: float,
    sensor_phase: float,
    propagation_phase: float,
    has_active_sensor: bool,
    propagation_level: int
) -> tuple[int, int, int]:
    """Modify color based on ripple intensity with out-of-phase propagation."""
    # Get the original color values
    r_orig, g_orig, b_orig = base_color
    
    if ripple_intensity > 0:
        if has_active_sensor:
            # Sensor faces pulse between BASE_COLOR_DIMMING and 1.0
            sine_component = (0.5 + 0.5 * math.sin(sensor_phase))  # Varies between 0 and 1
            # Scale between BASE_COLOR_DIMMING and 1.0
            final_intensity = BASE_COLOR_DIMMING + (1.0 - BASE_COLOR_DIMMING) * sine_component * ripple_intensity
            # Ensure we never go below BASE_COLOR_DIMMING
            final_intensity = max(BASE_COLOR_DIMMING, final_intensity)
            
            # Scale up to original color values
            r = int(r_orig * final_intensity)
            g = int(g_orig * final_intensity)
            b = int(b_orig * final_intensity)
        else:
            # Adjacent faces pulse with offset phase based on propagation level
            phase_offset = propagation_phase + (math.pi * propagation_level / 2)
            sine_component = (0.5 + 0.5 * math.sin(phase_offset))  # Varies between 0 and 1
            # Scale between BASE_COLOR_DIMMING and 1.0
            final_intensity = BASE_COLOR_DIMMING + (1.0 - BASE_COLOR_DIMMING) * sine_component * ripple_intensity
            # Ensure we never go below BASE_COLOR_DIMMING
            final_intensity = max(BASE_COLOR_DIMMING, final_intensity)
            
            # Scale up to original color values
            r = int(r_orig * final_intensity)
            g = int(g_orig * final_intensity)
            b = int(b_orig * final_intensity)
    else:
        # When no ripple, use the dimmed base state
        r = int(r_orig * BASE_COLOR_DIMMING)
        g = int(g_orig * BASE_COLOR_DIMMING)
        b = int(b_orig * BASE_COLOR_DIMMING)
    
    # Ensure values are within valid range
    return (
        max(0, min(255, r)),
        max(0, min(255, g)),
        max(0, min(255, b))
    )

async def animate(
    shape: Shape,
    stop_event: asyncio.Event,
    state: SharedState
) -> None:
    # Initialize ripple state
    ripple = RippleState(shape.num_faces)
    
    # Get all available colors and randomly select two
    colors = get_all_colors()
    if not colors:
        colors = [(255, 0, 255)]  # Fallback to purple if no colors available
    
    # Shuffle colors for variety
    n = len(colors)
    for i in range(n - 1, 0, -1):
        j = random.randint(0, i)
        colors[i], colors[j] = colors[j], colors[i]
    
    current_color_idx = 0
    next_color_idx = 1
    color_transition_start = time.ticks_ms()
    
    # Animation timing variables
    last_frame_time = time.ticks_ms()
    frame_count = 0
    
    while not stop_event.is_set():
        frame_start = time.ticks_ms()
        frame_count += 1
        
        # Get sensor data
        sensor_data = (await state.get()).get("distances", [])
        
        # Update phases
        dt = time.ticks_diff(frame_start, last_frame_time) / 1000.0  # Convert to seconds
        ripple.phase += RIPPLE_PULSE_FREQ * 2 * math.pi * dt
        ripple.propagation_phase += (RIPPLE_PULSE_FREQ * 0.7) * 2 * math.pi * dt
        last_frame_time = frame_start
        
        # Update color transition
        elapsed = time.ticks_diff(frame_start, color_transition_start)
        if elapsed >= COLOR_TRANSITION_TIME_MS:
            current_color_idx = next_color_idx
            next_color_idx = (next_color_idx + 1) % len(colors)
            color_transition_start = frame_start
            elapsed = 0
            
        transition_factor = elapsed / COLOR_TRANSITION_TIME_MS
        base_color = interpolate_colors(
            colors[current_color_idx],
            colors[next_color_idx],
            transition_factor
        )
        
        # Reset tracking arrays
        ripple.active_sensors = [False] * shape.num_faces
        ripple.propagation_levels = [0] * shape.num_faces
        
        # Process sensor data and update ripple targets
        active_faces_info = []  # Collect info about active faces for debug printing
        for face_idx in range(shape.num_faces):
            # Decay current ripple intensity
            ripple.intensities[face_idx] *= RIPPLE_DECAY_RATE
            
            # Check sensors for this face
            if face_idx < len(shape.face_to_sensors):
                max_temp = 0
                active_sensors = []
                for sensor_idx in shape.face_to_sensors[face_idx]:
                    if sensor_idx < len(sensor_data) and sensor_data[sensor_idx] is not None:
                        temp = sensor_data[sensor_idx][1]  # Get temperature value
                        if temp is not None and temp > max_temp:
                            max_temp = temp
                            active_sensors.append((sensor_idx, temp))
                
                # Update ripple target and active sensor status if temperature exceeds threshold
                if max_temp > MIN_TEMP_THRESHOLD:
                    # Calculate normalized temp with higher sensitivity
                    normalized_temp = min(1.0, (max_temp - MIN_TEMP_THRESHOLD) / (TEMP_SENSITIVITY * (MAX_TEMP - MIN_TEMP_THRESHOLD)))
                    ripple.target_intensities[face_idx] = normalized_temp * MAX_RIPPLE_INTENSITY
                    ripple.active_sensors[face_idx] = True
                    
                    # Collect debug info
                    active_faces_info.append((face_idx, max_temp, active_sensors))
                    
                    # Propagate to adjacent faces
                    adjacent_faces = get_adjacent_faces_in_layer(face_idx, shape.layers)
                    for adj_face in adjacent_faces:
                        if adj_face != face_idx:  # Don't propagate to self
                            # Calculate propagation intensity based on distance
                            propagation_intensity = ripple.target_intensities[face_idx] * RIPPLE_PROPAGATION_RATE
                            
                            # Update target intensity if propagation is stronger
                            if propagation_intensity > ripple.target_intensities[adj_face]:
                                ripple.target_intensities[adj_face] = propagation_intensity
                                ripple.propagation_levels[adj_face] = ripple.propagation_levels[face_idx] + 1
                                ripple.propagation_sources[adj_face].add(face_idx)
                    
                    # Debug print active faces and their temperatures periodically
                    current_time = time.ticks_ms()
                    if time.ticks_diff(current_time, ripple.last_debug_print) > DEBUG_PRINT_INTERVAL_MS:
                        ripple.last_debug_print = current_time
                        if active_faces_info:
                            print("Active faces:", ", ".join(
                                f"Face {face_idx} (temp: {temp:.1f}, sensors: {sensors})"
                                for face_idx, temp, sensors in active_faces_info
                            ))
            
            # Smooth transition to target intensity
            intensity_diff = ripple.target_intensities[face_idx] - ripple.intensities[face_idx]
            if abs(intensity_diff) > 0.01:  # Only adjust if difference is significant
                ripple.intensities[face_idx] += intensity_diff * 0.1  # Smooth transition factor
            
            # Apply ripple effect to color
            final_color = apply_ripple_to_color(
                base_color,
                ripple.intensities[face_idx],
                ripple.phase,
                ripple.propagation_phase,
                ripple.active_sensors[face_idx],
                ripple.propagation_levels[face_idx]
            )
            
            # Set the face color
            shape.set_face_color(face_idx, final_color)
        
        # Write all changes to strip
        shape.write()
        
        # Frame timing
        frame_duration = time.ticks_diff(time.ticks_ms(), frame_start)
        await asyncio.sleep_ms(max(10, FRAME_TIME_MS - frame_duration)) 