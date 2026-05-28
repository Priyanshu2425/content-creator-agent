"""``split-broll`` style: a 50/50 split with b-roll above the host, cutting between three modes.

Composes on the base authoring prompt (so the loop contract and kernel vocabulary stay in one
place) and adds the creative directive: arrange the short as a sequence of scenes that switch
between full host, full b-roll, and a ``split-h`` 50/50 with b-roll on top and the host on the
bottom. Everything it asks for is expressible with the existing tools (``add_scene`` with
``layout="split-h"`` + ``layout_params={"ratio": 0.5}``, two ``fill_region`` calls into ``top`` and
``bottom``), so no new kernel capability is required.
"""

from __future__ import annotations

from videogen.agent.prompts import SYSTEM_PROMPT

_STYLE = """\
## Style: split b-roll over host

Compose this short by cutting between three scene modes. Pick the mode per moment from the brief \
and the transcript -- do not stay in one mode for the whole video:

- FULL HOST: a `full` scene filled with the host (a-roll). Use it to open, to land a personal \
point, and whenever the words carry the moment with no b-roll to show.
- FULL B-ROLL: a `full` scene filled with a b-roll asset. Use it for an establishing beat or to \
let a strong visual breathe on its own.
- SPLIT (b-roll over host): a `split-h` scene with `layout_params` `{"ratio": 0.5}` -- fill the \
`top` region with the b-roll and the `bottom` region with the host. Use it when the host is \
explaining something the b-roll illustrates, so the viewer sees both at once.

Rules for this style:
- The host recording is the a-roll and the voiceover master clock; it is present in FULL HOST and \
in the `bottom` of every SPLIT scene. B-roll only ever appears in FULL B-ROLL or the `top` of a \
SPLIT.
- In `split-h`, `top` is the upper half and `bottom` is the lower half -- so b-roll goes in `top`, \
host in `bottom`. Keep `ratio` at 0.5 unless the brief asks for an uneven split.
- Mind the output canvas shape in the Media Manifest. On a tall (portrait) canvas each half of a \
`split-h` is a wide, near-square box, so a tall b-roll clip will be center-cropped to fill it -- \
prefer FULL B-ROLL for footage that must be seen uncropped.
- Portrait a-roll in `bottom`: if the a-roll (host recording) is portrait (9:16), its default \
center-cover in the wide bottom box will show the chest, cutting off the face. After `fill_region` \
call `set_crop` on the `bottom` region with `{"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.5}` \
to anchor the crop to the top of the source (where the face is). This crops to the top half of the \
portrait source -- a 9:8 window -- which matches the box aspect ratio and keeps the face in frame.
- Whoosh cuts: after every FULL HOST → FULL B-ROLL, FULL HOST → SPLIT, or SPLIT → FULL B-ROLL \
boundary, call `add_transition` with `kind="whoosh"` on that scene. These are the high-energy \
smash cuts where the audio accent lands hardest. Do NOT add a whoosh on a B-ROLL → HOST return \
cut (those land better as silent cuts) or on a crossfade.
- Scenes still tile the timeline without overlaps or gaps, and every span stays within the \
voiceover duration. Cut between modes on sentence or phrase boundaries from the transcript.
"""

SPLIT_BROLL_PROMPT = SYSTEM_PROMPT + "\n\n" + _STYLE
