"""Sound engine: recipes, browser presets and native-device synthesis for Ableton Live."""

from .calibration import dump_device_catalog, merge_catalog, recipe_device_names
from .demo import DemoClip, build_demo, generate_notes
from .engine import SoundEngine, SoundRequest, SoundResult
from .library import RecipeLibrary, RecipeMatch
from .schema import validate_recipe

__all__ = [
    "RecipeMatch", "SoundRequest", "SoundResult", "RecipeLibrary", "SoundEngine", "validate_recipe",
    "dump_device_catalog", "merge_catalog", "recipe_device_names", "build_demo", "generate_notes", "DemoClip",
]
