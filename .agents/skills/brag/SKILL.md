---
name: brag
description: Generate shareable product launch videos (brag.mp4) with automated motion graphics, background music, and voiceover narration.
---

# Brag Skill — Launch Video Generator (Voiceover ON)

This workspace is configured with **Voiceover ON** by default for product launch video generation.

## Default Configuration
- **Voiceover:** `Enabled` (`--voice`)
- **TTS Engine:** Kokoro Local TTS (`af_heart`)
- **Audio Mixing:** Automatic background audio ducking (12%–15% volume during narration)
- **Output:** `brag-output/brag.mp4`

## Usage Instructions
When the user executes `/brag` or requests a launch/demo video:
1. Automatically include the `--voice` flag during video storyboard rendering:
   ```bash
   /brag --voice
   ```
2. For specific tones:
   ```bash
   /brag --voice --tone launch
   /brag --voice --tone polished
   ```
