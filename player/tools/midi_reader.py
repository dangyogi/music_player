# midi_reader.py

# Results:
#
# flags    - 0 changed to EventFlag.TIME_MODE_REL (regardless of relative flag?),
#            flags changes are a mess!  They default to TIME_MODE_ABS, which is what I want, so I'll
#            just not use it...
# tag      - unchanged from original event
# queue_id - overridden by send_queue
#            if both event.queue_id and send_queue are None, then overridden with SND_SEQ_QUEUE_DIRECT
# tick     - None sometimes changed to 0.  This is set when there's a queue_id (other
#            than SND_SEQ_QUEUE_DIRECT) with TIME_STAMP_ABS flag (default).
# source   - overridden by send_port,
#            if both event.source and send_port are None, then overridden with port 0
# dest     - overridden by send_dest
#            if both event.dest and send_dest are None, then goes to subscribed port
# relative - relative changes are a mess!  They default to TIME_MODE_ABS, which is what I want
#            so I'll just not use it...

from midi_utils import *
from midi_writer import Choices


def init():
    midi_init("midi-reader")
    midi_create_input_port("no-sub", caps=PortCaps.WRITE)
    midi_create_input_port("sub-not-used")
    midi_create_input_port("sub-used")
    midi_process_fn(process_event)

Choices_fixed = False

Fields = dict(
    flags= 'flags',            # changed
    tag='tag',                 # never changed
    queue_id='event_queue',    # changed
    tick='ticks',              # changed
    source='event_source',     # changed
    dest='event_dest',         # changed
    relative='event_relative', # never changed
)

Changed = set()
Flags_sent = set()
Num_events = 0

def process_event(event):
    global Choices_fixed, Num_events

    if event.source == SYSTEM_ANNOUNCE:
        if event.type == EventType.PORT_SUBSCRIBED and not Choices_fixed:
            Choices.fix()
            Choices_fixed = True
    else:
        if event.type != EventType.NOTEON:
            print(f"Got unexpected event.type, {Event_type_names[event.type]}")
        Num_events += 1
        choices = Choices.decode(event.note, event.channel, event.velocity)
        for field, choice in Fields.items():
            event_value = getattr(event, field)
            sent_value = choices.get(choice)
            if field == 'tick':
                if event.queue_id != SND_SEQ_QUEUE_DIRECT and \
                   (event.flags & EventFlags.TIME_STAMP_MASK) == EventFlags.TIME_STAMP_TICK:
                    if event_value is None or sent_value is not None and event_value < sent_value:
                        print(f"{field} changed (got smaller): sent {sent_value}, "
                              f"got {event_value}, {event.flags=}, {event.relative=}, {event.queue_id=}")
                        Changed.add(field)
                    continue
                if sent_value is None and event_value in (0, None):
                    continue
                if event_value != sent_value:
                    print(f"{field} changed: sent {sent_value}, "
                          f"got {event_value}, {event.flags=}, {event.relative=}, {event.queue_id=}")
                    Changed.add(field)
                continue
            elif field == 'queue_id':
                send_queue = choices.get('send_queue')
                if send_queue is not None:
                    if send_queue != event_value:
                        print(f"{field} changed: sent {sent_value}, {send_queue=}, got {event_value}")
                        Changed.add(field)
                    continue
                if sent_value is None and event_value == SND_SEQ_QUEUE_DIRECT:
                    continue
                if sent_value != event_value:
                    print(f"{field} changed: sent {sent_value}, {send_queue=}, got {event_value}")
                    Changed.add(field)
                continue
            elif field == 'relative':
                if sent_value != event_value:
                    sent_flags = choices.get('flags')
                    print(f"{field} changed: sent {sent_value}, "
                          f"got {event_value}, {sent_flags=}, {event.flags=}, {event.queue_id=}")
                    Changed.add(field)
                continue
            elif field == 'flags':
                Flags_sent.add(sent_value)
                if sent_value == event_value:
                    continue
                print(f"flags changed, sent {sent_value}, got {event_value}, {event.relative=}")
                Changed.add(field)
                continue
                if relative is not None:
                    if relative:
                        # turns on TIME_MODE_REL
                        if event.queue_id is SND_SEQ_QUEUE_DIRECT:
                            # In this case, it obliterates the rest of the flags.
                            if event_value != EventFlags.TIME_MODE_REL.value:
                                print(f"{field} changed: sent {hex(sent_value)}, {relative=}, "
                                      f"{event.queue_id=}; got {hex(event_value)}")
                                Changed.add(field)
                            continue
                        if sent_value | EventFlags.TIME_MODE_REL.value != event_value:
                            print(f"{field} changed: sent {hex(sent_value)}, {relative=}, "
                                  f"{event.queue_id=}; got {hex(event_value)}")
                            Changed.add(field)
                    else:  # relative is False
                        # turns off TIME_MODE_REL
                        if sent_value & ~EventFlags.TIME_MODE_REL.value != event_value:
                            print(f"{field} changed: sent {hex(sent_value)}, {relative=}, "
                                  f"{event.queue_id=}; got {hex(event_value)}")
                            Changed.add(field)
                    continue
            elif field == 'source':
                send_port = choices.get('send_port')
                if send_port is not None:
                    send_port_addr = midi_address(("midi-writer", send_port))
                    assert send_port_addr is not None
                    if send_port_addr != event_value:
                        print(f"{field} changed: sent {send_port=}, {sent_value=}, "
                              f"got {event_value}, type={type(event_value)}")
                        Changed.add(field)
                    continue
                if sent_value is None:
                    sent_addr = midi_address(("midi-writer", 0))
                    assert sent_addr is not None
                    if sent_addr != event_value:
                        print(f"{field} changed: sent {send_port=}, {sent_value=}, got {event_value}")
                        Changed.add(field)
                    continue
            elif field == 'dest':
                send_dest = choices.get('send_dest')
                if send_dest is not None:
                    if send_dest != event_value:
                        print(f"{field} changed: sent {send_dest=}, {sent_value=}, got {event_value}")
                        Changed.add(field)
                elif sent_value is not None:
                    if sent_value != event_value:
                        print(f"{field} changed: sent {send_dest=}, {sent_value=}, got {event_value}")
                        Changed.add(field)
                # both send_dest and sent_value are None, can only show up on port 2
                elif event_value != midi_address(":2"):
                    print(f"{field} changed: sent {send_dest=}, {sent_value=}, got {event_value}")
                    Changed.add(field)
                continue
            if sent_value != event_value:
                print(f"{field} changed: sent {sent_value}, "
                      f"got {event_value}, {event.flags=}, {event.relative=}, {event.queue_id=}")
                Changed.add(field)
        #print(hex(event.flags), event.tag, event.queue_id, event.tick,
        #      event.source, event.dest, event.relative, sep='\t')
    return False


def run():
    try:
        init()
        print(f"{EventFlags(2)=}")
        print("flags", "tag", "queue", "tick", "source", "dest", "relative", sep='\t')
        while True:
            midi_pause()
    finally:
        midi_close()
        print(f"{Changed=}")
        print(f"{Flags_sent=}")
        print(f"{Num_events=}")


if __name__ == "__main__":
    run()
