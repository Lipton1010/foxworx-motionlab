# Windows beta media-runtime release gate

Decision recorded 2026-11-09: commercial use intended where selected models
permit; initial unsigned Windows prerelease with checksums. This is not
commercial legal clearance or authorization to choose a project license.

Observed live media runtime: Gyan FFmpeg 8.1.1 essentials, GPLv3 static build.
ffmpeg SHA256 228d7a8556258de907fdb55f36850078ebc7680b84ec30d84ea02e99bec1d1eb
ffprobe SHA256 0fde260f5abd35c9cafd96f594cc76365a780c1b73a90e35b6a3409ea1db1bf0
Upstream FFmpeg source revision: 239f2c733d.
Build enables GPL, version3, static libraries, libx264/libx265/libxvid and many
other external libraries. The app invokes command-line media tools rather
than directly linking libav libraries. That distinction is relevant, but is
not a blanket conclusion about app licensing or codec patents.

Current Package Production.ps1 copies local binaries (or Chocolatey fallback),
then independently copies Chocolatey LICENSE/README. This can mismatch notices
and actual binaries if local media files differ. The manifest records hashes
but hardcodes version/provenance. Release packaging must bind binary hashes,
version/configuration and notices to one reviewed runtime manifest.

Unresolved: local README lists external library names but not exact versions,
patches, build recipes and matching full sources. A link to the FFmpeg commit
alone does not establish complete corresponding source for this static build.
Do not label this audit complete or release binaries on that evidence alone.

Preferred completion: obtain/verify the exact upstream full source/build
bundle, or build a minimal reproducible FFmpeg+ffprobe from pinned sources
with exact dependency notices and matching source distribution. Preserve
required export codecs/filters and test actual app exports before replacement.
Changing to LGPL-only is not a drop-in answer if libx264 workflows remain.
Do not silently remove media functionality or contact upstream on Paul's
behalf without communication authorization.

Release checklist: reviewed binary/source manifest; all notices; corresponding
source accessible with binary release; no incompatible EULA restrictions;
codec/patent review appropriate to intended distribution; fresh install and
upgrade tests; SHA256SUMS; explicit unsigned Windows beta warning; README
links only after actual published release URLs exist.

Primary sources:
https://ffmpeg.org/legal.html
https://www.gyan.dev/ffmpeg/builds/

No binary replacement, publication, project-license change or upstream
outreach was performed by this investigation.

Follow-up 2026-11-09: the official Gyan builds page currently lists 8.1.2,
including essentials ZIP/7z and full/shared archives. The page describes its
builds as GPLv3 and links FFmpeg source revisions, but the inspected links do
not provide a verified, complete corresponding-source bundle for the exact
installed 8.1.1 static binary and all linked libraries. Upgrading the binary
alone does not resolve this distribution gate. No replacement was performed.

Alternative-source check: the official FFmpeg-Builds/FFmpeg-Builds latest
release, published 2026-11-09T13:03:27Z, lists Windows GPL/LGPL static/shared
variants for master, 9.0 and 8.1. This demonstrates available alternatives,
not compatibility or corresponding-source compliance for a selected artifact.
The moving latest URLs are not acceptable reproducibility pins by themselves.
https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/tag/latest

No GCC, bash or Docker command was found on the checked PATH; usual MSYS2 and
Docker installation directories checked were absent. wsl --list reports WSL
not installed. A controlled cross-build therefore needs a reviewed build
environment/toolchain setup; no system software was installed for this audit.

Implementation update: optional upstream installation (2026-11-09)
The core packaging script now refuses a staging tree containing runtime/media
and no longer copies FFmpeg from local or Chocolatey installations. Setup has
an explicit Media tools consent step linking the publisher, dated release,
GPL terms and download size. InstallMedia.ps1 verifies the archive and each
selected executable/license against portable/media-runtime.json, reuses the
resumable downloader and preserves differing pre-existing files.

The pinned upstream archive is ffmpeg-n8.1.3-34-ga35157abb9-win64-gpl-8.1.zip
from FFmpeg-Builds release autobuild-2026-11-09-12-42. A fresh isolated
installation from the verified cache passed synthetic H.264/AAC export and
full decode through the application's media validator. MediaChecks: 12 pass;
PortableChecks: 98 pass. No FFmpeg executable belongs in the application release.

This avoids redistributing that binary in our installer; it is not a blanket
legal clearance for codecs, application licensing, model terms or upstream
compliance. Preserve the upstream license and provenance alongside the tools.
A signed-off application license and final clean-install/upgrade gates remain.
