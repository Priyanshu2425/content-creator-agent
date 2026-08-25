"""Caption library: the caption style registry + its built-in renderers (ADR 0010).

``registry`` holds the registry core (``get``/``list``/``compile``); the built-in styles live under
``generic`` and register themselves on import (triggered lazily by ``default_caption_registry``).
"""
