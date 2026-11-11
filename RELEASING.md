# Releasing spsync

A release publishes the CLI and the Obsidian plugin under one version. A pushed `vX.Y.Z` tag starts [`.github/workflows/release.yml`](.github/workflows/release.yml). The workflow checks the tag and the changelog, builds the plugin and the standalone CLI on an Apple silicon runner, and creates a GitHub release with these files:

| File | Use |
|---|---|
| `spsync-macos-arm64.tar.gz` | The standalone CLI from `scripts/build_standalone.sh`, with `LICENSE`, `THIRD_PARTY_NOTICES.md`, and `licenses/` |
| `spsync-macos-arm64.tar.gz.sha256` | The SHA-256 checksum of the archive, in `shasum -a 256` format. The plugin checks it before it runs the CLI |
| `main.js` | The plugin code. BRAT reads this file |
| `manifest.json` | The plugin manifest. BRAT reads this file |

The plugin downloads the CLI from the release with the plugin's own version. Every fix reaches teammates only through a release.

## Before the release

1. Choose the version. Follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html): increase the patch number for fixes only, and the minor number for new behavior.
2. Create a branch for the release, such as `jillian/<NN>-release-X.Y.Z`.
3. Set the version in the three manifests: `pyproject.toml`, `obsidian-plugin/manifest.json`, and `obsidian-plugin/package.json`. The pre-commit hook fails when the three versions differ.
4. Run `uv lock`. `uv.lock` records the spsync version, and the build fails when the lockfile is out of date.
5. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` with the release date. Add an empty `## [Unreleased]` section above it. The workflow stops when the changelog has no section for the version.
6. Commit, open a PR, and merge it into `main`.

## Tag the release

1. Update `main`:

   ```sh
   git switch main
   git pull --ff-only origin main
   ```

2. Create an annotated tag on the merge commit, and push it:

   ```sh
   git tag -a vX.Y.Z -m "spsync X.Y.Z"
   git push origin vX.Y.Z
   ```

3. Follow the workflow run until it finishes:

   ```sh
   gh run list --workflow release.yml --limit 1
   gh run watch <run-id>
   ```

## Verify the release

1. Check that the release has the four files:

   ```sh
   gh release view vX.Y.Z --json assets --jq '.assets[].name'
   ```

2. Download the archive and the checksum, check the checksum, and run the CLI:

   ```sh
   gh release download vX.Y.Z --dir /tmp/spsync-vX.Y.Z --pattern 'spsync-macos-arm64.tar.gz*'
   cd /tmp/spsync-vX.Y.Z
   shasum -a 256 -c spsync-macos-arm64.tar.gz.sha256
   tar -xzf spsync-macos-arm64.tar.gz
   spsync-macos-arm64/spsync --version
   ```

   The last command prints `spsync X.Y.Z`.

3. In Obsidian, run the BRAT command that checks for updates. Confirm that Settings > Community plugins shows the new version of SharePoint Sync.

## When the workflow fails

When the workflow fails before the publish step, no release exists. Delete the tag, fix the cause through a PR, and tag the new merge commit:

```sh
git push origin --delete vX.Y.Z
git tag -d vX.Y.Z
```

Do not change a release that teammates can have installed. Publish a fix as a new patch version.

## Test release

A test release checks the workflow without a real version. Use a version that no real release uses, such as `0.0.1`.

1. Create a branch from `main`, set the three manifests to `0.0.1`, run `uv lock`, and add a `## [0.0.1] - YYYY-MM-DD` changelog section.
2. Commit on the branch, then tag that commit and push the tag. Do not open a PR:

   ```sh
   git tag -a v0.0.1 -m "spsync 0.0.1 test release"
   git push origin v0.0.1
   ```

3. Verify the release as described above.
4. Delete the release, the tag, and the branch:

   ```sh
   gh release delete v0.0.1 --cleanup-tag --yes
   git tag -d v0.0.1
   git branch -D <test-branch>
   ```

## Code signing

Nuitka gives the standalone CLI an ad hoc signature, not an Apple Developer ID signature. macOS runs the CLI without a Gatekeeper prompt when the plugin downloads the archive. Without a stable signature, macOS asks again for Keychain access to the cached Graph token after each update. The prompt affects only the graph backend.
