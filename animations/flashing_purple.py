import asyncio
import time
from utils import SharedState
from shape import Shape

async def animate(
        shape: Shape,
        stop_event: asyncio.Event,
        state: SharedState
    ) -> None:
    
    num_steps = 100
    layer_ratio = num_steps / len(shape.layers)
    reverse_start_step = num_steps - 1
    minimum_intensity = 50
    frame_time_ms = 1000/20
    
    # Framerate tracking variables
    total_frames = 0
    start_time = time.time()
    
    async def process_animation_step(step_index):
        nonlocal total_frames
        frame_start = time.time_ns()
        
        distances = (await state.get()).get("distances")
        
        # First pass - set base colors
        for j in range(len(shape.layers)):
            layer_location = j * layer_ratio
            distance = int(abs(step_index - layer_location))
            intensity = max(minimum_intensity, 255 - distance*30)
            for face in shape.layers[j]:
                sensor_temp = max([distances[i][1] for i in shape.face_to_sensors[face]] + [0])
                face_color = (intensity, 0, int(intensity*((255-sensor_temp)/255)))
                shape.set_face_color(face, face_color)
        
        shape.write()
        
        # Frame timing
        frame_duration_ns = time.time_ns() - frame_start
        frame_duration_ms = frame_duration_ns / 1_000_000
        sleep_time_ms = max(0, int(frame_time_ms - frame_duration_ms))
        await asyncio.sleep_ms(sleep_time_ms)
        
        total_frames += 1
    
    step = 0
    direction = 1
    
    while not stop_event.is_set():
        await process_animation_step(step)

        step += direction
        if step >= num_steps:
            step = reverse_start_step
            direction = -1
        elif step < 0:
            step = 0
            direction = 1
            
        # Calculate and print framerate every 100 frames
        if total_frames % 100 == 0:
            elapsed_time = time.time() - start_time
            fps = total_frames / elapsed_time
            print(f"Average FPS: {fps:.2f}")

