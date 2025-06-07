import machine, neopixel
import time
import asyncio
from typing import TypeVar, Generic, Callable, Optional, Dict, Any, TYPE_CHECKING
from copy import deepcopy
import sys

if TYPE_CHECKING:
    from types import ModuleType

from pathlib import Path
from utils import SharedState
from wifi_client import connect_to_wifi, fetch_animation_data, is_wifi_connected, listen_for_udp_state, maintain_connection
from animations import ANIMATIONS
from read_sensor import read_sensor, TempratureSettings
from shape import Shape

USE_SOCKET_SERVER = False  # Set to False to use UDP instead of TCP

def get_shape(file_path: Path) -> tuple[int, int, tuple[tuple[int, ...], ...]]:
    data = json.loads(file_path.read_text())
    
    leds_per_face = data.get('led_per_face')
    faces_data = data.get('faces')
    sensors = data.get('sensors')
    sensors_to_face = [[face for face in range(len(faces_data)) if i in faces_data[face]['sensors']] for i in range(sensors)]
    face_to_sensors = [face['sensors'] for face in faces_data]
    face_positions = [face['pos'] for face in faces_data]

    if leds_per_face is None or faces_data is None:
        raise ValueError(f"Invalid shape data in {file_path}")

    num_faces = len(faces_data)
    layers_map = get_layers(faces_data)
    return leds_per_face, num_faces, layers_map, sensors_to_face, face_to_sensors, face_positions


def set_face_color(np, leds_per_face, face_index, color):
    face_offset = leds_per_face * face_index
    for i in range(leds_per_face):
        np[face_offset + i] = color


def get_animations() -> dict[str, 'ModuleType']:
    return {name: getattr(__import__(f'animations.{name}'), name) for name in ANIMATIONS}


async def run_animations(
        shape: Shape,
        state: SharedState
    ) -> None:
    temp_settings = TempratureSettings()

    animations = get_animations()
    async def start_animation(animation_name: str) -> None:
        stop_event = asyncio.Event()
        temp_settings.set_values_to_default()
        task = asyncio.create_task(animations[animation_name].animate(
            shape, stop_event, state
            ))
        return task, stop_event
    
    if Path('force_animation.txt').exists():
        force_animation = Path('force_animation.txt').read_text().strip()
        print(f"Forcing animation: {force_animation}")
        task, stop_event = await start_animation(force_animation)
        await asyncio.gather(task)

    current_animation = list(animations.keys())[0]
    task, stop_event = await start_animation(current_animation)
    while True:
        try:
            new_animation = (await state.get()).get('animation')
            if new_animation is not None:
                if new_animation != current_animation and new_animation in animations:
                    current_animation = new_animation
                    if task is not None:
                        stop_event.set()
                        await asyncio.gather(task)
                    task, stop_event = await start_animation(new_animation)
            await asyncio.sleep(0.05)
        except Exception as e:
            sys.print_exception(e)
            error_animation(shape)


async def restart_in_30_minutes() -> None:
    await asyncio.sleep(30 * 60)
    print("Restarting after 30 minutes, see you soon!")
    machine.reset()


async def get_animation_name(state: SharedState):
    while True:
        animation_name = await fetch_animation_data()
        if animation_name is None:
            if not await is_wifi_connected():
                await connect_to_wifi()
        else:
            await state.update('animation', animation_name)
            await asyncio.sleep(5)


def error_animation(shape: Shape) -> None:
    try:
        for i in range(3):
            for face in range(shape.num_faces):
                shape.set_face_color(face, (255, 0, 0))
                shape.write()
                time.sleep(0.5)
                shape.set_face_color(face, (0, 0, 0))
                shape.write()
                time.sleep(0.5)
    except Exception as e:
        sys.print_exception(e)


def init_animation(shape: Shape) -> None:
    print("""
       ^     +------+.           /\              _----------_,                 _-_. 
      /|\    |`.    | `.       .'  `.          ,"__         _-:,            _-',^. `-_.
     / | \   |  `+--+---+    .'      `.       /    ""--_--""...:\       ._-' ,'   `.   `-_
    /  |  \  |   |  |   |   <          >     /         |.........\     !`-_._________`-':::
    '-.|.-'  +---+--+.  |    `.      .'     /          |..........\    !   /\        /\::::
              `. |    `.|      `.  .'      /,         _'_........./:   ;  /  \      /..\:::
                `+------+        \/        ! -,    _-"   "-_... ,;;:   ! /    \    /....\::
                                           \   -_-"         "-_/;;;;   !/      \  /......\:
                                            \   \             /;;;;'   ;--.___. \/_.__.--;;
                                             \   \           /;;;;      '-_    `:!;;;;;;;' 
                                              '.  \         /;;;'          `-_, :!;;;''    
                                                "-_\_______/;;'                `-!'      
""")
    for i in range(3):
        color = [0, 0, 0]
        color[i] = 255
        for face in range(shape.num_faces):
            shape.set_face_color(face, tuple(color))
            shape.write()
        time.sleep(1)

def main():
    shape_name = Path('shape.txt').read_text().strip()
    shape = Shape(Path(f'shapes/{shape_name}.json'))

    init_animation(shape)

    initial_state = {
        'animation': None,
        'distances': [(None, 0)] * 5
    }

    state = SharedState(initial_state)
    tasks = []
    tasks.append(run_animations(shape, state))
    tasks.append(maintain_connection())
    if USE_SOCKET_SERVER:
        tasks.append(get_animation_name(state))
    else:
        tasks.append(listen_for_udp_state(state))
    tasks.append(read_sensor(state))
    tasks.append(restart_in_30_minutes())
    asyncio.run(asyncio.gather(*tasks))

if __name__ == '__main__':
    main()

