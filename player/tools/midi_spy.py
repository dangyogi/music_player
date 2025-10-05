# midi_spy.py

import time
from collections import Counter

from .midi_utils import *

Show_clocks = False
Err_secs_counts = Counter()
Err_pulse_counts = Counter()
Clock_stat_period = None
Clocks_seen = 0
NoteOns_seen = None
NoteOffs_seen = None
Ticks_per_clock = None
Clocks_per_quarter_note = 24
Last_clock = None
Last_drop = None

Client_names = {}          # {id: name}
Clients_by_name = {}  # {name: id}
Ports = {}            # {(client_id, port_id): name}
Player_clock_addr = None
Player_queue = None
Player_queue_ppq = None
Net_client_addr = None

def process_event(event):
    global Err_secs_counts, Err_pulse_counts
    global Clocks_seen, NoteOns_seen, NoteOffs_seen, Last_clock, Last_drop
    global Player_clock_addr, Player_queue, Player_queue_ppq, Ticks_per_clock, Net_client_addr
    show_clock_stats = False
    if event.type != EventType.CLOCK:
        #input_time = time.time()
        #trace("input", input_time - pending_time)
        if event.queue_id == SND_SEQ_QUEUE_DIRECT:
            if event.tick:
                trace("source", event.source, event, "tick", event.tick)
            else:
                trace("source", event.source, event)
        elif event.tick:
            trace("source", event.source, event,
                  "queue_id", event.queue_id, "tick", event.tick)
        else:
            trace("source", event.source, event, "queue_id", event.queue_id)
        if event.type == EventType.CLIENT_START:
            trace(f"CLIENT_START: {event.addr=}")
            client_id = event.addr.client_id
            client_name = Client.get_client_info(client_id).name
            Client_names[client_id] = client_name
            Clients_by_name[client_name] = client_id
            if client_name == 'Player':
                time.sleep(0.1)
                Player_clock_addr = midi_address((client_id, "Clock"))
                assert Player_clock_addr is not None
                Player_clock_addr = str(Player_clock_addr)
                Player_queue = Client.get_named_queue("Player Queue")
                trace(f"Player started: {client_id=}, {Player_queue.queue_id=}")
            elif client_name == 'Net Client':
                trace(f"aseqnet started: {client_id=}")
                Net_client_addr = midi_address((client_id, 0))
                assert Net_client_addr is not None
                Net_client_addr = str(Net_client_addr)
        if event.type == EventType.CLIENT_EXIT:
            trace(f"CLIENT_EXIT: {event.addr=}")
            client_id = event.addr.client_id
            name = Client_names[client_id]
            del Client_names[client_id]
            del Clients_by_name[name]
            if name == 'Player':
                trace(f"Player exited: {client_id=}")
                Player_clock_addr = None
                Player_queue = None
            elif name == 'Player':
                trace(f"aseqnet exited: {client_id=}")
                Net_client_addr = None
        if event.type == EventType.PORT_START:
            #print(dir(event))
            #
            # addr (source port)
            # dest
            # flags
            # length
            # queue_id
            # raw_data
            # relative
            # source
            # tag
            # tick
            # time
            # type
            #print(f"{event.addr=}, {event.dest=}, {event.flags=}, {event.relative=}, {event.source=}")
            #print(f"{event.tick=}, {event.time=}, {event.type=}")
            #print(f"{event.addr=}, {event.flags=}")
            name = Client.get_port_info(event.addr).name
            Ports[event.addr.client_id, event.addr.port_id] = name
            trace(f"PORT_START: {event.addr=}, {name=}")
            connect_from(event.addr)
        if event.type == EventType.PORT_EXIT:
            name = Ports[event.addr.client_id, event.addr.port_id]
            del Ports[event.addr.client_id, event.addr.port_id]
            trace(f"PORT_EXIT: {event.addr=}, {name=}")
    if event.type == EventType.CLOCK:
        if str(event.source) != Player_clock_addr:
            if Show_clocks:
                trace(f"CLOCK not from Player:Clock, rather {event.source=}")
        else:
            Clocks_seen += 1
            assert event.tick is not None, f"Player:Clock CLOCK event with no event.tick"
            if event.tick - Last_clock != Ticks_per_clock:
                trace(f"CLOCK: Expected {Last_clock + Ticks_per_clock}, got {event.tick}")
            Last_clock = event.tick
            tick_delay = midi_queue_status(Player_queue).tick_time - event.tick
            Err_pulse_counts[tick_delay] += 1
            tempo = Player_queue.get_tempo()  # microseconds / quarter_note
            if tempo.ppq != Player_queue_ppq:
                trace(f"CLOCK: current ppq, {tempo.ppq}, != {Player_queue_ppq=}")
            secs_per_tick = tempo.tempo / tempo.ppq / 1e6
            err = round(tick_delay * secs_per_tick, 4)
            if err < 0.0:
                trace(f"Got pulse err < 0, queue_time={midi_queue_time(Player_queue)}, "
                      f"{event.tick=}, {err=}")
                err = -err
            Err_secs_counts[err] += 1
            if Show_clocks and Clocks_seen % Clock_stat_period == 0:
                show_clock_stats = True
    elif event.type == EventType.NOTEON:
        NoteOns_seen[str(event.source)] += 1
    elif event.type == EventType.NOTEOFF:
        NoteOffs_seen[str(event.source)] += 1
    elif event.type == EventType.START and str(event.source) == Net_client_addr:
        trace(f"START")
        Clocks_seen = 0
        Player_queue_ppq = Player_queue.get_tempo().ppq
        trace("ppq", Player_queue_ppq)
        Ticks_per_clock = Player_queue_ppq // Clocks_per_quarter_note
        Last_clock = -Ticks_per_clock
        NoteOns_seen = Counter()
        NoteOffs_seen = Counter()
    elif event.type == EventType.CONTINUE and str(event.source) == Net_client_addr:
        trace(f"CONTINUE")
    elif event.type == EventType.STOP and str(event.source) == Net_client_addr:
        #def str_seen(seen):
        #    return ', '.join(f"{str(addr)}: {count}" for addr, count in sorted(seen.items()))
        if NoteOns_seen is not None:
            trace(f"STOP: got {Clocks_seen} CLOCKS, {NoteOns_seen} NOTEONs, "
                  f"{NoteOffs_seen} NOTEOFFs")
        else:
            trace(f"STOP: no matching START")
        show_clock_stats = True
    if show_clock_stats:
        trace("Clock time stats:")
        clock_secs_count = 0
        for err, count in sorted(Err_secs_counts.items()):
            print(f"  {err}: {count}")
            clock_secs_count += count
        trace("Clock pulse stats:")
        clock_pulse_count = 0
        for err, count in sorted(Err_pulse_counts.items()):
            print(f"  {err}: {count}")
            clock_pulse_count += count
        Err_secs_counts = Counter()
        Err_pulse_counts = Counter()
        trace(f"  counted secs for {clock_secs_count} CLOCK messages")
        trace(f"  counted pulses for {clock_pulse_count} CLOCK messages")

def connect_from(addr):
    port_info = midi_get_port_info(addr)
    cap = port_info.capability
    if (cap & PortCaps.READ) and (cap & PortCaps.SUBS_READ):
        name = midi_get_address(port_info)
        trace(">>>>>>>>>>> connecting from", name)
        if not midi_connect_from(Port, port_info):
            trace("Got error, not connected")


Port = None

def run():
    global Client, Player_clock_addr, Player_queue, Player_queue_ppq, Ticks_per_clock, Net_client_addr
    global Port, Show_clocks, Clock_stat_period

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action="store_true", default=False)
    parser.add_argument('--show-clocks', '-s', action="store_true", default=False)
    #parser.add_argument('--bpm', '-b', type=int, default=None)
    parser.add_argument('--clock_stat_period', '-c', type=int, default=100)  # Clocks
    args = parser.parse_args()

    Show_clocks = args.show_clocks

    Clock_stat_period = args.clock_stat_period

    try:
        if args.verbose:
            midi_set_verbose(args.verbose)
        Client = midi_init("midi-spy")
        Port = midi_create_input_port("notes", connect_from=(SYSTEM_TIMER, SYSTEM_ANNOUNCE))
        for info in midi_list_ports():
            Client_names[info.client_id] = info.client_name
            Clients_by_name[info.client_name] = info.client_id
            Ports[info.client_id, info.port_id] = info.name
            if info.client_id != Client.client_id:
                connect_from(info)
        if "Player" in Clients_by_name:
            player_id = Clients_by_name["Player"]
            Player_clock_addr = midi_address((player_id, "Clock"))
            assert Player_clock_addr is not None
            Player_clock_addr = str(Player_clock_addr)
            Player_queue = Client.get_named_queue("Player Queue")
            Player_queue_ppq = Player_queue.get_tempo().ppq
            trace("ppq", Player_queue_ppq)
            Ticks_per_clock = Player_queue_ppq // Clocks_per_quarter_note
        if "Net Client" in Clients_by_name:
            net_client_id = Clients_by_name["Net Client"]
            Net_client_addr = midi_address((net_client_id, 0))
            assert Net_client_addr is not None
            Net_client_addr = str(Net_client_addr)
        trace(f"{Show_clocks=}, {Clock_stat_period=}, {Player_clock_addr=}, {Ticks_per_clock=}, "
              f"{Net_client_addr=}")

        midi_process_fn(process_event)

        while True:
            midi_pause()

    finally:
        midi_close()



if __name__ == "__main__":
    run()
