# HuC6280 desktop verification — 2026-11-06

Desktop version **0.0.1**, Web Synth version **0.0.8**.

## Imported release

- Archive SHA-256: `b4653287847003db346a77e6a99986312f98224e36bc3019e510b43d994c0c28`.
- 51 files imported without rewriting browser modules, CSS, WASM or source receipts.
- `python3 scripts/import_release.py --check` passes after tests and native build.
- `.gitattributes` preserves imported bytes on Windows. Local edits can be
  recorded separately without replacing the original release hashes.

## Automated checks

| Check | Result |
| --- | --- |
| `npm ci` | 4 packages installed; audit reported 0 vulnerabilities |
| `npm test` | Python 21 passed; Node 42 passed |
| `cargo test --manifest-path src-tauri/Cargo.toml --locked --offline` | 24 passed; 2 opt-in physical-device tests ignored by default |
| `cargo fmt --manifest-path src-tauri/Cargo.toml --check` | Passed |
| `npm run test:browser` | Chromium and WebKit passed |
| Offline audio transport stress | Passed; simulated host, not a physical device |
| Final unsigned macOS app build | Passed, arm64 |

The [browser report](desktop_browser_20261106.json) uses the real HuC6280 WASM
and AudioWorklets with a mocked Tauri IPC host and muted speakers. It covers:

- Menu / Pin, native binary preset saving and cancelled save / reload / load.
- Six Wave voices, two Noise voices, the LFO pair and six DDA voices.
- Master 380%, Pitch, source edits and waveform drawing.
- VGM / VGZ import and Wave channel levels 23 / 24 grouped to 24.
- WAV conversion, embedded PCM preset saving and audio chooser cancellation
  preserving the previous Wave sound.
- Switching all sound sources to Native output stops held notes and resets
  Pitch while keeping the instrument. New performance input is blocked during
  switching. Native failure restores Web Audio.
- Finite nonzero captured PCM, one speaker AudioContext, no missing assets or
  page errors, and zero horizontal overflow at 390px.

See also the [transport model report](audio_transport_20261106.json).

## Physical native output

The initial sandboxed attempt could not enumerate CoreAudio devices. Repeating
the opt-in check outside the sandbox succeeded:

```sh
cargo test --manifest-path src-tauri/Cargo.toml --locked --offline native_device_continuous -- --ignored --nocapture
```

The default physical output accepted 30 seconds of silence at 48 kHz. It
consumed 1,440,256 frames, with **0 underruns** and 29 injected 25ms producer
delays. This directly tests the Rust CPAL service; it does not test continuous
WebView-to-native IPC or human listening. The quiet-tone smoke test was not run.

[Physical-output record](native_audio_20261106.json).

## Native macOS bundle

Final build command, after the audio-menu cancellation fix:

```sh
npm run build -- --bundles app --no-sign -- --locked --offline
```

Output:

```text
src-tauri/target/release/bundle/macos/Tetorica HuC6280 Synth.app
```

The executable is Mach-O arm64. Signing was explicitly skipped. The app was
launched and its real `tauri://localhost` window exposed the HuC6280 title,
Menu, Pin, Master / Pitch, keyboard and Wave / PCM volume-variant checkbox.
Pin state initialization was visible; a real native Pin toggle was not part
of this inspection. Native GUI inspection was slow, so extended GUI tests were
not inferred from the browser results.

[Build record](build_20261106.json).

## Remaining checks

- Human listening with representative VGM, WAV and saved presets.
- Real app Menu / Pin interactions and file dialogs on the user's machine.
- Real WebView-to-CPAL output switching, prolonged playback and background /
  pinned-window behavior. The 30-second Rust test does not complete these.
- macOS Intel, Windows and Linux hosted builds / runtime checks. The workflow
  is configured; no commit, push, remote Actions run, tag or release was made
  by this implementation work.
- Signed / notarized distribution through exported credentials and
  `deploy_mac.sh`, when publishing is requested.
