import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import (
    ExtractorError,
    float_or_none,
    int_or_none,
    traverse_obj,
    unified_timestamp,
)


class SoundCloudDRMIE(InfoExtractor):
    IE_NAME = 'soundcloud:drm'
    _VALID_URL = r'''(?x)
        https?://
            (?:(?:www|m)\.)?soundcloud\.com/
            (?P<uploader>[\w\d-]+)/
            (?P<id>[\w\d-]+)
            (?:/(?P<token>[^?#]+))?
            (?:\?.*?\bsecret_token=(?P<secret_token>[^&]+))?
    '''
    _CLIENT_ID = None

    _ARTWORK_SIZES = [
        ('t500x500', 500),
        ('crop', 400),
        ('t300x300', 300),
        ('large', 100),
        ('t67x67', 67),
        ('badge', 47),
        ('tiny', 20),
    ]

    def _real_extract(self, url):
        uploader, track_slug = self._match_valid_url(url).group('uploader', 'id')
        client_id = self._get_client_id(url)

        track = self._download_json(
            'https://api-v2.soundcloud.com/resolve',
            track_slug,
            query={'url': url, 'client_id': client_id},
            headers=self._sc_headers(),
            note='Downloading info JSON',
        )

        track_id = str(track['id'])
        title = track.get('title', track_slug)
        user = track.get('user') or {}

        duration = float_or_none(track.get('duration'), 1000)
        timestamp = unified_timestamp(track.get('created_at'))

        thumbnails = []
        artwork_url = track.get('artwork_url') or user.get('avatar_url')
        if artwork_url:
            for size_id, size_px in self._ARTWORK_SIZES:
                thumbnails.append({
                    'id': size_id,
                    'url': artwork_url.replace('-large', f'-{size_id}'),
                    'width': size_px,
                    'height': size_px,
                })

        transcodings = traverse_obj(track, ('media', 'transcodings')) or []

        drm_streams = []
        for t in transcodings:
            preset = t.get('preset', '')
            protocol = traverse_obj(t, ('format', 'protocol'), default='')
            if 'ctr-encrypted-hls' in protocol and 'aac' in preset:
                drm_streams.append(t)

        if not drm_streams:
            self.write_debug('No Widevine DRM stream found, falling back to default extractor')
            return self.url_result(url, ie='Soundcloud')

        formats = []
        subtitles = {}
        pssh = None
        primary_stream_url = None
        primary_stream_token_url = None

        for drm_stream in drm_streams:
            preset = drm_stream.get('preset', '?')

            stream_data = self._download_json(
                drm_stream['url'],
                track_id,
                query={'client_id': client_id},
                headers=self._sc_headers(),
                note=f'Downloading {preset} format info JSON',
            )

            stream_url = stream_data.get('url')
            if not stream_url:
                continue

            if primary_stream_url is None:
                primary_stream_url = stream_url
                primary_stream_token_url = drm_stream['url']

            if pssh is None:
                m3u8_text = self._download_webpage(
                    stream_url, track_id,
                    note='Downloading m3u8 manifest',
                    fatal=False,
                )
                if m3u8_text:
                    pssh_match = re.search(
                        r'URI="data:text/plain;base64,([^"]+)"', m3u8_text)
                    if pssh_match:
                        pssh = pssh_match.group(1)

            stream_formats, stream_subs = self._extract_m3u8_formats_and_subtitles(
                stream_url, track_id, 'mp4',
                entry_protocol='m3u8_native',
                m3u8_id=preset,
                headers=self._sc_headers(),
                fatal=False,
            )

            is_hq = drm_stream.get('quality') == 'hq'
            abr = int_or_none(self._search_regex(
                r'(\d+)k$', preset, 'abr', default=None))

            for fmt in stream_formats:
                fmt.pop('has_drm', None)
                fmt.update({
                    'format_id': f'drm_{preset}',
                    'manifest_url': stream_url,
                    'protocol': 'm3u8_native',
                    'http_headers': self._sc_headers(),
                    'vcodec': 'none',
                    'acodec': 'mp4a.40.2',
                    'ext': 'm4a',
                    'abr': abr or 160,
                    'quality': 5 if is_hq else (0 if (abr and abr >= 160) else -1),
                    'format_note': 'Premium' if is_hq else None,
                })
                formats.append(fmt)

            subtitles = self._merge_subtitles(subtitles, stream_subs)

        if not formats and primary_stream_url:
            formats = [{
                'url': primary_stream_url,
                'format_id': 'drm_aac_160k',
                'ext': 'm4a',
                'vcodec': 'none',
                'acodec': 'mp4a.40.2',
                'abr': 160,
                'protocol': 'm3u8_native',
                'manifest_url': primary_stream_url,
                'http_headers': self._sc_headers(),
            }]

        if pssh is None:
            self.report_warning('Could not extract PSSH from manifest')

        for pp in self._downloader._pps.get('before_dl', []):
            if hasattr(pp, 'add_mpd'):
                pp.add_mpd(primary_stream_url, pssh, None)

        _token_url = primary_stream_token_url
        _client_id = client_id

        def license_callback(challenge, lic_url=None):
            fresh = self._download_json(
                _token_url, track_id,
                query={'client_id': _client_id},
                headers=self._sc_headers(),
                note='Refreshing license token',
            )

            fresh_token = None
            for key in fresh:
                if any(kw in key.lower() for kw in ('license', 'drm', 'token')):
                    fresh_token = fresh[key]
                    break

            if not fresh_token:
                raise ExtractorError(
                    'No license token found. Ensure you have access to this track.')

            license_url = (
                'https://license.media-streaming.soundcloud.cloud/playback/widevine'
                f'?license_token={fresh_token}'
            )

            return self._request_webpage(
                license_url, track_id,
                note='Downloading Widevine license',
                data=challenge,
                headers={
                    'Accept': '*/*',
                    'Content-Type': 'application/octet-stream',
                    **self._sc_headers(),
                },
            ).read()

        return {
            'id': track_id,
            'title': title,
            'track': title,
            'uploader': user.get('username'),
            'uploader_id': user.get('permalink'),
            'uploader_url': user.get('permalink_url'),
            'timestamp': timestamp,
            'thumbnails': thumbnails,
            'duration': duration,
            'genre': track.get('genre'),
            'description': track.get('description'),
            'view_count': int_or_none(track.get('playback_count')),
            'like_count': int_or_none(
                track.get('likes_count') or track.get('favoritings_count')),
            'repost_count': int_or_none(track.get('reposts_count')),
            'comment_count': int_or_none(track.get('comment_count')),
            'license': track.get('license'),
            'webpage_url': track.get('permalink_url'),
            'formats': formats,
            'subtitles': subtitles,
            '_license_callback': license_callback,
            '_license_url': primary_stream_url,
        }

    def _get_client_id(self, url):
        if self._CLIENT_ID:
            return self._CLIENT_ID

        client_id = self.cache.load('soundcloud', 'client_id')
        if client_id:
            self._CLIENT_ID = client_id
            return client_id

        webpage = self._download_webpage(
            url, None, note='Downloading main page')

        client_id = self._search_regex(
            r'client_id\s*:\s*"([0-9a-zA-Z]{32})"',
            webpage, 'client id', default=None)

        if not client_id:
            scripts = re.findall(r'src="(https://[^"]+\.js)"', webpage)
            for script_url in reversed(scripts):
                script = self._download_webpage(
                    script_url, None, fatal=False,
                    note='Downloading JS asset')
                if not script:
                    continue

                client_id = self._search_regex(
                    r'client_id\s*:\s*"([0-9a-zA-Z]{32})"',
                    script, 'client id', default=None)

                if client_id:
                    break

        if client_id:
            self.write_debug(f'Found client_id: {client_id[:8]}...')
            self._CLIENT_ID = client_id
            self.cache.store('soundcloud', 'client_id', client_id)
            return client_id

        raise ExtractorError('Could not find client_id', expected=True)

    def _sc_headers(self):
        return {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/131.0.0.0 Safari/537.36'
            ),
            'Origin': 'https://soundcloud.com',
            'Referer': 'https://soundcloud.com/',
        }