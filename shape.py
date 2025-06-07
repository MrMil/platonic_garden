from pathlib import Path
import json
from typing import Tuple, List
import neopixel
import machine
import sys

SHAPE_LED_PIN = 18
SMALL_SHAPE_LED_PIN = 13
SMALL_SHAPE_LED_COUNT = 2


class Shape:
    def __init__(self, file_path: Path):
        self.name = file_path.stem  # Gets filename without extension
        data = json.loads(file_path.read_text())
        
        self.leds_per_face = data.get('led_per_face')
        faces_data = data.get('faces')
        sensors = data.get('sensors')
        
        if self.leds_per_face is None or faces_data is None:
            raise ValueError(f"Invalid shape data in {file_path}")
            
        self.num_faces = len(faces_data)
        self.layers = self._get_layers(faces_data)
        self.sensors_to_face = [[face for face in range(len(faces_data)) if i in faces_data[face]['sensors']] for i in range(sensors)]
        self.face_to_sensors = [face['sensors'] for face in faces_data]
        self.face_positions = [face['pos'] for face in faces_data]
        
        # Initialize NeoPixel
        self.np = neopixel.NeoPixel(machine.Pin(SHAPE_LED_PIN, machine.Pin.OUT), self.leds_per_face * self.num_faces)
        self.small_np = neopixel.NeoPixel(machine.Pin(SMALL_SHAPE_LED_PIN, machine.Pin.OUT), SMALL_SHAPE_LED_COUNT)

    def _get_layers(self, shape_faces: List[dict]) -> Tuple[Tuple[int, ...], ...]:
        if not shape_faces:
            return tuple()
        max_layer = max(face['layer'] for face in shape_faces)
        layers = [[] for _ in range(max_layer + 1)]
        for face in shape_faces:
            layers[face['layer']].append((face['face_id'], face['index']))
        
        processed_layers = []
        for layer_list in layers:
            layer_list.sort(key=lambda x: x[1])
            processed_layers.append(tuple(item[0] for item in layer_list))
        return tuple(processed_layers)

    def set_face_color(self, face_index: int, color: Tuple[int, int, int]) -> None:
        """Set all LEDs in a face to a specific color."""
        face_offset = self.leds_per_face * face_index
        for i in range(self.leds_per_face):
            self[face_offset + i] = color
            
    def write(self) -> None:
        """Write the LED buffer to the physical LEDs."""
        try:
            self.np.write()
        except Exception as e:
            sys.print_exception(e)
        
        
        if self.name == "octahedron":
            #  This should work for any shape but the esp32 is slow so we only do it for octahedron
            colors = []
            for face_index in self.layers[0]:
                colors.append(self[self.leds_per_face * face_index])
            color = [0, 0, 0]
            for i in range(len(colors)):
                color[0] += colors[i][0]
                color[1] += colors[i][1]
                color[2] += colors[i][2]
            color[0] = color[0] // len(colors)
            color[1] = color[1] // len(colors)
            color[2] = color[2] // len(colors)
            color = tuple(color)
        else:
            color = self[self.leds_per_face * self.layers[0][0]]
            
        self.small_np.fill(color)
        try:
            self.small_np.write()
        except Exception as e:
            sys.print_exception(e)
        
    def __getitem__(self, index: int) -> Tuple[int, int, int]:
        """Get the color of an LED at the specified index."""
        return self.np[index]
        
    def __setitem__(self, index: int, color: Tuple[int, int, int]) -> None:
        """Set the color of an LED at the specified index."""
        self.np[index] = color
        
    def fill(self, color: Tuple[int, int, int]) -> None:
        """Fill all LEDs with the specified color."""
        self.np.fill(color) 
        self.small_np.fill(color)