import machine
from machine import Pin, SoftI2C, Timer
from VL53L0X import VL53L0X
import asyncio
import utime  # Add this for timing measurements
from utils import SharedState
from wifi_client import send_message # New import
import sys # Added for print_exception
from collections import deque # New import


class TempratureSettings:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.set_values_to_default()
        return cls._instance
    
    def set_values_to_default(self):
        self.TEMPRATURE_CHANGE_THRESHOLD = 800
        self.TEMP_DELTA_UP = 30
        self.TEMP_DELTA_DOWN = 10


DO_LOCK_ANIMATION = False

I2C_FREQ = 400000
REINIT_INTERVAL = 20 * 60 * 1000  # 20 minutes in milliseconds

TEMP_RISE_THRESHOLD = 100
LOCK_MESSAGE_COOLDOWN_MS = 5000
TEMP_HISTORY_WINDOW_MS = 5000

DISTANCE_OFFSET = 50 # Default offset for distance calculation

SENSOR_LOOP_DELAY_S = 0.1 # Corresponds to asyncio.sleep(0.1)
# Calculate max history length based on window and loop delay
MAX_TEMP_HISTORY_LENGTH = int(TEMP_HISTORY_WINDOW_MS / (SENSOR_LOOP_DELAY_S * 1000))


async def read_sensor(state: SharedState):
    print("setting up i2c")
    sda = Pin(21)
    scl = Pin(22)
    Xshut0 = Pin(23, Pin.OUT, value=False)
    Xshut1 = Pin(4, Pin.OUT, value=False)
    Xshut2 = Pin(15, Pin.OUT, value=False)
    Xshut3 = Pin(27, Pin.OUT, value=False)
    Xshut4 = Pin(25, Pin.OUT, value=False)
    Xshut3 = Pin(27, Pin.OUT, value=False)
    Xshut4 = Pin(25, Pin.OUT, value=False)
    # THIS PIN IS INPUT ONLY FUCK YOU
    #Xshut4 = Pin (39, Pin.OUT,value=True)
    pins = [Xshut0, Xshut1, Xshut2, Xshut3, Xshut4]
    
    # Initialize sensor_temp_array with correct length
    sensor_temp_array = [0] * len(pins)

    # Use a higher I2C frequency for faster communication
    i2c = SoftI2C(sda=sda, scl=scl, freq=I2C_FREQ)  # Max speed for better performance
    print(i2c.scan())

    # Function to shutdown all sensors
    async def xshutarrayreset():
        for pin in pins:
            pin.value(False)
        await asyncio.sleep(0.05)  # Give time to shut down completely

    # Configure a single sensor
    async def configure_tof(sensor_index, address_already_set=False):
        # Activate only the requested sensor
        # Assumes all others are off or at different addresses due to prior xshutarrayreset and sequential config
        pins[sensor_index].value(True)
        await asyncio.sleep(0.05)  # Give time for the sensor to power up and stabilize

        try:
            # Attempt to initialize the sensor (targets default address 0x29)
            new_address = 0x33 + sensor_index

            if not address_already_set:
                tof = VL53L0X(i2c)
            if address_already_set:
                tof = VL53L0X(i2c, new_address)
                
            # Configure timing and pulse periods
            tof.set_measurement_timing_budget(20000)
            tof.set_Vcsel_pulse_period(tof.vcsel_period_type[0], 18) # Period_pclks, Vcsel_period
            tof.set_Vcsel_pulse_period(tof.vcsel_period_type[1], 14) # Period_pclks, Vcsel_period for phasecal
            
            # Initial ping to stabilize and confirm sensor is working
            tof.ping()
            await asyncio.sleep(0.01) # Short delay after ping
            
            if not address_already_set:
                tof.set_address(new_address)
            print(f"Sensor {sensor_index} configured successfully at address {hex(new_address)}")
            return tof
        except Exception as e:
            print(f"Error configuring sensor {sensor_index}: {e}")
            pins[sensor_index].value(False)  # Shut down the problematic sensor
            return None

    async def initialize_sensors(current_pins, current_i2c):
        await xshutarrayreset()
        tofs_list = []
        for i in range(len(current_pins)):
            tof = await configure_tof(i) # Relies on current_pins and current_i2c from outer scope implicitly if not passed.
                                         # configure_tof uses `pins` and `i2c` from the read_sensor scope.
                                         # This is fine, but passing them explicitly might be clearer if these functions were more generic.
                                         # For now, matches existing style.
            if tof is None:
                tof = await configure_tof(i, True)

            if tof is not None:
                tofs_list.append(tof)
            else:
                tofs_list.append(None)
        return tofs_list

    tofs = await initialize_sensors(pins, i2c)
    
    # Statistics variables
    total_read_time = 0
    read_count = 0
    min_read_time = float('inf')
    max_read_time = 0
    last_init_time = utime.ticks_ms()  # Track when we last initialized sensors
    

    # New state variables for temperature monitoring and lock message cooldown
    # temp_history_per_sensor = [[] for _ in range(len(pins))] # Old list-based history
    if DO_LOCK_ANIMATION:
        temp_history_per_sensor = [deque((), MAX_TEMP_HISTORY_LENGTH) for _ in range(len(pins))]

    # Initialize last_lock_sent_time to be more than cooldown in the past to allow immediate sending
    _initial_current_time_for_lock_logic = utime.ticks_ms()
    last_lock_sent_time = utime.ticks_add(_initial_current_time_for_lock_logic, -(LOCK_MESSAGE_COOLDOWN_MS + 1))

    temp_settings = TempratureSettings()

    while True:
        current_loop_time = utime.ticks_ms()

        # Check if we need to reinitialize sensors
        if utime.ticks_diff(current_loop_time, last_init_time) >= REINIT_INTERVAL:
            print("\nReinitializing sensors...")
            tofs = await initialize_sensors(pins, i2c)
            last_init_time = current_loop_time
        
        # Measure how long the readings take
        start_time_reading_block = utime.ticks_ms()
        
        sensor_readings = []
        for i, sensor_tof in enumerate(tofs): # Use enumerate for index
            if sensor_tof is not None:
                try:
                    distance = max(0, sensor_tof.ping() - DISTANCE_OFFSET) # Adjusted offset if necessary
                    # Update temperature based on distance
                    sensor_temp_array[i] = sensor_temp_array[i] + temp_settings.TEMP_DELTA_UP if distance < temp_settings.TEMPRATURE_CHANGE_THRESHOLD else sensor_temp_array[i] - temp_settings.TEMP_DELTA_DOWN
                    sensor_temp_array[i] = min(max(0, sensor_temp_array[i]), 255)
                    # Create a tuple with distance and temperature
                    sensor_readings.append((distance, sensor_temp_array[i]))
                except Exception as e:
                    # Log error and record None for this sensor in this cycle
                    print(f"Error reading from sensor {i} (expected addr {hex(0x33 + i)}): {e}")
                    sensor_readings.append((None, sensor_temp_array[i])) # Append current temp before reinit
                    print(f"Reinitializing all sensors due to read error on sensor {i}...")
                    tofs = await initialize_sensors(pins, i2c) # Reinitialize all sensors
                    last_init_time = current_loop_time # Consider this a reinitialization point
                    # Optional: could mark tofs[i] = None to stop trying to read from it.
                    # For now, it will retry on the next cycle.
            else:
                # Sensor was not configured or failed during configuration
                sensor_readings.append((None, sensor_temp_array[i]))
        
        # Calculate elapsed time for readings block
        end_time_reading_block = utime.ticks_ms()
        elapsed_ms = utime.ticks_diff(end_time_reading_block, start_time_reading_block)
        
        # Update statistics
        read_count += 1
        total_read_time += elapsed_ms
        min_read_time = min(min_read_time, elapsed_ms)
        max_read_time = max(max_read_time, elapsed_ms)
        if read_count > 0: # Avoid division by zero if first read fails before count increment
            avg_read_time = total_read_time / read_count
        else:
            avg_read_time = 0
        
        # New feature: Check for temperature rise and send lock message
        if DO_LOCK_ANIMATION:
            lock_animation_triggered_this_cycle = False
            triggering_sensor_index = -1
            triggering_sensor_temp = -1

            for i in range(len(pins)): # Iterate through all sensor temperature slots
                current_temp_for_sensor = sensor_temp_array[i]

                # Update history for sensor i
                # history = temp_history_per_sensor[i] # No longer needed to get a mutable list reference
                # history.append((current_loop_time, current_temp_for_sensor))
                # Prune history: keep entries from the last TEMP_HISTORY_WINDOW_MS seconds
                # temp_history_per_sensor[i] = [(t, temp) for t, temp in history if utime.ticks_diff(current_loop_time, t) <= TEMP_HISTORY_WINDOW_MS]
                # With deque(maxlen=...), appending handles pruning automatically.
                temp_history_per_sensor[i].append((current_loop_time, current_temp_for_sensor))

                # Check for temperature rise for sensor i
                for recorded_time, recorded_temp in temp_history_per_sensor[i]: # Iterating deque is fine
                    # Check if current temp is >TEMP_RISE_THRESHOLD higher than any recorded temp in the window
                    if current_temp_for_sensor - recorded_temp > TEMP_RISE_THRESHOLD:
                        lock_animation_triggered_this_cycle = True
                        triggering_sensor_index = i
                        triggering_sensor_temp = current_temp_for_sensor
                        break  # Found a rise for this sensor, no need to check its further history
                
                if lock_animation_triggered_this_cycle:
                    break # Found a rise in one sensor, proceed to check cooldown and send

            if lock_animation_triggered_this_cycle:
                # Check cooldown: more than LOCK_MESSAGE_COOLDOWN_MS ms since last "LOCK_ANIMATION"
                if utime.ticks_diff(current_loop_time, last_lock_sent_time) > LOCK_MESSAGE_COOLDOWN_MS:
                    print(f"Sensor temperature spike detected (sensor {triggering_sensor_index}, current temp {triggering_sensor_temp}). Sending LOCK_ANIMATION.")
                    try:
                        response = await send_message(b"LOCK_ANIMATION", False)
                        print(f"LOCK_ANIMATION message sent successfully. Response: {response}")
                    except Exception as e_send:
                        print("Exception occurred while sending LOCK_ANIMATION message:")
                        sys.print_exception(e_send) # Requires 'import sys'
                    
                    last_lock_sent_time = current_loop_time # Update time of last sent message (or attempt)
        await state.update("distances", sensor_readings)
        #print(f"\rDistances: {sensor_readings} Time: {avg_read_time}ms", end="")
        await asyncio.sleep(SENSOR_LOOP_DELAY_S)


if __name__ == "__main__":
    # Ensure SharedState is instantiated if needed by read_sensor
    # The original code calls asyncio.run(read_sensor(SharedState()))
    # This means if wifi_client.py also needs SharedState for send_message,
    # it must be handled there, or send_message should not depend on it directly
    # if called from read_sensor. For now, SharedState is only used by state.update.
    try:
        asyncio.run(read_sensor(SharedState()))
    except Exception as e:
        # Assuming sys is available for consistency with wifi_client.py
        # If not, a simple print(e) would do.
        # Adding import sys at the top of the file.
        print("Error in main execution:")
        sys.print_exception(e)