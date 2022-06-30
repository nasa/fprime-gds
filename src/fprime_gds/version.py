""" Versioning information for the GDS

This file contains versioning and compatibility definitions for the GDS tool set.
"""

# Currently the GDS is backwards compatible with all dictionaries. 9,9,9 effectively disables this check. It will be
# revisited with a schema version in the next release.
MINIMUM_SUPPORTED_FRAMEWORK_VERSION = (0, 0, 0)
MAXIMUM_SUPPORTED_FRAMEWORK_VERSION = (9, 9, 9)
