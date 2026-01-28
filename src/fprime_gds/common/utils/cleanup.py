from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.models.serialize.type_base import DictionaryType
from fprime_gds.common.loaders.json_loader import JsonLoader

def globals_cleanup():
    """Cleans up all global/cached constructs.
    
    This is useful for example to start fresh between tests that may load
    some of these up.
    """

    # Clear out ConfigManager singleton
    ConfigManager._ConfigManager__instance = None  # Python name mangling

    # Clear out cached constructs for loaded DictionaryType
    DictionaryType._CONSTRUCTS.clear()

    # Clear out cached constructs at the JsonLoader level
    JsonLoader.parsed_types.clear()

