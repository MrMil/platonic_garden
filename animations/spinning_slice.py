# animations/spinning_slice.py

import asyncio
import time
import math
import random
from shape import Shape
import neopixel
from utils import SharedState

# --- Vector Math Helpers (same as before) ---
def dot(v1, v2): return v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]
def cross(v1, v2): return [v1[1] * v2[2] - v1[2] * v2[1], v1[2] * v2[0] - v1[0] * v2[2], v1[0] * v2[1] - v1[1] * v2[0]]
def normalize(v):
    mag = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
    if mag == 0: return [0.0, 0.0, 0.0]
    return [v[0] / mag, v[1] / mag, v[2] / mag]
def scale(v, s): return [v[0] * s, v[1] * s, v[2] * s]
def add(v1, v2): return [v1[0] + v2[0], v1[1] + v2[1], v1[2] + v2[2]]

# --- Color Palettes ---
PALETTES = [
    # Pink/Teal
    [(200, 0, 50), (0, 200, 150)],
    # Earthy
    [(139, 69, 19), (0, 100, 0), (230, 100, 0), (34, 139, 34)],
    # Warm (Sunrise/Sunset)
    [(200, 30, 10), (255, 69, 0), (255, 140, 0), (255, 215, 0), (139, 0, 139)],
    # Ocean/Sky
    [(0, 0, 139), (70, 130, 180), (0, 0, 50)],
    # Primary
    [(255, 0, 0), (0, 0, 255), (255, 255, 0), (0, 255, 0)] # R, B, Y, G
]

# --- Animation Constants ---
FPS = 20
FRAME_TIME_MS = int(1000 / FPS)
SECONDS_PER_REVOLUTION = 3
SLICE_WIDTH_DEGREES = 60.0
SLICE_WIDTH_RADIANS = math.radians(SLICE_WIDTH_DEGREES)
TWO_PI = 2 * math.pi
BASE_ANGLE_PER_FRAME = TWO_PI / (SECONDS_PER_REVOLUTION * FPS)

# --- Speed Calculation (same as before) ---
def calculate_speed_factor(temp: int) -> float:
    return  1 + (float(temp) / 255)

async def animate(
        shape: Shape,
        stop_event: asyncio.Event,
        state: SharedState
    ) -> None:
    """
    Main animation function with palettes and speed control.
    """
    face_centers = [[p[0] - 0.5, p[1] - 0.5, p[2] - 0.5] for p in shape.face_positions]
    last_revolution_colors = {}

    # --- Setup Palettes ---
    shuffled_palettes = PALETTES.copy()
    shuffle(shuffled_palettes)
    print(f"Color order: #{shuffled_palettes}")
    colors = [c for pallete in shuffled_palettes for c in pallete]
    current_color_index = 1

    # Get initial colors
    base_color = colors[0]
    slice_color = colors[current_color_index]

    while not stop_event.is_set():
        # --- Setup for new cycle ---
        num_revolutions_target = random.randint(5, 10)
        print(f"Running for {num_revolutions_target} revolutions with slice color {slice_color}")
        chosen_face_center = random.choice(face_centers)
        axis = normalize(chosen_face_center)
        if all(a == 0 for a in axis): axis = [0.0, 0.0, 1.0]

        u = axis
        v_temp = [1.0, 0.0, 0.0]
        if abs(dot(u, v_temp)) > 0.99: v_temp = [0.0, 1.0, 0.0]
        v = normalize(add(v_temp, scale(u, -dot(v_temp, u))))
        w = cross(u, v)

        last_revolution_colors.clear()
        shape.fill(base_color)
        shape.write()

        current_angle = 0.0
        total_angle_turned = 0.0

        # --- Revolution Loop ---
        while abs(total_angle_turned / TWO_PI) < num_revolutions_target:
            if stop_event.is_set(): return
            frame_start_ns = time.time_ns()

            sensor_data = (await state.get()).get("distances", [])
            max_temp = 0
            if sensor_data:
                valid_temps = [temp for _, temp in sensor_data if temp is not None]
                if valid_temps: max_temp = max(valid_temps)
            speed_factor = calculate_speed_factor(max_temp)

            angle_change = BASE_ANGLE_PER_FRAME * speed_factor
            current_angle += angle_change
            total_angle_turned += angle_change
            display_angle = current_angle % TWO_PI

            current_rev_abs = abs(total_angle_turned / TWO_PI)
            is_last_rev = current_rev_abs >= (num_revolutions_target - 1)

            slice_end_angle = display_angle
            slice_start_angle = (slice_end_angle - SLICE_WIDTH_RADIANS + TWO_PI) % TWO_PI

            for face_id, p_center in enumerate(face_centers):
                p_v = dot(p_center, v)
                p_w = dot(p_center, w)
                p_angle = math.atan2(p_w, p_v)
                if p_angle < 0: p_angle += TWO_PI

                in_slice = False
                if slice_start_angle < slice_end_angle:
                    if slice_start_angle <= p_angle <= slice_end_angle: in_slice = True
                else:
                    if slice_start_angle <= p_angle or p_angle <= slice_end_angle: in_slice = True

                if face_id in last_revolution_colors:
                    shape.set_face_color(face_id, last_revolution_colors[face_id])
                elif in_slice:
                    shape.set_face_color(face_id, slice_color)
                    if is_last_rev and speed_factor >= 0:
                        last_revolution_colors[face_id] = slice_color
                else:
                    shape.set_face_color(face_id, base_color)

            shape.write()
            elapsed_ms = (time.time_ns() - frame_start_ns) / 1_000_000
            await asyncio.sleep_ms(max(10, int(FRAME_TIME_MS - elapsed_ms)))
            if speed_factor == 0: await asyncio.sleep_ms(50)

        # --- End of Cycle: Update Colors ---
        base_color = slice_color # Old slice becomes new base
        current_color_index = (current_color_index + 1) % len(colors)
        slice_color = colors[current_color_index]

        shape.fill(base_color)
        shape.write()
        await asyncio.sleep_ms(500)

def shuffle(seq):
    n = len(seq)
    for i in range(n - 1, 0, -1):
        j = random.randint(0, i)
        seq[i], seq[j] = seq[j], seq[i]