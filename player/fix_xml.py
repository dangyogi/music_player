# fix_xml.py

from itertools import zip_longest
import xml.etree.ElementTree as ET


XML_changed = False
Divisions = None  # divisions per quarter note
Time = None
Divisions_per_measure = None

def fix_measure(measure):
    global Divisions, Time, Divisions_per_measure
    number = int(measure.attrib['number'])
    children = []
    for child in measure:
        if child.tag == 'attributes':
            divisions = child.find('divisions')
            if divisions is not None:
                Divisions = int(divisions.text)
                if Time is not None:
                    calc_div_per_measure(number)
            time = child.find('time')
            if time is not None:
                Time = int(find1(time, 'beats').text), int(find1(time, 'beat-type').text)
                if Divisions is not None:
                    calc_div_per_measure(number)
        elif child.tag in ('backup', 'forward', 'note'):
            children.append(child)
    errors, changes = fix_children(measure, children)
    return errors, changes

def calc_div_per_measure(measure_number):
    global Divisions_per_measure
    dpm = Divisions * (Time[0] * 4 / Time[1])
    if dpm == int(dpm):
        Divisions_per_measure = int(dpm)
    else:
        Divisions_per_measure = dpm
    print(f"Measure {measure_number}: divisions={Divisions}, div_per_measure={Divisions_per_measure}")
    print()

def fix_children(measure, children, trace=1):
    measure_num = int(measure.attrib['number'])
    #print(f"got measure {measure_num} with {len(children)} children")
    voices, errors, changes = collect_voices(measure, children)
    if errors or changes:
        print_voices(measure_num, voices)
    return errors, changes

def print_voices(measure_num, voices):
    print(f"measure {measure_num}")
    print()
    #print(voices)
    #return
    width = 20
    for voice_num, _, duration in voices:
        print_col(f"voice {voice_num}", width)
    print()
    for voice_num, _, duration in voices:
        print_col(f"duration {duration}", width)
    print()
    print()
    elements = [el for _, el, _ in voices]
    for lines in zip_longest(*elements):
        for element in lines:
            if element is None:
                print_col("", width)
            else:
                print_col(print_elem(measure_num, element), width)
        print()
    print()

def print_elem(measure_num, elem):
    if elem.tag == 'note':
        if elem.find('rest') is not None:
            note = "rest"
        else:
            try:
                pitch = find1(elem, 'pitch')
                alter = pitch.find('alter')
                note = f"{find1(pitch, 'step').text}{find1(pitch, 'octave').text}"
                if alter is not None:
                    note += f"{int(alter.text):+}"
            except AssertionError:
                print("got AssertionError, measure", measure_num)
                ET.dump(elem)
                raise
        if elem.find('grace') is not None:
            note += ' grace'
        if elem.find('chord') is not None:
            note += ' chord'
        dur = get_duration(elem)
        note += f" {dur=}"
        if not get_print(elem):
            note += " NO"
        return note
    else:
        return f"{elem.tag} {find1(elem, 'duration').text}"

def print_col(s, width=20):
    print(f"{s:{width}}", end='')

def collect_voices(measure, children):
    global XML_changed
    voices = []
    errors = 0
    changes = 0
    measure_num = int(measure.attrib['number'])
    voice = []
    voice_num = None
    duration = 0
    elements_to_remove = []
    for child in children:
        if child.tag == 'note':
            new_voice = int(find1(child, 'voice').text)
            if voice_num is not None and new_voice != voice_num:
                if voice:
                    if duration != Divisions_per_measure:
                        print(f"Measure {measure_num}, voice {voice_num}, incorrect dur {duration}")
                        errors += 1
                    voices.append((voice_num, voice, duration))
                    voice = []
            voice_num = new_voice
            if child.find('chord') is None:
                duration += get_duration(child)
        elif child.tag == 'backup':
            if voice:
                if duration != Divisions_per_measure:
                    print(f"Measure {measure_num}, voice {voice_num}, incorrect dur {duration}")
                    errors += 1
                voices.append((voice_num, voice, duration))
                voice = []
            voice_num = None
            dur_elem = find1(child, 'duration')
            dur = int(dur_elem.text)
            if dur > duration:
                print(f"Measure {measure_num} got backup {dur} > {duration}, setting to {duration}")
                errors += 1
                dur = duration
                dur_elem.text = str(dur)
                XML_changed = True
                changes += 1
            duration -= dur
        elif child.tag == 'forward':
            dur_elem = find1(child, 'duration')
            dur = int(dur_elem.text)
            if duration + dur > Divisions_per_measure:
                print(f"Measure {measure_num} got forward {dur} past {Divisions_per_measure}, "
                      f"setting to {Divisions_per_measure - dur}")
                errors += 1
                dur = Divisions_per_measure - dur
                dur_elem.text = str(dur)
                XML_changed = True
                changes += 1
            duration += dur
        else:
            raise AssertionError(f"Measure {measure_num} got unknown tag {child.tag}")
        if voice and voice[-1].tag == 'backup' \
           and child.tag == 'note' and child.find('rest') is not None and not get_print(child):
            rest_dur = get_duration(child)
            print(f"Deleting non-printing rest after backup in measure {measure_num}")
            elements_to_remove.append(child)
            backup_dur_elem = find1(voice[-1], 'duration')
            backup_dur = int(backup_dur_elem.text) - rest_dur
            print("Changing backup duration to", backup_dur)
            backup_dur_elem.text = str(backup_dur)
            XML_changed = True
            changes += 1
        else:
            voice.append(child)
    if voice:
        if duration != Divisions_per_measure:
            print(f"Measure {measure_num}, voice {voice_num}, incorrect dur {duration}")
            errors += 1
        voices.append((voice_num, voice, duration))
    if elements_to_remove:
        XML_changed = True
        for element in elements_to_remove:
            measure.remove(element)
            changes += 1
    return voices, errors, changes


def get_duration(note):
    duration = note.find('duration')
    if duration is None:
        return 0
    return int(duration.text)

def get_print(note):
    return note.get('print-object', 'yes') == 'yes'

def parse(xmlfilename, no_write=False):
    r'''Returns a list of Parts.
    '''
    global Tree
    Tree = ET.parse(xmlfilename)
    root = Tree.getroot()
    assert root.tag == "score-partwise", f"Expected root tag of 'score-partwise', got {root.tag}"
    part = find1(root, 'part')
    measures = list(part.findall('measure'))
    errors = changes = 0
    for measure in measures:
        err, chg = fix_measure(measure)
        errors += err
        changes += chg
    print(f"Total of {errors} errors")
    print(f"Total of {changes} changes")
    if changes and not no_write:
        if not xmlfilename.endswith('-fix.xml'):
            xmlfilename = xmlfilename[:-4] + '-fix.xml'
        print("Saving changes to", xmlfilename)
        Tree.write(xmlfilename, encoding='UTF-8', xml_declaration=True)

def find1(root, tag):
    sp = list(root.findall(tag))
    assert len(sp) == 1, f"Expected 1 {tag} on {root.tag}, got {len(sp)}"
    return sp[0]



if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", "-w", action="store_true", default=False)
    parser.add_argument("score_xmlfile")

    args = parser.parse_args()

    parse(args.score_xmlfile, args.no_write)
