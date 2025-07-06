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
            ans = 1
            if tag in attributes and attributes[tag]:
                print(' ' * indent, f"{tag}{tuple(sorted(attributes[tag]))}: {count[tag]}", sep='')
            else:
                print(' ' * indent, f"{tag}: {count[tag]}", sep='')
            if tag in tags and tags[tag]:
                for child in sorted(tags[tag]):
                    ans += dump(child, indent + 2)
            return ans
        num_tags = dump(root.tag)
        assert num_tags == len(tags), f"{num_tags=} != {len(tags)=}"
        assert num_tags == len(attributes), f"{num_tags=} != {len(attributes)=}"
        assert num_tags == len(count), f"{num_tags=} != {len(count)=}"



if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("musicxml_file")

    args = parser.parse_args()

    run(args.musicxml_file)
