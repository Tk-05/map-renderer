#!/usr/bin/env node
// Bedrock Realms helper for map-renderer (tools/map_renderer/realms.py).
//
//   node realms.js login    --auth DIR
//   node realms.js list     --auth DIR
//   node realms.js download --auth DIR --realm ID --slot N --out FILE
//
// Common options: --client-version X.Y.Z (sent as Client-Version), --preview (Preview Realms).
//
// The result is printed as one JSON document on stdout. Everything for the
// user (the Microsoft sign-in code, progress, errors) goes to stderr, so the
// sign-in prompt shows up in the terminal or in `docker compose logs`.

'use strict'

const fs = require('fs')
const path = require('path')
const { pipeline } = require('stream/promises')
const { Readable, Transform } = require('stream')
const { Authflow } = require('prismarine-auth')
const { RealmAPI } = require('prismarine-realms')

const REALMS_RELYING_PARTY = 'https://pocket.realms.minecraft.net/'

// prismarine-auth logs with console.info; keep stdout clean for the JSON result.
for (const name of ['log', 'info', 'warn', 'debug']) console[name] = console.error.bind(console)

class UsageError extends Error {}

function parseArgs (argv) {
  const [command, ...rest] = argv
  const opts = { command }
  for (let i = 0; i < rest.length; i++) {
    const arg = rest[i]
    if (!arg.startsWith('--')) throw new UsageError(`Unexpected argument: ${arg}`)
    const key = arg.slice(2)
    if (key === 'preview') {
      opts.preview = true
    } else {
      if (i + 1 >= rest.length) throw new UsageError(`Missing value for ${arg}`)
      opts[key] = rest[++i]
    }
  }
  if (!opts.auth) throw new UsageError('--auth DIR is required')
  return opts
}

function makeAuth (opts) {
  // Default flow of prismarine-auth: Microsoft device code sign-in ("live" flow).
  // Tokens are cached in opts.auth and refreshed automatically afterwards.
  return new Authflow('map-renderer', opts.auth, undefined, (response) => {
    console.error('')
    console.error('Microsoft sign-in required (only once, the login is remembered):')
    console.error(`  ${response.message}`)
    console.error('Waiting for the sign-in to complete ...')
  })
}

function makeApi (auth, opts) {
  const options = { usePreview: Boolean(opts.preview) }
  if (opts['client-version']) options.minecraftVersion = opts['client-version']
  return RealmAPI.from(auth, 'bedrock', options)
}

async function login (opts) {
  const auth = makeAuth(opts)
  const token = await auth.getXboxToken(REALMS_RELYING_PARTY)
  return { signedIn: true, xuid: token.userXUID }
}

async function list (opts) {
  const auth = makeAuth(opts)
  const { userXUID } = await auth.getXboxToken(REALMS_RELYING_PARTY)
  const realms = await makeApi(auth, opts).getRealms()
  return realms.map(r => ({
    id: String(r.id),
    name: r.name,
    owner: r.owner,
    isOwner: Boolean(userXUID) && String(r.ownerUUID) === String(userXUID),
    state: r.state,
    activeSlot: r.activeSlot,
    expired: Boolean(r.expired),
    worldType: r.worldType
  }))
}

function progress (total) {
  let done = 0
  let lastShown = 0
  const tty = process.stderr.isTTY
  return new Transform({
    transform (chunk, _enc, callback) {
      done += chunk.length
      const now = Date.now()
      if (now - lastShown > (tty ? 200 : 10000)) {
        lastShown = now
        const mb = (done / 1e6).toFixed(1)
        const text = total ? `${Math.floor(done * 100 / total)}%  ${mb} / ${(total / 1e6).toFixed(1)} MB` : `${mb} MB`
        process.stderr.write(tty ? `\r  ${text.padEnd(40)}` : `  ${text}\n`)
      }
      callback(null, chunk)
    },
    flush (callback) {
      if (tty) process.stderr.write('\r' + ' '.repeat(44) + '\r')
      callback()
    }
  })
}

async function download (opts) {
  if (!opts.realm) throw new UsageError('--realm ID is required')
  if (!opts.out) throw new UsageError('--out FILE is required')
  const slot = opts.slot || '1'

  const api = makeApi(makeAuth(opts), opts)
  // 'latest' = the world as it is now (not the newest backup).
  const dl = await api.getRealmWorldDownload(opts.realm, slot, 'latest')
  if (!dl.downloadUrl) throw new Error('The Realms API returned no download link.')

  // Streamed to disk; Download.getBuffer() would hold the whole world in memory.
  const res = await fetch(dl.downloadUrl, {
    headers: dl.token ? { Authorization: `Bearer ${dl.token}` } : {}
  })
  if (!res.ok || !res.body) throw new Error(`Download failed: ${res.status} ${res.statusText}`)
  const total = Number(res.headers.get('content-length')) || Number(dl.size) || 0

  fs.mkdirSync(path.dirname(opts.out), { recursive: true })
  const part = `${opts.out}.part`
  try {
    await pipeline(Readable.fromWeb(res.body), progress(total), fs.createWriteStream(part))
    fs.renameSync(part, opts.out)
  } catch (e) {
    fs.rmSync(part, { force: true })
    throw e
  }
  return { file: path.resolve(opts.out), size: fs.statSync(opts.out).size }
}

// Turn Realms API errors ("403 Forbidden {...}") into something actionable.
function explain (error) {
  const text = String(error && error.message ? error.message : error)
  const status = Number((text.match(/^(\d{3}) /) || [])[1])
  if (status === 401) return `${text}\nThe sign-in was rejected. Run "map-renderer realm logout", then sign in again.`
  if (status === 403) return `${text}\nAccess denied. Only the Realm owner can download the world.`
  if (status === 404) return `${text}\nRealm or world slot not found (see "map-renderer realm list").`
  if (/outdated|client.?version|upgrade/i.test(text)) {
    return `${text}\nThe Realms API wants a newer client version. Pass the current Bedrock version, ` +
      'e.g. --client-version 1.26.30 (or set REALMS_CLIENT_VERSION).'
  }
  return text
}

async function main () {
  let opts
  try {
    opts = parseArgs(process.argv.slice(2))
  } catch (e) {
    console.error(`error: ${e.message}`)
    return 2
  }
  const commands = { login, list, download }
  const run = commands[opts.command]
  if (!run) {
    console.error(`error: unknown command "${opts.command}" (expected: ${Object.keys(commands).join(', ')})`)
    return 2
  }
  try {
    const result = await run(opts)
    process.stdout.write(JSON.stringify(result) + '\n')
    return 0
  } catch (e) {
    console.error(`error: ${explain(e)}`)
    return e instanceof UsageError ? 2 : 1
  }
}

main().then(code => { process.exitCode = code })
