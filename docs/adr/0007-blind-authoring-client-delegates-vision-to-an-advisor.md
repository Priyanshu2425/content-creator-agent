# An image-blind authoring client delegates vision to an advisor model

The authoring loop's vision tools ([0004](./0004-tool-driven-incremental-authoring.md)) feed frames back as image `ToolResult`s, but several `ModelClient`s have no image-input channel: `ClaudeCodeClient` ([0006](./0006-claude-code-via-agent-sdk-as-single-turn-model.md)) drives a one-shot text query, and the Gemini/OpenAI-compatible adapters stringify image results away. Such a client authors **blind**. Rather than leave it guessing at placement, framing, and cropping, we add a capability signal and a vision-advice seam: a `ModelClient` may set `consumes_images: bool` (the loop reads it with `getattr(client, "consumes_images", True)`, so existing and scripted clients are unaffected), and when a client cannot see **and** a `VisionAdvisor` is wired, the loop drops the image vision tools (`render_still`/`scene_preview`) and advertises `consult_placement` instead — a tool that renders the current frame, asks a vision-capable advisor model (Gemini today) a text question, and returns its text advice as the tool result. So the blind client gets a *text-return* vision channel in place of the image-return one it cannot use.

The advisor is a Protocol in a neutral module (`agent/vision_advice.py`); the concrete `GeminiVisionAdvisor` (`agent/gemini_vision.py`) is constructed only in `cli.build_default_pipeline`, so the loop and services never import a provider SDK — the same Protocol/concrete split as `review.py`/`gemini_review.py`. Sighted clients (`AnthropicModelClient`, `consumes_images = True`) keep the image vision tools and ignore the advisor. The default pipeline pairs the blind `ClaudeCodeClient` author with a Gemini advisor (and Gemini still serves the full-motion `ReviewAgent`).

## Considered Options

- **`isinstance` checks in the loop** — rejected: couples the loop to concrete client types; the capability flag is open to any future blind client.
- **Each blind client carries its own advisor internally** — rejected: duplicates the render-a-still path and breaks the invariant that the loop is the single owner of vision and the tool surface.
- **Reuse the `ReviewAgent` seam for stills** — rejected: different return shape (free-text advice vs. structured timestamped `ReviewFeedback`) and different cost profile (a small inline image vs. a full video upload).

## Consequences

- Each `consult_placement` costs a still render **plus** an advisor call; it counts against the loop's existing op budget, and the advice prompt/tool description tell the agent to consult sparingly.
- A blind client with no advisor (or no backend) simply falls back to the plain tool list — no advice tool, no regression.
