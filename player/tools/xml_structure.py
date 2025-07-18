# xml_structure.py

from collections import defaultdict, Counter
from zipfile import ZipFile
from xml.etree.ElementTree import parse, fromstring


container = 'META-INF/container.xml'

def run(filename):
    with ZipFile(filename) as xml_zip:
        #print(xml_zip.namelist())
        container_xml = xml_zip.read(container)
        #print(container_xml)
        root = fromstring(container_xml)
        print('iter', [e.tag for e in root])
        rootfiles = root.find('rootfiles')
        files = [x.get('full-path') for x in rootfiles.findall('rootfile')]
        assert len(files) == 1, f"expected one file in musicxml zip file, got {len(files)}"

        musicxml = files[0]
        root = fromstring(xml_zip.read(musicxml))
        print("root", root.tag)
        count = Counter()
        tags = defaultdict(set)
        attributes = defaultdict(set)
        def load_tags(e):
            count[e.tag] += 1
            attributes[e.tag].update(e.keys())
            for child in e:
                tags[e.tag].add(child.tag)
                load_tags(child)
        load_tags(root)

        def dump(tag, indent=0):
            if tag in seen:
                print(' ' * indent, '*', tag, sep='', end='')
            else:
                print(' ' * indent, tag, sep='', end='')
                seen.add(tag)
            if tag in attributes and attributes[tag]:
                print(f"{tuple(sorted(attributes[tag]))}", end='')
            print(f": {count[tag]}")
            if tag in tags and tags[tag]:
                for child in sorted(tags[tag]):
                    dump(child, indent + 2)
        seen = set()
        dump(root.tag)
        assert len(seen) == len(attributes), f"{len(seen)=} != {len(attributes)=}"
        assert len(seen) == len(count), f"{len(seen)=} != {len(count)=}"

def script():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("musicxml_file")

    args = parser.parse_args()

    run(args.musicxml_file)


if __name__ == "__main__":
    script()
