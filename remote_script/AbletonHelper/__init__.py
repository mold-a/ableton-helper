"""AbletonHelper MIDI Remote Script (Live 11 / 12).

Select 'AbletonHelper' in Preferences -> Link, Tempo & MIDI -> Control Surface.
"""

from .surface import AbletonHelper


def create_instance(c_instance):
    return AbletonHelper(c_instance)
