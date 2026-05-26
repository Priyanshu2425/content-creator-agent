# Kickoff input: recordings + assets + brief, host audio is the voiceover

To start a video the user provides a **host-cam recording** (its audio track *is* the master-clock `voiceover`), a set of **b-roll assets** (movie clips, screenshots) with optional hints, and a short **brief** (topic, target length, style, must-use moments). MediaService transcribes the host audio; the Agent decides structure, cuts, captions, and effects from there.

We chose this talking-head-first model over a **script-first / TTS-generative** front door (and over a fully pre-structured plan) so the system stays an authentic talking-head editor — the genre in the reference video — rather than a synthetic-voice generator. The choice is reversible-by-addition: because `voiceover` is just an asset, a standalone VO track or a script→TTS path can layer on later without changing the composition model or the pipeline.

## Consequences

- MediaService's transcription always targets the host recording's audio; the transcript is what `addCaptionsFromTranscript` and scene-timing decisions hang off.
- The front door requires the user to record themselves — there is no zero-footage path in v1 (script→TTS is the deferred escape hatch).
