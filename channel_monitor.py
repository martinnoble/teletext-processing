from gpiozero import LED, DigitalInputDevice
from signal import pause
import configparser
import threading
import sys
import os

from t42restream import restream, DEFAULT_MASK

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "channel_monitor.ini")

def _load_channel_config(path):
    """Load per-channel file and time_format from an INI config file.

    Returns a dict mapping channel number (int) to
    {'file': str, 'time_format': str}.
    """
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path)
    config = {}
    for section in cp.sections():
        if not section.startswith("channel."):
            continue
        try:
            ch = int(section.split(".", 1)[1])
        except ValueError:
            continue
        def unquote(s):
            if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
                return s[1:-1]
            return s

        config[ch] = {
            "file": cp.get(section, "file"),
            "time_format": unquote(cp.get(section, "time_format", fallback="%H:%M/%S")),
        }
    return config

# Map channel number (0-3) to {'file': ..., 'time_format': ...}
CHANNEL_CONFIG = _load_channel_config(_CONFIG_FILE)

output_enable = LED(4)
address_0 = DigitalInputDevice(pin=2, pull_up=True, bounce_time=0.1)
address_1 = DigitalInputDevice(pin=3, pull_up=True, bounce_time=0.1)

channel = 5
_restream_thread = None
_stop_event = threading.Event()


def _run_restream(input_file, time_format, stop_event):
    """Run restream, writing to stdout.buffer, stopping when stop_event is set."""
    class StoppableOutput:
        """Wraps stdout.buffer and raises StopIteration when stop_event fires."""
        def write(self, data):
            if stop_event.is_set():
                raise StopIteration
            sys.stdout.buffer.write(data)

        def flush(self):
            if not stop_event.is_set():
                sys.stdout.buffer.flush()

    try:
        restream(input_file, DEFAULT_MASK, time_format, loop=True,
                 output=StoppableOutput(), magazine_parallel=True,
                 control_overrides={'C9': 0})
    except StopIteration:
        pass


def _start_restream(ch):
    """Stop any running restream thread and start a new one for *ch*."""
    global _restream_thread, _stop_event

    # Signal the current thread to stop and wait for it to finish
    _stop_event.set()
    if _restream_thread is not None:
        _restream_thread.join()

    cfg = CHANNEL_CONFIG.get(ch)
    input_file = cfg["file"] if cfg else None
    if input_file is None or not os.path.isfile(input_file):
        print("Channel {}: no file available ({})".format(ch, input_file), file=sys.stderr)
        return

    time_format = cfg["time_format"]
    print("Channel changed to {}: streaming {} (time_format={!r})".format(
        ch, input_file, time_format), file=sys.stderr)
    _stop_event = threading.Event()
    _restream_thread = threading.Thread(target=_run_restream,
                                        args=(input_file, time_format, _stop_event),
                                        daemon=True)
    _restream_thread.start()


def channel_change():
    global channel
    value = (1 - address_0.value) + ((1 - address_1.value) * 2)
    if channel != value:
        channel = value
        _start_restream(value)


address_0.when_activated = channel_change
address_0.when_deactivated = channel_change
address_1.when_activated = channel_change
address_1.when_deactivated = channel_change

output_enable.on()

# Start streaming for the initial channel read at boot
channel_change()

pause()

# Made with Bob
