"""Fakes of the Live API objects used by the Remote Script tests."""
import math


def _fmt_hz(hz):
    return "%.2f kHz" % (hz / 1000.0) if hz >= 1000 else "%.1f Hz" % hz


def _fmt_ms(ms):
    return "%.2f s" % (ms / 1000.0) if ms >= 1000 else "%.1f ms" % ms


def log_hz(raw):
    """Normalised 0..1 on a log curve 10 Hz .. 22 kHz."""
    return _fmt_hz(10.0 * (2200.0 ** raw))


def inverse_hz(raw):
    """Display DEcreases as raw grows (22 kHz at min, 10 Hz at max)."""
    return log_hz(1.0 - raw)


def exp_ms(raw):
    """Normalised 0..1 on an exponential curve 1 ms .. 10 s."""
    return _fmt_ms(10000.0 ** raw)


def db_curve(raw):
    """-inf dB at raw 0, 0 dB at raw 1 (20*log10)."""
    if raw <= 0.0:
        return "-inf dB"
    return "%.1f dB" % (20.0 * math.log10(raw))


def percent(raw):
    return "%.1f %%" % (raw * 100.0)


class FakeParam(object):
    def __init__(self, name, value=0.0, vmin=0.0, vmax=1.0, default=None, items=None, enabled=True, curve=None):
        self.curve = curve
        self.name = name
        self.original_name = name
        self.value = value
        self.min = vmin
        self.max = vmax
        self.default_value = value if default is None else default
        self.value_items = tuple(items or ())
        self.is_quantized = bool(items)
        self.is_enabled = enabled

    def str_for_value(self, v):
        if self.is_quantized:
            return self.value_items[int(v)]
        if self.curve is not None:
            return self.curve(v)
        return "%.2f" % v


class NoDisplayParam(FakeParam):
    """A parameter whose Live object has no str_for_value."""
    str_for_value = None


class FakeDevice(object):
    def __init__(self, name, class_name=None, type_int=1, params=None):
        self.name = name
        self.class_name = class_name or name.replace(" ", "")
        self.type = type_int
        self.parameters = [FakeParam("Device On", 1.0, 0.0, 1.0, items=("Off", "On"))]
        self.parameters.extend(params or [])
        self.is_active = True


def make_operator():
    return FakeDevice("Operator", "Operator", 1, [
        FakeParam("Filter Freq", 0.5, 0.0, 1.0, 1.0),
        FakeParam("Osc-A Wave", 0.0, 0.0, 3.0, 0.0, items=("Sine", "Saw D", "Square", "Noise")),
        FakeParam("Locked", 0.2, enabled=False),
    ])


class FakeNote(object):
    def __init__(self, pitch, start_time, duration, velocity, mute):
        self.pitch = pitch
        self.start_time = start_time
        self.duration = duration
        self.velocity = velocity
        self.mute = mute


class FakeLive(object):
    """Minimal stand-in for the `Live` module (Live.Clip.MidiNoteSpecification)."""

    class Clip(object):
        class MidiNoteSpecification(object):
            def __init__(self, pitch, start_time, duration, velocity, mute=False):
                self.pitch = pitch
                self.start_time = start_time
                self.duration = duration
                self.velocity = velocity
                self.mute = mute

        class Clip(object):
            def add_new_notes(self):
                pass

        class ClipSlot(object):
            pass

    class Track(object):
        class Track(object):
            pass


class _BaseClip(object):
    def __init__(self, length):
        self.length = length
        self.name = ""
        self.is_playing = False
        self.notes = []   # list of (pitch, start, duration, velocity, mute)
        self.removed_with = None

    def fire(self):
        self.is_playing = True

    def stop(self):
        self.is_playing = False


class ModernClip(_BaseClip):
    def add_new_notes(self, specs):
        for s in specs:
            self.notes.append((s.pitch, s.start_time, s.duration, s.velocity, s.mute))

    def get_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        return [FakeNote(*n) for n in self.notes
                if from_pitch <= n[0] < from_pitch + pitch_span and from_time <= n[1] < from_time + time_span]

    def remove_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        self.removed_with = "extended"
        self.notes = []


class LegacyClip(_BaseClip):
    def set_notes(self, notes):
        self.notes.extend(notes)

    def get_notes(self, from_time, from_pitch, time_span, pitch_span):
        return tuple(n[:1] + n[1:] for n in self.notes)

    def remove_notes(self, from_time, from_pitch, time_span, pitch_span):
        self.removed_with = "legacy"
        self.notes = []


class FakeClipSlot(object):
    clip_class = ModernClip

    def __init__(self):
        self.clip = None

    @property
    def has_clip(self):
        return self.clip is not None

    def create_clip(self, length):
        if self.clip is not None:
            raise RuntimeError("slot has a clip")
        self.clip = self.clip_class(length)

    def delete_clip(self):
        self.clip = None

    def fire(self):
        if self.clip:
            self.clip.fire()

    def stop(self):
        if self.clip:
            self.clip.stop()


class AudioClipSlot(FakeClipSlot):
    def create_audio_clip(self, path):
        self.clip = ModernClip(8.0)
        self.clip.name = path.rsplit("/", 1)[-1]


class _Val(object):
    def __init__(self, value):
        self.value = value


class FakeMixer(object):
    def __init__(self):
        self.volume = _Val(0.85)
        self.panning = _Val(0.0)


class FakeTrack(object):
    def __init__(self, name, midi=True, foldable=False, slot_class=FakeClipSlot, scenes=4):
        self.name = name
        self.color_index = 0
        self.has_midi_input = midi
        self.has_audio_input = not midi
        self.is_foldable = foldable
        self.mute = False
        self.solo = False
        self._arm = False
        self.can_be_armed = not foldable
        self.devices = []
        self.clip_slots = [slot_class() for _ in range(scenes)]
        self.mixer_device = FakeMixer()
        self.slot_class = slot_class

    @property
    def arm(self):
        if not self.can_be_armed:
            raise RuntimeError("group tracks cannot be armed")
        return self._arm

    @arm.setter
    def arm(self, v):
        if not self.can_be_armed:
            raise RuntimeError("group tracks cannot be armed")
        self._arm = v

    def delete_device(self, i):
        del self.devices[i]


class TrackWithInsert(FakeTrack):
    """Live 12.3+ style track."""
    insert_calls = None
    fail = False

    def insert_device(self, name, index=None):
        if self.insert_calls is None:
            self.insert_calls = []
        self.insert_calls.append((name, index))
        if self.fail:
            raise RuntimeError("no such device")
        if name.lower() not in KNOWN_DEVICES:
            raise RuntimeError("unknown device %s" % name)
        type_int, cls = KNOWN_DEVICES[name.lower()]
        dev = FakeDevice(name, cls, type_int)
        if type_int == 1:
            self.devices = [d for d in self.devices if d.type != 1]
            self.devices.insert(0 if index is None else index, dev)
        else:
            self.devices.insert(len(self.devices) if index is None else index, dev)
        return dev


KNOWN_DEVICES = {
    "operator": (1, "Operator"),
    "wavetable": (1, "InstrumentVector"),
    "reverb": (2, "Reverb"),
    "arpeggiator": (4, "MidiArpeggiator"),
}


class FakeView(object):
    def __init__(self):
        self.selected_track = None


class FakeSong(object):
    def __init__(self, with_insert=False, slot_class=FakeClipSlot):
        self.tracks = []
        self.return_tracks = [FakeTrack("A-Reverb", midi=False)]
        self.view = FakeView()
        self.tempo = 120.0
        self.signature_numerator = 4
        self.signature_denominator = 4
        self.is_playing = False
        self.can_undo = False
        self.can_redo = False
        self.undone = 0
        self.redone = 0
        self.scenes = [object() for _ in range(4)]
        self._track_class = TrackWithInsert if with_insert else FakeTrack
        self._slot_class = slot_class

    def _new(self, name, midi, index):
        track = self._track_class(name, midi=midi, slot_class=self._slot_class, scenes=len(self.scenes))
        if index == -1:
            self.tracks.append(track)
        else:
            self.tracks.insert(index, track)
        return track

    def create_midi_track(self, index):
        self._new("%d-MIDI" % (len(self.tracks) + 1), True, index)

    def create_audio_track(self, index):
        self._new("%d-Audio" % (len(self.tracks) + 1), False, index)

    def delete_track(self, i):
        del self.tracks[i]

    def create_scene(self, index):
        self.scenes.append(object())
        for t in self.tracks:
            t.clip_slots.append(t.slot_class())

    def start_playing(self):
        self.is_playing = True

    def stop_playing(self):
        self.is_playing = False

    def undo(self):
        self.undone += 1
        self.can_undo = False

    def redo(self):
        self.redone += 1


class FakeBrowserItem(object):
    def __init__(self, name, children=None, loadable=False, device=False, uri=None, loads=None, folder=None):
        self.name = name
        self.children = tuple(children or ())
        self.is_loadable = loadable
        self.is_device = device
        self.is_folder = bool(self.children) if folder is None else folder
        if uri is not None:
            self.uri = uri
        self.loads = loads   # (name, class_name, type_int) devices appended on load_item


class FakeBrowser(object):
    CATS = ("instruments", "sounds", "drums", "audio_effects", "midi_effects", "user_library",
            "packs", "samples", "clips", "plugins", "max_for_live")

    def __init__(self, song):
        self._song = song
        self.loaded = []
        self.user_folders = []
        for c in self.CATS:
            setattr(self, c, FakeBrowserItem(c.title()))

    def load_item(self, item):
        self.loaded.append(item)
        track = self._song.view.selected_track
        if track is None or item.loads is None:
            return
        name, cls, type_int = item.loads
        dev = FakeDevice(name, cls, type_int)
        if type_int == 1:
            track.devices = [d for d in track.devices if d.type != 1]
            track.devices.insert(0, dev)
        else:
            track.devices.append(dev)


class SilentBrowser(FakeBrowser):
    """load_item does nothing (async-load simulation)."""

    def load_item(self, item):
        self.loaded.append(item)


class FakeApplication(object):
    def __init__(self, song, browser_class=FakeBrowser):
        self.browser = browser_class(song)

    def get_major_version(self):
        return 12

    def get_minor_version(self):
        return 1

    def get_bugfix_version(self):
        return 5


def populate_browser(browser):
    """A small realistic tree."""
    browser.instruments = FakeBrowserItem("Instruments", [
        FakeBrowserItem("Operator", [
            FakeBrowserItem("Bell", [FakeBrowserItem("Tubular Bell.adv", loadable=True, uri="query:Op#Tubular", loads=("Operator", "Operator", 1))]),
        ], loadable=True, device=True, uri="query:Instruments#Operator", loads=("Operator", "Operator", 1)),
        FakeBrowserItem("Wavetable", loadable=True, device=True, uri="query:Instruments#Wavetable", loads=("Wavetable", "InstrumentVector", 1)),
    ])
    browser.audio_effects = FakeBrowserItem("Audio Effects", [
        FakeBrowserItem("Reverb", loadable=True, device=True, uri="query:AudioFx#Reverb", loads=("Reverb", "Reverb", 2)),
    ])
    browser.midi_effects = FakeBrowserItem("MIDI Effects", [
        FakeBrowserItem("Arpeggiator", loadable=True, device=True, uri="query:MidiFx#Arp", loads=("Arpeggiator", "MidiArpeggiator", 4)),
    ])
    browser.sounds = FakeBrowserItem("Sounds", [
        FakeBrowserItem("Piano & Keys", [
            FakeBrowserItem("Grand Piano.adg", loadable=True, uri="query:Sounds#Grand", loads=("Instrument Rack", "InstrumentGroupDevice", 1)),
            FakeBrowserItem("Piano Pad.adv", loadable=True),   # no uri attribute -> path is the uri
        ]),
    ])
    browser.user_folders = [FakeBrowserItem("MyFolder", [FakeBrowserItem("Accordion.wav", loadable=True, uri="file:acc")])]
    return browser


def make_world(with_insert=False, midi_tracks=1, audio_tracks=0, slot_class=FakeClipSlot, browser_class=FakeBrowser):
    song = FakeSong(with_insert=with_insert, slot_class=slot_class)
    for i in range(midi_tracks):
        song._new("%d-MIDI" % (i + 1), True, -1)
    for i in range(audio_tracks):
        song._new("%d-Audio" % (i + 1), False, -1)
    if song.tracks:
        song.view.selected_track = song.tracks[0]
    app = FakeApplication(song, browser_class)
    populate_browser(app.browser)
    return song, app


class FakeCInstance(object):
    def __init__(self, song, app):
        self._song = song
        self._app = app
        self.messages = []
        self.shown = []

    def song(self):
        return self._song

    def application(self):
        return self._app

    def log_message(self, msg):
        self.messages.append(msg)

    def show_message(self, msg):
        self.shown.append(msg)


def make_dispatcher(song, app, with_index=True, live_module=None, index_complete=True):
    from AbletonHelper.browser_index import BrowserIndex
    from AbletonHelper.context import Context
    from AbletonHelper.dispatcher import Dispatcher
    logs = []
    index = BrowserIndex(app, log=logs.append) if with_index else None
    if index is not None and index_complete:
        index.start(0)
        while index._gen is not None:
            index.step(1.0, 100000)
    ctx = Context(song, app, index, log=logs.append, live_module=live_module)
    d = Dispatcher(ctx)
    d.logs = logs
    return d


def call(d, command, **params):
    """Run a command through the full envelope path; returns the envelope."""
    return d.handle({"id": "1", "command": command, "params": params})


def result(d, command, **params):
    env = call(d, command, **params)
    assert env["ok"], env
    return env["result"]


def error(d, command, **params):
    env = call(d, command, **params)
    assert not env["ok"], env
    return env["error"]["code"]
