import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { beforeEach, test } from "node:test";

import { standaloneCli, StandaloneCliError } from "./standalone-cli.ts";
import type { StandaloneCliOptions } from "./standalone-cli.ts";

const ARCHIVE_URL =
  "https://github.com/jekozyra/spsync/releases/download/v0.2.0/spsync-macos-arm64.tar.gz";

const CHECKSUM_URL = `${ARCHIVE_URL}.sha256`;

let root = "";
let archive: Buffer = Buffer.alloc(0);

/** Pack a synthetic build the way scripts/build_standalone.sh does: one folder with the executable. */
function packArchive(): Buffer {
  const work = mkdtempSync(path.join(os.tmpdir(), "spsync-archive-"));
  const folder = path.join(work, "spsync-macos-arm64");
  mkdirSync(folder);
  writeFileSync(path.join(folder, "spsync"), "#!/bin/sh\necho spsync 0.2.0\n", { mode: 0o755 });
  writeFileSync(path.join(folder, "LICENSE"), "MIT\n");
  execFileSync("/usr/bin/tar", [
    "-C",
    work,
    "-czf",
    path.join(work, "a.tar.gz"),
    "spsync-macos-arm64",
  ]);

  return readFileSync(path.join(work, "a.tar.gz"));
}

function checksumOf(bytes: Buffer): string {
  return `${createHash("sha256").update(bytes).digest("hex")}  spsync-macos-arm64.tar.gz\n`;
}

/** A release server that answers from `files` and records each requested URL. */
function release(
  files: Map<string, Buffer>,
  requests: string[],
): StandaloneCliOptions["fetchBytes"] {
  return async (url) => {
    requests.push(url);
    const body = files.get(url);

    if (!body) {
      throw new Error("Request failed, status 404");
    }

    return new Uint8Array(body).buffer;
  };
}

/** The v0.2.0 release with the archive and its correct checksum. */
function publishedRelease(requests: string[]): StandaloneCliOptions["fetchBytes"] {
  return release(
    new Map([
      [ARCHIVE_URL, archive],
      [CHECKSUM_URL, Buffer.from(checksumOf(archive))],
    ]),
    requests,
  );
}

function options(
  fetchBytes: StandaloneCliOptions["fetchBytes"],
  overrides: Partial<StandaloneCliOptions> = {},
): StandaloneCliOptions {
  return {
    version: "0.2.0",
    platform: "darwin",
    arch: "arm64",
    root,
    fetchBytes,
    onDownloadStart: () => {},
    ...overrides,
  };
}

beforeEach(() => {
  root = path.join(mkdtempSync(path.join(os.tmpdir(), "spsync-root-")), "bin");
  archive = packArchive();
});

test("installs the release once and runs the installed build after that", async () => {
  const requests: string[] = [];
  const fetchBytes = publishedRelease(requests);
  let downloads = 0;
  const install = options(fetchBytes, { onDownloadStart: () => (downloads += 1) });

  const first = await standaloneCli(install);
  const second = await standaloneCli(install);

  assert.equal(first, path.join(root, "0.2.0", "spsync"));
  assert.equal(second, first);
  assert.equal(execFileSync(first, { encoding: "utf8" }), "spsync 0.2.0\n");
  assert.equal(downloads, 1);
  assert.deepEqual(new Set(requests), new Set([ARCHIVE_URL, CHECKSUM_URL]));
  assert.deepEqual(readdirSync(root), ["0.2.0"]);
});

test("two vaults that install at the same time get the same build", async () => {
  const fetchBytes = publishedRelease([]);

  const [a, b] = await Promise.all([
    standaloneCli(options(fetchBytes)),
    standaloneCli(options(fetchBytes)),
  ]);

  assert.equal(a, b);
  assert.deepEqual(readdirSync(root), ["0.2.0"]);
});

test("a checksum mismatch installs nothing", async () => {
  const fetchBytes = release(
    new Map([
      [ARCHIVE_URL, archive],
      [CHECKSUM_URL, Buffer.from(checksumOf(Buffer.from("another build")))],
    ]),
    [],
  );

  await assert.rejects(standaloneCli(options(fetchBytes)), (error: Error) => {
    assert.ok(error instanceof StandaloneCliError);
    assert.match(error.message, /does not match its SHA-256 checksum/);

    return true;
  });
  assert.throws(() => readdirSync(root), { code: "ENOENT" });
});

test("a failed download names the URL and installs nothing", async () => {
  const fetchBytes = release(new Map([[CHECKSUM_URL, Buffer.from(checksumOf(archive))]]), []);

  await assert.rejects(standaloneCli(options(fetchBytes)), {
    name: "StandaloneCliError",
    message: `Could not download the spsync CLI 0.2.0 from ${ARCHIVE_URL}: Request failed, status 404`,
  });
  assert.throws(() => readdirSync(root), { code: "ENOENT" });
});

test("an update removes older versions and keeps newer versions", async () => {
  for (const version of ["0.1.0", "0.1.9", "0.10.0"]) {
    mkdirSync(path.join(root, version), { recursive: true });
  }

  writeFileSync(path.join(root, "notes.txt"), "");
  const fetchBytes = publishedRelease([]);

  await standaloneCli(options(fetchBytes));

  assert.deepEqual(new Set(readdirSync(root)), new Set(["0.10.0", "0.2.0", "notes.txt"]));
});

test("an Intel Mac gets an error without a download", async () => {
  const requests: string[] = [];

  await assert.rejects(standaloneCli(options(release(new Map(), requests), { arch: "x64" })), {
    name: "StandaloneCliError",
    message: /only Macs with Apple silicon/,
  });
  assert.deepEqual(requests, []);
});
