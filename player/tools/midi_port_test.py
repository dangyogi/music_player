# midi_port_test.py

from midi_utils import *

def init():
    global Ports, Port_names
    midi_init("port-test")
    Ports = []
    Port_names = []
    add("input", midi_create_input_port("input"))
    add("inout", midi_create_inout_port("inout", default=False))
    add("output", midi_create_output_port("output", default=False))
    midi_process_fn(process_event)

def add(name, port):
    assert port.port_id == len(Ports)
    Port_names.append(name)
    Ports.append(port)

Msg = None

def process_event(event):
    print(f"{Msg} got {Port_names[event.source.port_id]} -> {Port_names[event.dest.port_id]}")
    return False

def send(port=None, dest=None):
    midi_send_event(NoteOnEvent(60, 1, 70), port=Ports[port], dest=Ports[dest], drain_output=True)
    midi_pause(0.1)

def restart():
    midi_close()
    init()

def run():
    global Msg
    ports = 0, 1, 2
    try:
        init()
        for port in ports:
            for dest in ports:
                Msg = f"{Port_names[port]} -> {Port_names[dest]}"
                try:
                    send(port=port, dest=dest)
                except ALSAError as e:
                    print(f"{Msg}: Error {e}")
                    restart()
    finally:
        midi_close()


if __name__ == "__main__":
    run()
