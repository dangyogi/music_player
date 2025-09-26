# states.py

r'''State

'''

from .parse_xml import parse
from .unroll_repeats import unroll_parts
from .assign_starts import assign_parts

from .tools.midi_utils import *


Song_dir = "~/Documents/MuseScore4/Scores/"

Songs = [
    Song_dir + "Weeping_Willow_-_Scott_Joplin_-_1903.mxl",
    Song_dir + "Gladiolus_Rag_by_Scott_Joplin_1907.mxl",
    Song_dir + "La_Campanella-fix.mxl",
] 

# Ch1_commands and Ch1_CC_commands map to State method names.

Ch1_commands = {      # Passed event
    EventType.START: "start",
    EventType.STOP: "stop",
    EventType.CONTINUE: "continue_",
    EventType.SONGPOS: "song_position_pointer",
    EventType.SONGSEL: "song_select",
}

Ch1_CC_commands = {   # Passed event.value
}


class State:
    def enter(self):
        return False

    def name(self):
        return self.__class__.__name__

    def switch(self, new_state):
        global State
        State = new_state
        return State.enter()

    def start(self, event):
        print(f"{self.name()}.start: ignored")
        return False

    def stop(self, event):
        print(f"{self.name()}.stop: ignored")
        return False

    def continue_(self, event):
        print(f"{self.name()}.continue_: ignored")
        return False

    def song_position_pointer(self, event):
        print(f"{self.name()}.song_position_pointer: ignored")
        return False

    def song_select(self, event):
        print(f"{self.name()}.song_select: ignored")
        return False


Parts = None
Start_spp = None
Start_end = None
Continue_end = None

class start_spp:
    r'''Finds the first note who's start is >= spp.

    This points to the first note to be played when Start is done. 
    '''
    def __init__(self, spp):
        self.spp = spp  # spp in 16ths

def set_spp(spp):
    for part_no, (info, measures) in enumerate(Parts):
        spp.part_no = part_no
        first_measure = measures[0]
        spp.divisions = first_measure.divisions
        trace(f"  divisions={Divisions}")
        spp.divisions_per_16th = first_measure.divisions_per_16th
        spp.spp_divisions = spp.spp * spp.divisions_per_16th   # spp in divisions
        for measure_no, measure in enumerate(measures):
            if measure.start > spp.spp_divisions: 
                # Looks like measure_no is past the spp position, look at prior measure:
                spp.measure_no = measure_no - 1
                if search_measure(measures[self.measure_no]):
                    return spp
                # None of the notes in the prior measure match
                spp.measure_no += 1
                # This will be > than spp_divisions, so qualifies for both start and end.
                spp.note_no = 0
                return spp
        if search_measure(spp, measures[-1]):
            spp.measure_no = measure_no
            return spp
    trace(f"{spp=} not found in song, largest spp is {Parts[0][1][-1].sorted_notes[-1].start}"
    return None

def search_measure(spp, measure):
    r'''Returns True if found, setting self.note_no to the note found.
    '''
    for note_no, notes in enumerate(measure.sorted_notes):
        if note.start >= spp.spp_divisions:
            # This is the first note past the spp.  This is the note we want!
            spp.note_no = note_no
            return True
    return False

class No_song(State):
    # Note: enter() is never called on this state!

    def song_select(self, event):
        # event.value has song number
        global Parts, Start_spp, Start_end, Continue_end
        if event.value not in Songs:
            print(f"No_song.song_select: unknown song number, {event.value=}")
            return False
        parts = parse(Songs[event.value])
        new_parts = unroll_parts(parts)
        assign_parts(new_parts)
        Parts = new_parts
        Start_spp = set_spp(start_spp(0))
        Start_end = None
        Continue_end = None
        # FIX: send time signature and key signature
        return self.switch(New_song_state)

No_song_state = No_song()

New_spp = None

class SPP(No_song):
    end_at_msb_value = None
    loop_at_msb_value = None

    def song_position_pointer(self, event):
        global Start_spp, Start_end
        spp = set_spp(start_spp(event.value))
        if spp is None:
            print(f"{self.name()}.song_position_pointer, {event.value} not found -- ignored")
            return False
        Start_spp = spp
        Start_end = None
        print(f"{self.name()}.song_position_pointer: set to {Start_spp}")
        return self.switch(Ready_state)

    def set_end(self, spp):
        global Start_end
        Start_end = spp

class New_song(SPP):
    def enter(self):
        global Continue_spp
        # FIX: send time signature and key signature
        Continue_spp = 0
        return True

    def start(self, event):
        self.switch(Running_state)
        return True

New_song_state = New_song()

class Ready(SPP):
    def continue_(self, event):
        global New_spp
        New_spp = None
        return self.switch(Running_state)

    def start(self, event):
        global Continue_spp, New_spp
        Continue_spp = New_spp
        New_spp = None
        return self.switch(Running_state)

Ready_state = Ready()

class Paused(SPP):
    def continue_(self, event):
        global Start_end, Continue_end
        Start_end = Continue_end
        Continue_end = None
        return self.switch(Running_state)

Paused_state = Paused()

class Running(State):
    def enter(self):
        self.run = True
        while self.run:
            # FIX: run here!
            pass
        return False

    def stop(self, event):
        return self.end()


Running_state = Running()


State = No_song_state

def process_ch1_event(event):
    # Playback settings: Start, Stop, Continue, SPP, End/Loop at, Song Select
    if event.type == EventType.CONTROLLER:
        if event.param not in Ch1_CC_commands:
            print(f"process_ch1_event({event=}): unknown ch1 event.param, {event.param=:#X}, ignored")
            return False
        method = Ch1_CC_commands[event.param]
        param = event.value
    else:
        if event.type not in Ch1_commands:
            print(f"process_ch1_event({event=}): unknown ch1 event.type, {event.type=}, ignored")
            return False
        method = Ch1_commands[event.type]
        param = event
    return getattr(State, method)(param)
