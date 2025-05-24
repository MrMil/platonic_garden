import sys
import json
from animations import ANIMATIONS
import network
import usocket
import uasyncio
import random
import time
from utils import SharedState, read_until_null_terminator
import wifi_consts


TIME_BETWEEN_ANIMATIONS_SECONDS = 90
LOCK_WINDOW_SECONDS = 10
MAX_LOCK_TIME_SECONDS = 60

HOST_IP = wifi_consts.ACCESS_POINT_IP_ADDRESS # Listen on the AP's IP address

REQUEST_READ_TIMEOUT_S = 10.0
ACK_READ_TIMEOUT_S = 5.0



async def provide_animation(reader: usocket.socket, writer: usocket.socket, state: SharedState):
    current_shared_state = await state.get_unsafe()
    response_payload = json.dumps(current_shared_state)

    writer.write(response_payload.encode('utf-8') + b'\x00')
    await writer.drain()


async def lock_animation(reader: usocket.socket, writer: usocket.socket, state: SharedState):
    state.update('last_locked_animation', time.time())
    writer.write(b"LOCKED\x00")
    await writer.drain()


RESPONSES = {
    b"GET_ANIMATION": provide_animation,
    b"LOCK_ANIMATION": lock_animation
}

async def handle_client(reader, writer, state: SharedState):
    """
    Handles incoming client connections.
    Reads a request (ending with null terminator), sends a JSON response (ending with null terminator),
    and expects an ACK.
    """


    client_addr = writer.get_extra_info('peername')
    print(f"Client connected: {client_addr}")
    try:
        request = await uasyncio.wait_for(
            read_until_null_terminator(reader),
            timeout=REQUEST_READ_TIMEOUT_S
        )
        if not request:
            return
        
        if request in RESPONSES:
            await RESPONSES[request](reader, writer, state)
        else:
            print(f"Unknown request: {request}")
            writer.write(b"UNKNOWN_REQUEST\x00")
            await writer.drain()

        # 4. Wait for ACK from client
        ack = await uasyncio.wait_for(reader.read(3), timeout=ACK_READ_TIMEOUT_S) # Expect "ACK" (3 bytes)

    except uasyncio.TimeoutError as te:
        sys.print_exception(te) # Provide traceback for timeout
    except OSError as ose:
        sys.print_exception(ose) # Provide traceback for OSError
    except Exception as e:
        sys.print_exception(e) # Provide traceback for other exceptions
    finally:
        writer.close()
        await writer.wait_closed()


async def start_ap(state: SharedState):
    """
    Main asynchronous function to set up the Wi-Fi AP and start the server.
    """
    # 1. Initialize WLAN in Access Point mode
    ap = network.WLAN(network.AP_IF)
    ap.active(False)

    ap.config(essid=wifi_consts.WIFI_SSID, password=wifi_consts.WIFI_PASSWORD, authmode=network.AUTH_WPA_WPA2_PSK)
    # Set static IP configuration
    # Note: ifconfig order is (ip, subnet, gateway, dns)
    # For AP mode, DNS is often not needed or is the same as gateway/IP
    ap.ifconfig((wifi_consts.ACCESS_POINT_IP_ADDRESS, wifi_consts.SUBNET_MASK, wifi_consts.GATEWAY, wifi_consts.GATEWAY)) # Using GATEWAY as DNS or remove if not needed by your specific firmware version
    ap.active(True)

    while not ap.active():
        await uasyncio.sleep_ms(100)

    # 2. Start the asynchronous server
    try:
        # Use a lambda to pass the state to handle_client
        server = await uasyncio.start_server(
            lambda r, w: handle_client(r, w, state),
            HOST_IP, 
            wifi_consts.PORT
        )
        print(f"Server started on {HOST_IP}:{wifi_consts.PORT}")
        while True:
            await uasyncio.sleep(10) # Keep the event loop alive
    except Exception as e:
        pass
    finally:
        if 'server' in locals() and hasattr(server, 'close'):
            server.close()
            await server.wait_closed()
        ap.active(False)


async def choose_animation(state: SharedState):
    animation = None
    while True:
        animation_start_time = time.time()
        new_animation = random.choice(ANIMATIONS)
        while new_animation == animation:
            new_animation = random.choice(ANIMATIONS)
        animation = new_animation
        await state.update('animation', animation)
        await uasyncio.sleep(TIME_BETWEEN_ANIMATIONS_SECONDS)
        last_locked_animation = (await state.get_unsafe()).get('last_locked_animation')
        if last_locked_animation is not None:
            while (time.time() - last_locked_animation < LOCK_WINDOW_SECONDS and
                   time.time() - animation_start_time < TIME_BETWEEN_ANIMATIONS_SECONDS + MAX_LOCK_TIME_SECONDS):
                await uasyncio.sleep(1)
                last_locked_animation = (await state.get_unsafe()).get('last_locked_animation')
        

def main():
    try:
        # Initialize SharedState, potentially with some initial data
        initial_data = {
            'animation': None,
            'last_locked_animation': None
        }
        state = SharedState(initial=initial_data)
        tasks = []
        tasks.append(start_ap(state))
        tasks.append(choose_animation(state))
        uasyncio.run(uasyncio.gather(*tasks))
    except KeyboardInterrupt:
        raise
    except Exception as e:
        sys.print_exception(e)
        

if __name__ == "__main__":
    main()
