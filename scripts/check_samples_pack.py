#!/usr/bin/env python3
"""Manual check (not a test): run the Sampler-preset generator on an UNPACKED sample pack and print the zone map.

It uses the synthetic Sampler template from the tests, so no Ableton Live is needed. The result is a real
.adv that Live can open IF the template matches the structure of your Live; for the final result use
`abhelper samples install <id>` which takes the template from your own Live installation.

  python scripts/check_samples_pack.py --sfz "<folder>/PRESET Button Accordion HN tuned.sfz" [--out preset.adv]
"""

import argparse
import gzip
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests" / "samples"))

from abhelper.samples.adv import (build_preset_xml, describe_parts, region_to_part,  # noqa: E402
                                  template_from_xml, write_adv)
from abhelper.samples.audioinfo import read_audio_info  # noqa: E402
from abhelper.samples.sfz import parse_sfz_file  # noqa: E402
from samples_testkit import synth_template_xml  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sfz", required=True, help="path to the .sfz file inside the unpacked pack")
    ap.add_argument("--out", help="write the generated .adv here")
    ap.add_argument("--name", default="AbletonHelper Check")
    ap.add_argument("--library", default="C:\\Users\\me\\User Library", help="pretend User Library (for the paths in the preset)")
    args = ap.parse_args(argv)

    sfz = Path(args.sfz)
    inst = parse_sfz_file(sfz)
    template = template_from_xml(synth_template_xml(), "synthetic")
    parts = []
    for region in inst.regions:
        src = sfz.parent.joinpath(*PurePosixPath(region.sample).parts)
        info = read_audio_info(src)
        parts.append(region_to_part(region, info, src, "Samples/AbletonHelper/check/" + region.sample))
    parts.sort(key=lambda s: (s.lokey, s.lovel))
    print("SFZ: %s" % sfz.name)
    print("Зон: %d, пропущено: %d" % (len(parts), len(inst.skipped)))
    for reason in inst.skipped[:3]:
        print("  пропущено: " + reason)
    print("Огибающая SFZ: %s" % inst.envelope)
    print()
    print("\n".join(describe_parts(parts)))
    xml = build_preset_xml(template, parts, args.name, inst.envelope or None)
    root = ET.fromstring(xml.encode("utf-8"))
    env = {e.tag: e.find("Manual").get("Value") for e in root.find("MultiSampler/VolumeAndPan/Envelope")}
    print("\nОгибающая в пресете (мс / уровни):", env)
    print("Filter on: %s, Lfo on: %s" % (root.find("MultiSampler/Filter/IsOn/Manual").get("Value"),
                                          root.find("MultiSampler/Lfo/IsOn/Manual").get("Value")))
    if args.out:
        write_adv(args.out, xml)
        with gzip.open(args.out, "rb") as fh:
            ET.fromstring(fh.read())
        print("\nЗаписано: %s (gzip XML читается обратно)" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
