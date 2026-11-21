"""Runtime shim for Pyfa's eos package.

Pyfa's real config.py is GUI/wx-bound. Eos only reads these attributes, so this
shim provides them without any Pyfa GUI dependency. Shared by the browser runtime
and the build pipeline.
"""

debug = False
lang = "en"
translation_mapping = {}
savePath = None
saveDB = None
gamedata_version = None
gamedata_date = None
