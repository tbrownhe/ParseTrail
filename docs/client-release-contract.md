# Client installer target contract

Client **1.4.0** introduces version-2 signed installer manifests. This is the
prepared source contract; it does not establish that 1.4.0 has been built, tagged,
published, or deployed. The remaining native/release gates are in [TODO](../TODO.md).

## Supported targets

| Target / channel | Signed architecture | Filename for version 1.4.0 | Website label |
| --- | --- | --- | --- |
| `windows-x86_64` | `x86_64` | `parsetrail_1.4.0_windows-x86_64_setup.exe` | Windows (x64) |
| `macos-x86_64` | `x86_64` | `parsetrail_1.4.0_macos-x86_64_setup.dmg` | Intel Mac (x86_64) |

The signed artifact's `platform` is the full target above, and `architecture` is
required explicitly. The exact filename must agree with the version and target.
Only these two targets are accepted. The client requires a 64-bit x86 process on
Windows or an x86_64 process on macOS before requesting an installer; a 64-bit
pointer alone is insufficient. Linux source execution remains experimental and
has no supported installer. Apple Silicon development/publication is deferred.
This process check does not claim native ARM or translation-mode acceptance.

Windows and Intel Mac artifacts at the same version have independent identities,
filenames, and release directories. A manifest may represent both, with unique
target/version pairs and sorted filenames. Each public channel must contain only
its own target. Native builders currently produce one installer per channel;
`latest` and the public website reject an ambiguous multi-version active channel.

The manifest's `schema_version` is **2**. Other fields remain `release_sequence`,
`published_at`, `key_id`, and `artifacts`; artifact entries retain `artifact_type`,
`filename`, `version`, `size`, and `sha256`. Unknown fields, missing architecture,
legacy targets/schemas, unsupported architectures, and filename disagreement are
rejected. The signature authenticates the original JSON bytes, including target
and architecture. A filename or target change requires a new release/signature.

## API and publication layout

For each supported target, the API reads
`data/clients/<target>/current-release.json`, then immutable
`data/clients/<target>/releases/<sequence>/` files. The pointer retains schema
version **1**; it is not the installer manifest. Inventories also retain their
version-1 outer schema and add the client `architecture` and
`manifest_schema_version`. Inventory generation validates target/version against
the client manifest. Embedded build metadata uses version **2**, the explicit
target, and `architecture`.

The existing `/api/v1/clients/` listing exposes `platform`, `architecture`,
`manifest_schema_version`, `version`, `file_name`, `file_path`, `size`, and `sha256`.
`file_path` is the target channel name. Exact bytes remain available at:

```text
/api/v1/clients/<target>/manifest
/api/v1/clients/<target>/manifest-signature
/api/v1/clients/<target>/<version-or-latest>
```

The website offers only supported, available version-2 targets, with explicit
processor labels and version-specific URLs. It does not infer CPU compatibility
from `navigator.platform`. API listing metadata is presentation data; desktop
clients still verify the signed manifest and installer bytes independently.

## Transition from 1.3

The transition deliberately requires **one manual installer upgrade**. Existing
1.3 clients reject version-2 manifests and do not know the new target channels.
After deploying the new API, legacy `win64` and `macos` routes return **HTTP 410**
with a link to `https://parsetrail.com/download.html`. There is no redirect of an
old client's request to a differently signed/typed artifact. Existing local
finance data and cached plugins remain usable; the old updater cannot deliver
this upgrade. A 1.4 client also cannot update against a server that only has the
old channels.

Release order:

1. Finish the approved release-tool implementation and source/offline checks;
   create the clean `client-v1.4.0` candidate tag when ready for native builds.
   Complete the native build, offline, and publication rehearsals. Retain
   verified Windows x64 and Intel Mac installers, signatures, and inventories.
2. Rehearse the complete API/website/installer transition on staging with those
   exact bytes. Include a 1.3 client's retired-channel response and a manual
   installation that preserves its local profile.
3. Preserve the old API/website release and both legacy immutable artifact trees
   and pointers. Prepare and verify both new target channels before switching
   the public API and download page together. Public activation remains an
   explicit operator action; merging this code must not deploy it.
4. Confirm both labeled website downloads, exact public manifest/signature bytes,
   installer range responses, and 1.4 update selection. Announce the manual
   upgrade to existing users. Do not claim that old clients can auto-upgrade.

No existing signed file is renamed or edited, and no legacy directory is reused
for the new contract. This API change needs no financial database migration or
server infrastructure redesign. Plugin manifests and plugin routes keep their
existing contract. Cross-contract rollback requires the preserved API/website
and old channel pointers; see [artifact rollback](artifact-rollback.md).
