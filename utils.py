import asyncio
from copy import deepcopy
from typing import Optional, Dict, Any, Callable

class SharedState:
    def __init__(self, initial: Optional[Dict[Any, Any]] = None):
        self._data: Optional[Dict[Any, Any]] = deepcopy(initial) if initial is not None else {}
        self._lock = asyncio.Lock()

    async def get(self) -> Optional[Dict[Any, Any]]:
        async with self._lock:
            return deepcopy(self._data)

    async def set(self, value: Dict[Any, Any]) -> None:
        async with self._lock:
            self._data = deepcopy(value)

    async def update(self, key: str, value: Any) -> None:
        async with self._lock:
            if self._data is None:
                self._data = {}
            self._data[key] = value


async def read_until_null_terminator(reader):
    buffer = bytearray()
    while True:
        byte = await reader.read(1)  # Reads 1 byte, returns a bytes object like b'\x00' or b'a'

        if byte == b'\x00':
            return bytes(buffer)

        buffer.append(byte[0])