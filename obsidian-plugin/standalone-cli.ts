/**
 * Install and locate the standalone spsync CLI. The plugin runs this build when the `cliPath` setting is empty.
 *
 * The CLI version always equals the plugin version. Every vault shares one install root.
 *
 *   GitHub release v<version>
 *     spsync-macos-arm64.tar.gz  --download, SHA-256 check, /usr/bin/tar-->  <root>/.staging-XXXXXX/
 *     spsync-macos-arm64.tar.gz.sha256                                         `-- spsync-macos-arm64/
 *                                                               --rename-->  <root>/<version>/spsync
 *
 * A version folder exists only after its archive passed the checksum check, because the rename into place is
 * atomic. Two vaults that install the same version at the same time each unpack into their own staging folder,
 * and the first rename wins.
 */
import { execFile } from "child_process";
import { createHash } from "crypto";
import { promises as fs } from "fs";
import * as os from "os";
import * as path from "path";
import { promisify } from "util";

const RELEASES_URL = "https://github.com/jekozyra/spsync/releases/download";
const SUPPORTED_PLATFORM = "darwin";
const SUPPORTED_ARCH = "arm64";
const ARCHIVE_FOLDER = `spsync-macos-${SUPPORTED_ARCH}`;
const ARCHIVE_NAME = `${ARCHIVE_FOLDER}.tar.gz`;
const CHECKSUM_NAME = `${ARCHIVE_NAME}.sha256`;
const EXECUTABLE_NAME = "spsync";
const STAGING_PREFIX = ".staging-";
const TAR_PATH = "/usr/bin/tar";

// `shasum -a 256` prints "<hex>  <file>", or "<hex> *<file>" in binary mode.
const CHECKSUM_LINE = /^([0-9a-f]{64}) [ *](.+)$/i;
const VERSION_PATTERN = /^(\d+)\.(\d+)\.(\d+)$/;

// An install that runs longer than this time has stopped, so its staging folder is safe to remove.
const STALE_STAGING_MS = 60 * 60 * 1000;

const execFileAsync = promisify(execFile);

/** The install root that every vault shares. */
export const SHARED_INSTALL_ROOT = path.join(
  os.homedir(),
  "Library",
  "Application Support",
  "spsync",
  "bin",
);

/** Gets the bytes at a URL, and rejects when the request fails. The plugin passes Obsidian's `requestUrl`. */
export type FetchBytes = (url: string) => Promise<ArrayBuffer>;

export interface StandaloneCliOptions {
  /** The plugin version. The release tag is `v<version>`. */
  version: string;
  /** `process.platform` of the Obsidian app. */
  platform: string;
  /** `process.arch` of the Obsidian app. */
  arch: string;
  /** The folder that holds one folder for each installed version. */
  root: string;
  fetchBytes: FetchBytes;
  /** Called once when a download starts. Not called when the version is already installed. */
  onDownloadStart: () => void;
}

/** A failure that the plugin shows to the user. The message names the cause and the fix when one exists. */
export class StandaloneCliError extends Error {
  name = "StandaloneCliError";
}

function parseVersion(text: string): number[] | null {
  const match = VERSION_PATTERN.exec(text);

  return match ? match.slice(1).map(Number) : null;
}

function isOlderVersion(candidate: number[], current: number[]): boolean {
  const index = candidate.findIndex((part, i) => part !== current[i]);

  return index !== -1 && candidate[index] < current[index];
}

async function exists(file: string): Promise<boolean> {
  try {
    await fs.access(file);

    return true;
  } catch {
    return false;
  }
}

function expectedChecksum(checksumFile: string): string {
  for (const line of checksumFile.split("\n")) {
    const match = CHECKSUM_LINE.exec(line.trim());

    if (match && match[2] === ARCHIVE_NAME) {
      return match[1].toLowerCase();
    }
  }

  throw new StandaloneCliError(`${CHECKSUM_NAME} has no SHA-256 checksum for ${ARCHIVE_NAME}.`);
}

async function download(options: StandaloneCliOptions, file: string): Promise<Buffer> {
  const url = `${RELEASES_URL}/v${options.version}/${file}`;

  try {
    return Buffer.from(await options.fetchBytes(url));
  } catch (cause) {
    const reason = cause instanceof Error ? cause.message : String(cause);

    throw new StandaloneCliError(
      `Could not download the spsync CLI ${options.version} from ${url}: ${reason}`,
    );
  }
}

/** Download, check, and unpack the archive into `versionFolder`. Another vault can install it first. */
async function install(
  options: StandaloneCliOptions,
  versionFolder: string,
  executable: string,
): Promise<void> {
  options.onDownloadStart();

  const [archive, checksumFile] = await Promise.all([
    download(options, ARCHIVE_NAME),
    download(options, CHECKSUM_NAME),
  ]);

  const actual = createHash("sha256").update(archive).digest("hex");

  if (actual !== expectedChecksum(checksumFile.toString("utf8"))) {
    throw new StandaloneCliError(
      `The downloaded spsync CLI ${options.version} does not match its SHA-256 checksum, so the plugin did not run it. Try again later, or set the spsync CLI path in settings.`,
    );
  }

  await fs.mkdir(options.root, { recursive: true });
  const staging = await fs.mkdtemp(path.join(options.root, STAGING_PREFIX));

  try {
    const archivePath = path.join(staging, ARCHIVE_NAME);
    await fs.writeFile(archivePath, archive);
    await execFileAsync(TAR_PATH, ["-xzf", archivePath, "-C", staging]);
    await fs.rename(path.join(staging, ARCHIVE_FOLDER), versionFolder);
  } catch (cause) {
    // A rename fails when another vault installed the same version first. That install is complete.
    if (!(await exists(executable))) {
      const reason = cause instanceof Error ? cause.message : String(cause);

      throw new StandaloneCliError(`Could not unpack the spsync CLI ${options.version}: ${reason}`);
    }
  } finally {
    await fs.rm(staging, { recursive: true, force: true });
  }

  if (!(await exists(executable))) {
    throw new StandaloneCliError(
      `The spsync CLI ${options.version} archive has no ${ARCHIVE_FOLDER}/${EXECUTABLE_NAME}.`,
    );
  }
}

/**
 * Remove the versions older than `current`, and staging folders of stopped installs. Newer versions stay,
 * because a vault with a newer plugin version can still use them.
 */
async function removeOldInstalls(root: string, current: number[]): Promise<void> {
  const removals: Promise<void>[] = [];
  const now = Date.now();

  for (const entry of await fs.readdir(root, { withFileTypes: true })) {
    const folder = path.join(root, entry.name);
    const version = parseVersion(entry.name);

    if (!entry.isDirectory()) {
      continue;
    }

    if (version && isOlderVersion(version, current)) {
      removals.push(fs.rm(folder, { recursive: true, force: true }));
    } else if (entry.name.startsWith(STAGING_PREFIX)) {
      // oxlint-disable-next-line no-await-in-loop
      const { mtimeMs } = await fs.stat(folder);

      if (now - mtimeMs > STALE_STAGING_MS) {
        removals.push(fs.rm(folder, { recursive: true, force: true }));
      }
    }
  }

  await Promise.all(removals);
}

/**
 * Return the path of the standalone CLI for the plugin version. Install that version first when it is missing,
 * then remove older versions.
 *
 * Rejects with `StandaloneCliError` when the Mac is not supported, the download fails, or the archive does not
 * match its checksum. The plugin never runs an archive that failed the check.
 */
export async function standaloneCli(options: StandaloneCliOptions): Promise<string> {
  if (options.platform !== SUPPORTED_PLATFORM || options.arch !== SUPPORTED_ARCH) {
    throw new StandaloneCliError(
      "The spsync CLI download supports only Macs with Apple silicon. Set the spsync CLI path in settings to run your own build.",
    );
  }

  const current = parseVersion(options.version);

  if (!current) {
    throw new StandaloneCliError(
      `The plugin version ${options.version} is not a release version. Set the spsync CLI path in settings.`,
    );
  }

  const versionFolder = path.join(options.root, options.version);
  const executable = path.join(versionFolder, EXECUTABLE_NAME);

  if (await exists(executable)) {
    return executable;
  }

  await install(options, versionFolder, executable);
  await removeOldInstalls(options.root, current);

  return executable;
}
