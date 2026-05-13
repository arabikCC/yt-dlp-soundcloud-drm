# SoundCloud DRM Downloader (yt-dlp plugin)

A custom [yt-dlp](https://github.com/yt-dlp/yt-dlp) plugin for downloading and decrypting Widevine-protected tracks from SoundCloud.

## Features
*   **Automatic DRM Bypass:** Automatically identifies encrypted streams, extracts PSSH from manifests, and handles license challenges.
*   **Multi-Quality:** Supports both standard (96k) and high quality (160k) AAC streams.
*   **Smart Fallback:** Seamlessly delegates unprotected tracks to the official SoundCloud extractor.
*   **Caching:** Implements `client_id` caching (shared with the official extractor) for near-instant startup.

## Prerequisites
*   **yt-dlp:** Latest version recommended.
*   **Bento4:** `mp4decrypt` executable must be present in your system's PATH.
*   **CDM:** A valid Widevine Device file (`.wvd`). Private CDMs are highly recommended as public ones are often blacklisted.

## Installation

```bash
pip install git+https://github.com/arabikCC/yt-dlp-soundcloud-drm
```

Or clone and install locally:

```bash
git clone https://github.com/arabikCC/yt-dlp-soundcloud-drm
cd soundcloud-drm-plugin
pip install .
```

## Usage

```bash
yt-dlp --use-postprocessor "Mp4Decrypt:when=before_dl;devicepath=/path/to/device.wvd" --allow-unplayable-formats "TRACK_URL"
```

### Options
| Option | Description |
|---|---|
| `devicepath` | Absolute path to your `.wvd` file |
| `when=before_dl` | Ensures keys are fetched before download starts |
| `--impersonate chrome` | Optional. May help if you encounter WAF blocks |

*Created for personal use.*

