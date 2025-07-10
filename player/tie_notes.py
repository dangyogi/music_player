# tie_notes.py


def tie_notes(measures, trace_measure=None, trace=False):
    first_notes = {}
    for measure in measures:
        sorted_notes = [child for child in measure.children if child.name == 'note' and not child.ignore]
        sorted_notes.sort(key=lambda note: (note.start, -note.midi_note))
        measure.sorted_notes = sorted_notes
        if str(measure.number) == trace_measure:
            print(f"measure {measure.number}:")
        for note in sorted_notes:
            if str(measure.number) == trace_measure:
                print(f"  note {note.note} start={note.start}, duration={note.duration}, tie={note.tie}")
            tie_note(measure.number, note, first_notes, trace)

def tie_note(measure, note, first_notes, trace=False):
    if 'start' in note.tie and 'stop' not in note.tie:
        if note.note in first_notes:
            print(f"tie_note duplicate start for note {note.note} in measure {measure}")
        first_notes[note.note] = note
        return
    if note.note in first_notes:
        first_notes[note.note].duration += note.duration
        if trace:
            print(f"tie_note adding {note.duration} for {note.note} from measure {measure}, "
                  f"first_note.duration now {first_notes[note.note].duration}")
        note.ignore = True
    if 'stop' in note.tie and 'start' not in note.tie:
        if note.note not in first_notes:
            print(f"tie_note got unmatched 'stop' for {note.note} in measure {measure}, "
                  f"first_notes: {list(first_notes.keys())}")
        else:
            del first_notes[note.note]

def tie_parts(parts, trace_measure=None, trace=False):
    for _, measures in parts:
        tie_notes(measures, trace_measure, trace)



if __name__ == "__main__":
    import argparse
    from parse_xml import parse
    from unroll_repeats import unroll_parts
    from assign_starts import assign_parts
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", "-t", action="store_true", default=False)
    parser.add_argument("--measure", "-m", default=None)
    parser.add_argument("--no-skip-no-print", "-S", action="store_false", default=True)
    parser.add_argument("musicxml_file")

    args = parser.parse_args()

    parts = parse(args.musicxml_file)
    new_parts = unroll_parts(parts)
    assign_parts(new_parts, skip_no_print=args.no_skip_no_print)
    tie_parts(new_parts, args.measure, args.trace)

