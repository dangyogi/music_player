# set_colors.py

from itertools import zip_longest
import xml.etree.ElementTree as ET


Colors = {
    1: '#FF0000',
    2: '#00FF00',
    3: '#0000FF',
    4: '#00FFFF',
    5: '#FF00FF',
    6: '#FFFF00',
    7: '#404040',
}

def fix_measure(measure):
    notes = list(measure.findall('note'))
    for note in notes:
        voice = int(find1(note, 'voice').text)
        print(f"{voice=}")
        note.set('color', Colors[voice])

def parse(xmlfilename, no_write=False):
    r'''Returns a list of Parts.
    '''
    global Tree
    Tree = ET.parse(xmlfilename)
    root = Tree.getroot()
    assert root.tag == "score-partwise", f"Expected root tag of 'score-partwise', got {root.tag}"
    part = find1(root, 'part')
    measures = list(part.findall('measure'))
    print(f"{len(measures)=}")
    for measure in measures:
        fix_measure(measure)
    if not no_write:
        if not xmlfilename.endswith('-color.xml'):
            xmlfilename = xmlfilename[:-4] + '-color.xml'
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
