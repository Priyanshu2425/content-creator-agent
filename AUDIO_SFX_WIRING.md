# ✅ DONE: Wire AudioDeciderAgent SFX into Renderer

## What needs to happen

AudioDeciderAgent now annotates every `Scene` with `scene.audio.sound` (`click` / `whoosh` / `dramatic_whoosh`).  
These annotations are stored on the Composition but are **not yet played** in the rendered video.

## Steps to complete SFX wiring

### 1. Add SFX asset files
Place the three MP3s at:
```
src/videogen/backends/remotion/project/public/assets/sfx/click.mp3
src/videogen/backends/remotion/project/public/assets/sfx/whoosh.mp3
src/videogen/backends/remotion/project/public/assets/sfx/dramatic_whoosh.mp3
```

### 2. Update `compile_ir`
In `src/videogen/kernel/compile_ir.py`, after compiling scene layers, iterate over
`composition.scenes` and for each scene with `scene.audio is not None`, emit an IR audio node:

```python
if scene.audio is not None:
    ir_layers.append({
        "kind": "audio",
        "src": f"assets/sfx/{scene.audio.sound}.mp3",
        "start_frame": seconds_to_frame(scene.start, fps),
        "volume": 1.0,
    })
```

### 3. Verify Remotion handles the audio IR node
`RemotionBackend.HANDLED_KINDS` already includes `"audio"` — confirm the Remotion Node project
(`project/src/Main.tsx`) renders audio nodes from props correctly.

### 4. Test end-to-end
Run `videogen make` with a host recording and verify the three SFX play at the correct cut points
in the output mp4.

## Durations for reference
| Sound | Duration |
|---|---|
| `click` | 0.23s |
| `whoosh` | 0.57s |
| `dramatic_whoosh` | 1.92s |
