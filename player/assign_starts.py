# assign_starts.py

from fractions import Fraction

from .tools.midi_utils import fraction


# measures have:
#
#   attributes, direction, backup, forward, note, barline
#
#   This module doesn't care about direction or barline.
#
#   attributes have divisions, staves, key and time (beats, beat_type)
#   backup/forward have duration
#
# notes have (of interest here):
#
#   rest, cue, grace (no duration), chord, duration, voice, time_modification
#
#   chord is not set on first note of the chord.  So don't count duration on chord notes.
#
#   time_modification: actual-notes (e.g., 3), normal-notes (e.g, 2)

# attributes.divisions

Quarter_note = Fraction(1, 4)

Note_durations = {  # the note durations in clocks (24/qtr-note)
   'whole': 4 * 24,
   'half': 2 * 24,
   'quarter': 1 * 24,
   'eighth': 24 // 2,
   '16th': 24 // 4,
   '32nd': 24 // 8,
   '64th': Fraction(24, 16),
   '128th': Fraction(24, 32),
   '256th': Fraction(24, 64),
}

Measure_start = 0
Modifiers_seen = set()

class assign_measure:
    r'''Acts like a function, but provides a bucket for measure-level variables.

    All methods are only used by __init__.

    Assigns the following to measure:
        index - 0 relative index into measures
        key - attributes.key
        tempo - direction.tempo
        volume - direction.volume
        dynamics - direction.direction_type.dynamics
        sorted_notes - notes sorted by ascending start, decending midi_note
        divisions - brought out in the measure declaring attributes.divisions
        divisions_per_clock - brought out in the measure declaring attributes.divisions
        divisions_per_16th - brought out in the measure declaring attributes.divisions
        time - brought out in the measure declaring attributes.time as (beats, beat_type)
        divisions_per_measure - brought out in the measure declaring both divisions and time
        clocks_per_measure - brought out in the measure declaring both divisions and time
        start - start of measure in clocks from the start of the part.
        duration_clocks - duration of measure (greatest note stop time)

    Also assigns the following to notes (that are not ignored):
        duration_clocks - note duration in clocks
        start           - start of note in clocks from the start of the part.
        chord_top_down  - note number in chord counting from highest to lowest pitch,
                          None if not in chord
        chord_bottom_up - note number in chord counting from lowest to highest pitch, 
                          None if not in chord
        modifiers       - set of modifiers used as expession indexes
    '''
    def __init__(self, measure, index, time_modifications=False, trace=None, trace_no_print=False):
        self.trace = trace
        self.measure = measure
        self.number = str(measure.number)
        self.measure.index = index
        self.time_modifications = time_modifications
        self.trace_no_print = trace_no_print
        if self.number == self.trace:
            print("measure", self.number)
        self.process_children()

    def process_children(self):
        global Measure_start
        self.start = Measure_start
        self.last_start = 0
        self.longest = 0
        self.backup_num = 0
        self.forward_num = 0
        for child in self.measure.children:
            if child.name == 'attributes':
                if hasattr(child, 'divisions'):
                    self.assign_divisions(child.divisions)
                if hasattr(child, 'time'):
                    self.assign_time(child.time)
                if hasattr(child, 'key'):
                    self.measure.key = child.key
            elif child.name == 'direction':
                if hasattr(child, 'tempo'):
                    self.measure.tempo = child.tempo
                if hasattr(child, 'volume'):
                    self.measure.volume = child.volume
                if hasattr(child, 'direction_type'):
                    for direction_type in child.direction_type:
                        if direction_type.name == 'dynamics':
                            self.measure.dynamics = direction_type.value
            elif child.name == 'backup':
                self.backup_num += 1
                child.duration_clocks = fraction(child.duration, Divisions_per_clock)
                if self.number == self.trace:
                    print(f"backup {self.backup_num} duration_clocks={child.duration_clocks}")
                if child.duration_clocks > self.start:
                    print(f"backup num {self.backup_num}, {child.duration_clocks}, "
                          f"in measure {self.number} > start, {self.start=}")
                    self.start = Measure_start
                else:
                    self.start -= child.duration_clocks
                self.last_start = self.start
            elif child.name == 'forward':
                self.forward_num += 1
                child.duration_clocks = fraction(child.duration, Divisions_per_clock)
                if self.number == self.trace:
                    print(f"forward {self.forward_num} duration_clocks={child.duration_clocks}")
                if self.start + child.duration_clocks > Clocks_per_measure:
                    print(f"forward num {self.forward_num}, {child.duration_clocks}, "
                          f"in measure {self.number} > Clocks_per_measure, {self.start=}")
                self.inc_start(child.duration_clocks)
            elif child.name == 'note':
                self.assign_start(child)
                child.chord_top_down = child.chord_bottom_up = None

                # process ties, this sets child.ignore on all but first note in tie.
                # This gets done before sorting the notes, so that tied notes are excluded.
                if not child.ignore and child.grace is None:
                    child_end = child.start + child.duration_clocks
                    links_to_last = (child.note, child_end) in Last_tie_notes
                    tie_start = 'start' in child.tie
                    links_to_first = (child.note, child.start) in First_tie_notes
                    tie_stop = 'stop' in child.tie

                    # This has to be done first, because it may change child.duration_clocks
                    if tie_start:
                        if links_to_last:
                            # add last to note
                            last = Last_tie_notes[child.note, child_end]
                            child.duration += last.duration
                            child.duration_clocks += last.duration_clocks
                            # ignore last
                            last.ignore = True
                            # del last's Last_tie_note
                            del Last_tie_notes[child.note, child_end]
                            # correct child_end
                            child_end += last.duration_clocks
                            # Do we need a First_tie_note?
                            last_end = last.start + last.duration_clocks
                            if (last.note, last_end) in First_tie_notes:
                                # last still waiting for something after it
                                # substitute child for last in First_tie_notes
                                del First_tie_notes[last.note, last_end]
                                First_tie_notes[child.note, child_end]
                        else:
                            # wait for next note
                            First_tie_notes[child.note, child_end] = child
                    elif links_to_last:
                        print(f"process_children: missing tie start on note={child.note}, "
                              f"voice={child.voice}, in measure {self.number}")

                    if tie_stop:
                        if links_to_first:
                            # add note to first
                            first = First_tie_notes[child.note, child.start]
                            first.duration += child.duration
                            first.duration_clocks += child.duration_clocks
                            # ignore child
                            child.ignore = True
                            # del first's First_tie_note
                            del First_tie_notes[child.note, child.start]
                            # if first is also in Last_tie_notes, the entry is still valid!
                        else:
                            Last_tie_notes[child.note, child.start] = child
                    elif links_to_first:
                        print(f"process_children: missing tie stop on note={child.note}, "
                              f"voice={child.voice}, in measure {self.number}")

        measure_duration = self.longest - Measure_start
        if measure_duration != Clocks_per_measure:
            print(f"Measure {self.number} has incorrect length.  "
                  f"Got {measure_duration}, expected {Clocks_per_measure}")
        self.measure.start = Measure_start
        self.measure.duration_clocks = measure_duration
        Measure_start += self.measure.duration_clocks

        for (midi_note, start), note in list(First_tie_notes.items()):
            if start < Measure_start:
                print(f"process_children: missing matching tie stop for tie start note {note.note}, "
                      f"voice={note.voice}, in measure {self.number}")
                print(f"looking for {start=}, {Measure_start=}")
                del First_tie_notes[midi_note, start]
        for key, note in list(Last_tie_notes.items()):
            print(f"process_children: missing matching tie start for tie stop note {note.note}, "
                  f"voice={note.voice}, in measure {self.number}")
            del Last_tie_notes[key]

        sorted_notes = [child for child in self.measure.children
                               if child.name == 'note' and not child.ignore]
        # ascending start, descending midi_note, descending duration
        sorted_notes.sort(key=lambda note: (note.start,                         # ascending start
                                            -note.midi_note,                    # descending midi_note
                                            -10000 if note.grace is not None
                                                   else -note.duration_clocks)) # descending duration
        start_len = len(sorted_notes)
        if self.number == self.trace:
            print(f"measure({self.number}) sorted_notes before de-dup:")
            for note in sorted_notes:
                print(f"  note {note.note}, midi_note={note.midi_note}, voice={note.voice}, "
                      f"start={note.start}, duration_clocks={note.duration_clocks}, tie={note.tie}")
        i = 0
        first_note = None  # of chord
        while i + 1 < len(sorted_notes):
            assert sorted_notes[i].start <= sorted_notes[i + 1].start, \
                   f"sorted_notes sort failed, measure={self.number}, note={sorted_notes[i].note}" \
                   f"first start={sorted_notes[i].start}, second start={sorted_notes[i + 1].start}"
            if sorted_notes[i].start == sorted_notes[i + 1].start:
                assert sorted_notes[i].midi_note >= sorted_notes[i + 1].midi_note, \
                       f"sorted_notes sort failed, measure={self.number}, note={sorted_notes[i].note}" \
                       f"first midi_note={sorted_notes[i].midi_note}, " \
                       f"second start={sorted_notes[i + 1].midi_note}"
                if sorted_notes[i].midi_note == sorted_notes[i + 1].midi_note:
                    # These are actually fairly common.  Ultimately, we can only play the note with one
                    # duration, so we pick the longest and delete the shortest...
                    assert sorted_notes[i].duration_clocks >= sorted_notes[i + 1].duration_clocks, \
                           f"sorted_notes sort failed, measure={self.number}, " \
                           f"note={sorted_notes[i].note}" \
                           f"first duration_clocks={sorted_notes[i].duration_clocks}, " \
                           f"second duration_clocks={sorted_notes[i + 1].duration_clocks}"
                    if sorted_notes[i].duration_clocks == sorted_notes[i + 1].duration_clocks:
                        # What would this mean??  Let's see if this ever happens...
                        print(f"process_children(measure={self.number}): "
                              f"two {sorted_notes[i].note} notes "
                              f"with same start={sorted_notes[i].start} "
                              f"and duration_clocks={sorted_notes[i].duration_clocks}")
                    print(f"process_children(measure={self.number}) deleting dup note "
                          f"{sorted_notes[i + 1].note}, "
                          f"duration_clocks={sorted_notes[i + 1].duration_clocks}")
                    # delete the shorter note
                    del sorted_notes[i + 1]
                    continue   # without incrementing i
                # else these are not the same note.
                # If we make it this far, these are two different notes sounding at the same time.
                if first_note is None:
                    first_note = i
            else:
                if first_note is not None:
                    # i is last note of chord
                    chord = sorted_notes[first_note: i + 1]
                    for n, note in enumerate(chord, 1):
                        note.chord_top_down = n
                    for n, note in enumerate(reversed(chord), 1):
                        note.tags.append(f"chord-{n}")
                        note.chord_bottom_up = n
                    first_note = None
            i += 1
        if first_note is not None:
            # chord goes to end
            chord = sorted_notes[first_note:]
            for n, note in enumerate(chord, 1):
                note.chord_top_down = n
            for n, note in enumerate(reversed(chord), 1):
                note.tags.append(f"chord-{n}")
                note.chord_bottom_up = n
        end_len = len(sorted_notes)
        if start_len != end_len:
            print(f"process_children(measure={self.number}): deleted {start_len - end_len} dup notes")

        # add modifiers to each note to trigger expressions.
        for note in sorted_notes:
            note.modifiers = set()
            note.modifiers.add(f"voice_{note.voice}")
            note.modifiers.add(f"staff_{note.staff}")
            if note.slur_start:
                note.modifiers.add('slur_start')
            if note.slur_middle:
                note.modifiers.add('slur_middle')
            if note.slur_stop:
                note.modifiers.add('slur_stop')
            if note.chord_bottom_up is not None:
                if note.arpeggiate:
                    note.modifiers.add(f"arpeggiate_{note.chord_bottom_up}")
                else:
                    note.modifiers.add(f"chord_{note.chord_bottom_up}")
           #if note.tuplet is not None:
           #    note.modifiers.add('tuplet')
            if note.articulations is not None:
                articulations = note.articulations
                for attr in "strong_accent accent staccato detached_legato " \
                            "staccatissimo tenuto".split():
                    if hasattr(articulations, attr):
                        note.modifiers.add(attr)
            if note.fermata is not None:
                note.modifiers.add("fermata")
            if note.grace is not None:
                grace = note.grace
                if hasattr(grace, "slash") and grace.slash == "yes":
                    note.modifiers.add("grace_slash")
                else:
                    note.modifiers.add("grace")
            if hasattr(note, "ornaments"):
                ornaments = note.ornaments
                if hasattr(ornaments, "trill_mark") and ornaments.trill_mark:
                    note.modifiers.add("trill")
            Modifiers_seen.update(note.modifiers)
        self.measure.sorted_notes = sorted_notes
        if self.number == self.trace:
            print(f"measure({self.number}) sorted_notes after de-dup:")
            for note in sorted_notes:
                print(f"  note {note.note}, midi_note={note.midi_note}, voice={note.voice}, "
                      f"start={note.start}, duration_clocks={note.duration_clocks}, tie={note.tie}")
        return 

    def assign_divisions(self, divisions):
        global Divisions, Divisions_per_clock, Divisions_per_16th
        if Divisions is not None and self.trace:
            print(f"Divisions reassigned in measure {self.number} "
                  f"from {Divisions} to {divisions}")
        Divisions = divisions
        self.measure.divisions = Divisions      # divisions per quarter note
        if divisions % 4 != 0:
            raise AssertionError(f"divisions, {divisions}, not multiple of 4 for SPP "
                                 f"in measure {self.number}")
        Divisions_per_clock = fraction(Divisions, 24)
        print(f"assign_divisions({divisions}): {Divisions_per_clock=}")
        Divisions_per_16th = fraction(Divisions_per_clock, 4)
        self.measure.divisions_per_clock = Divisions_per_clock
        self.measure.divisions_per_16th = Divisions_per_16th
        if self.trace:
            print("Got Divisions", Divisions, "in measure", self.number)
        if Time is not None:
            self.assign_divisions_per_measure()

    def assign_time(self, time):
        global Time
        new_time = (time.beats, time.beat_type)
        if Time is not None and self.trace:
            print(f"Time reassigned in measure {self.number} from {Time} to {new_time}")
        Time = new_time
        self.measure.time = Time
        if self.trace:
            print(f"assign_time got time {time.beats}/{time.beat_type}, set {Time=}, "
                  f"in measure {self.number}")
        if Divisions is not None:
            self.assign_divisions_per_measure()

    def assign_divisions_per_measure(self):
        global Divisions_per_measure, Clocks_per_measure
        Divisions_per_measure = fraction(Divisions * Time[0], Time[1] * Quarter_note)
        Clocks_per_measure = fraction(Divisions_per_measure, Divisions_per_clock)
        print(f"assign_divisions_per_measure: {Divisions=}, {Divisions_per_measure=}, "
            f"{Divisions_per_clock=}, {Clocks_per_measure=}")
        self.measure.divisions_per_measure = Divisions_per_measure
        self.measure.clocks_per_measure = Clocks_per_measure
        if self.trace:
            print("Divisions_per_measure set to", Divisions_per_measure)

    def assign_start(self, note):
        if hasattr(note, "start"):
            print("Note", note.note, "already has start in measure", self.number)
        note.start = self.start
        if not note.grace:
            note.duration_clocks = fraction(note.duration, Divisions_per_clock)
        print_object = ""
        if hasattr(note, "print_object"):
            if note.print_object != 'no':
                print("got note with print-object != 'no'", note.print_object, "in measure", self.number)
            if self.trace_no_print:
                if note.rest:
                    print("got rest note with print-object", note.print_object, 
                          "in measure", self.number)
                elif note.cue:
                    print("got cue note with print-object", note.print_object,
                          "in measure", self.number)
                elif note.grace:
                    print("got grace note with print-object", note.print_object,
                          "in measure", self.number)
                else:
                    print("got note", note.note, "with print-object", note.print_object,
                          "in measure", self.number)
            print_object = f" print_object={note.print_object}"
            if note.print_object == 'no':
                note.ignore = True
        if note.rest:
            if self.number == self.trace:
                print(f"rest voice={note.voice}, start={self.start}, "
                      f"duration_clocks={note.duration_clocks}{print_object}")
            self.inc_start(note.duration_clocks)
            if note.tags:  # e.g., "fermata"
                note.midi_note = -1  # to sort last with notes of equal starts 
            else:
                note.ignore = True
            return
        if note.cue:
            if self.number == self.trace:
                print(f"Got cue note {note.note}, voice={note.voice} "
                      f"in measure {self.number}{print_object}")
            note.ignore = True
            return
        if note.chord:
            note.start = self.last_start
            if self.number == self.trace:
                print(f"note {note.note} chord, voice={note.voice}, start={note.start}, "
                      f"duration_clocks={note.duration_clocks} doesn't count{print_object}")
        elif note.grace:
            if self.number == self.trace:
                print(f"note {note.note} grace, voice={note.voice}, start={note.start}, "
                      f"no duration{print_object}")
        else:
            duration_clocks = note.duration_clocks
            if note.time_modification is None:
                if self.number == self.trace:
                    print(f"note {note.note}, voice={note.voice}, start={note.start}, "
                          f"duration_clocks={duration_clocks}{print_object}")
            else:
                actual_notes = note.time_modification.actual_notes
                normal_notes = note.time_modification.normal_notes
                normal_duration = Note_durations[note.type]  # in clocks
                actual_duration = fraction(normal_duration * normal_notes, actual_notes)
                if self.time_modifications and self.number == self.trace:
                    print(f"got time_modification({actual_notes=}, {normal_notes=}) "
                          f"in measure {self.number}, {duration_clocks=}, {actual_duration=}")
                duration_clocks = actual_duration
                if self.number == self.trace:
                    print(f"note {note.note} {note.type}, voice={note.voice}, "
                          f"tuplet({normal_notes}/{actual_notes}) "
                          f"start={self.start}, duration_clocks={duration_clocks}{print_object}")
            self.inc_start(duration_clocks)

    def inc_start(self, amount):
        self.last_start = self.start
        self.start += amount
        if self.start.denominator == 1:  # ints have a numerator and denominator too!
            self.start = self.start.numerator
        if self.start > self.longest:
            self.longest = self.start


def assign_parts(parts, time_modification=False, trace=None, trace_no_print=False):
    r'''Assign starts to all notes in all measures in all parts in parts.

    Assigns the following to the info for each part:
        part_duration_clocks - the number of clocks in the associated part
    '''
    global Divisions, Divisions_per_clock, Divisions_per_16th, Time
    global Divisions_per_measure, Clocks_per_measure, Measure_start, First_tie_notes, Last_tie_notes
    for info, measures in parts:
        Divisions = Divisions_per_clock = Divisions_per_16th = Time \
                  = Divisions_per_measure = Clocks_per_measure \
                  = None
        Measure_start = 0
        First_tie_notes = {}  # note: note; e.g., "E4": <note>
        Last_tie_notes = {}
        for i, measure in enumerate(measures):
            assign_measure(measure, i, time_modification, trace, trace_no_print)
        part_duration_clocks = Measure_start       # in clocks
        expected_duration_clocks = (i + 1) * Clocks_per_measure
        info.part_duration_clocks = part_duration_clocks
        print(f"Part {info.id}, {i + 1} measures, duration_clocks {part_duration_clocks} -- "
              f"expected {expected_duration_clocks}")
    print("Modifiers_seen:")
    for modifier in sorted(Modifiers_seen):
        print('  ', modifier)


def run():
    import argparse
    from .parse_xml import parse
    from .unroll_repeats import unroll_parts
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", "-m", metavar="MEASURE", default=None)
    parser.add_argument("--trace-no-print", "-n", action="store_true", default=False)
    parser.add_argument("--time-modifications", "-t", action="store_true", default=False)
    parser.add_argument("musicxml_file")

    args = parser.parse_args()

    parts = parse(args.musicxml_file)
    new_parts = unroll_parts(parts)
    assign_parts(new_parts, args.time_modifications, args.trace, args.trace_no_print)

