# Minecraft Map Renderer

A web map for Minecraft worlds (Bedrock and Java). Browse the Overworld, Nether and
End in the browser, with a list of all structures found (portals, villages,
strongholds, ancient cities, …), world statistics, and a distance measuring tool.

Rendering is done by [uNmINeD](https://unmined.net). The world can come from a local
save or be downloaded automatically from a **Bedrock Realm**. A small nginx container
serves the finished map.

> The `map/` folder is intentionally empty in the repository. The map is generated
> (locally or on the server) and never committed.

---

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Tutorial 1: Render a local world and view it](#tutorial-1-render-a-local-world-and-view-it)
- [Tutorial 2: Download a Realm world](#tutorial-2-download-a-realm-world)
- [Tutorial 3: Run the map on a server](#tutorial-3-run-the-map-on-a-server)
  - [Quick start: all-in-one](#quick-start-all-in-one)
  - [Portainer](#portainer)
  - [Step 1: Get the Docker images](#step-1-get-the-docker-images)
  - [Option A: Serve a finished map from a folder](#option-a-serve-a-finished-map-from-a-folder)
  - [Option B: Download and render a Realm automatically](#option-b-download-and-render-a-realm-automatically)
- [Using the web map](#using-the-web-map)
- [Command reference](#command-reference)
- [Environment variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Licenses and privacy](#licenses-and-privacy)

---

## How it works

```
 local world ───────────────┐
                            ├─► map-renderer ──► map/ ──► web container (nginx) ──► browser
 Bedrock Realm ──(download)─┘   (uNmINeD)        overworld/ nether/ end/
                                                stats.json structures.json
```

- **`map-renderer`** (Python, in `tools/`) renders the world into tiles with uNmINeD,
  scans it for structures, and writes everything into a map folder.
- **Realm download:** a small Node.js helper (`tools/realm_download/`) signs in with
  your Microsoft account and downloads the current Realm world as a `.mcworld`.
- **Web container:** serves `index.html`. The map is mounted from outside, as a
  Docker volume or as a folder on the server. It is never part of the image.

---

## Requirements

| For                 | You need                                                                                                                |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Rendering locally   | **Python 3.10+** (Windows: [python.org](https://www.python.org/downloads/), tick "Add python.exe to PATH" during setup) |
| Realm downloads     | also **Node.js 18+** ([nodejs.org](https://nodejs.org/)). The account must **own** the Realm.                           |
| Running on a server | **Docker** with Docker Compose. Python and Node are not needed there; they are inside the container.                    |

You don't have to install uNmINeD yourself. The tool downloads it from unmined.net
into `.cache/` on first use.

---

## Tutorial 1: Render a local world and view it

**1. Get the project**

```bash
git clone https://github.com/tk-05/map-renderer.git
cd map-renderer
```

**2. Start the assistant**

- **Windows:** double-click `map-renderer.bat`
- **Linux/macOS:** `./map-renderer.sh`

The assistant finds your Minecraft worlds automatically and asks step by step:

```
? Which world?
  ›  1) SMP                       Bedrock         saved 10.11.2026 22:24
     2) Creative     Bedrock         saved 11.11.2026 17:51
      p) Enter a folder path …
      r) Download from a Realm …  needs Node.js

? What should be done?
  ›  1) Render map and scan for structures
...
? Which dimensions?
? Re-render everything? (otherwise only changed regions)
```

At the end it shows a summary and the matching command, so you can repeat the same
run later without questions, e.g.:

```bash
map-renderer build --world "C:\...\minecraftWorlds\FVE7uGW04AU=" -y
```

> **Tip:** Close Minecraft before rendering. While the game is running, the world may
> not be fully saved. The tool warns you if it is.

**3. View the map**

```bash
python -m http.server 8765
```

Then open <http://localhost:8765> in your browser.

> Opening `index.html` directly (`file://`) only works partly. Use the small web
> server.

**How long does it take?** The first run renders everything. After that, only changed
areas are redrawn by default. `--force` re-renders everything.

---

## Tutorial 2: Download a Realm world

This works with **Bedrock Realms you own**. Node.js must be installed. The tool
installs the npm packages it needs on first use.

**1. Sign in (once)**

```bash
map-renderer realm login
```

A code is shown:

```
Microsoft sign-in required (only once, the login is remembered):
  To sign in, use a web browser to open the page https://www.microsoft.com/link and use the code ABCD1234
```

Open the link, enter the code, and sign in with the Microsoft account that owns the
Realm. The sign-in is stored in `.cache/realms/auth/` and refreshed automatically.

**2. List your Realms**

```bash
map-renderer realm list
```

```
My Realm      id 12345678, owner YourName
Friends SMP   id 87654321, owner Someone, you are not the owner
```

**3. Download and render**

```bash
map-renderer build --realm "My Realm" -y
```

The id works as well as the name. Use `--slot 1|2|3` for a different world slot
(default: the active slot). In the assistant, choose
**r) Download from a Realm …**.

To download only, without rendering:

```bash
map-renderer realm download --realm "My Realm"
```

The unpacked world is then in `.cache/realms/<id>/slot<N>/world/`.

---

## Tutorial 3: Run the map on a server

There are two containers:

| Container  | Job                                                                  |
| ---------- | -------------------------------------------------------------------- |
| `web`      | nginx, serves the page. The map is mounted from outside.             |
| `renderer` | optional: regularly downloads the Realm world and re-renders the map |

The map always comes **from a path outside the image**:

| `MAP_DIR` in `.env`  | The map lives in …                               |
| -------------------- | ------------------------------------------------ |
| not set              | the Docker volume `map` (filled by the renderer) |
| `/srv/minecraft-map` | this folder on the server                        |

There are two compose files. Use one of them, not both at once:

| File | Renderer | Use it for |
| --- | --- | --- |
| `docker-compose.yml` (repo root) | always on | **web map + Realm renderer in one stack** (also in Portainer) |
| `server/docker-compose.yml` | optional | serving a map rendered elsewhere; renderer only on demand |

Both use the prebuilt images `ghcr.io/tk-05/map-renderer` and
`ghcr.io/tk-05/map-renderer-renderer` (see [Step 1](#step-1-get-the-docker-images)).
Nothing is built on the server.

### Quick start: all-in-one

Runs the web map and the Realm renderer together.

**1. Get the compose file and create `.env`**

```bash
git clone https://github.com/tk-05/map-renderer.git
cd map-renderer
cp .env.example .env
```

Edit `.env` and set at least `REALM` (the name of your Realm). All settings are
explained in [`.env.example`](.env.example).

**2. Pull the images, sign in once, check the Realm name**

```bash
docker compose pull
docker compose run --rm renderer map-renderer realm login
docker compose run --rm renderer map-renderer realm list
```

Open the link, enter the code, and sign in with the Realm owner's account.

**3. Start**

```bash
docker compose up -d
docker compose logs -f renderer
```

The map is on <http://localhost:8080> (or the `PORT` from `.env`) and is updated every
`INTERVAL`. To update the images later: `docker compose pull && docker compose up -d`.

**Build from source instead** (needs the Docker CLI with BuildKit on that machine,
not Portainer):

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

> With the Docker CLI, `MAP_DIR=./map` in `.env` keeps the map in the repository's
> `map/` folder, so the local `map-renderer` tool and the containers share it.

### Portainer

Portainer can't build images in a stack (the build fails with
`error reading server preface: http2: frame too large`), so it uses the prebuilt
images.

1. **Images available?** The GitHub Action must have run at least once (push to
   `main`, or *Actions → Build image → Run workflow*). Make both packages public under
   *GitHub → Packages → Package settings → Change visibility*, or add `ghcr.io` under
   *Portainer → Registries* (username + personal access token with `read:packages`).
2. **Create the stack:** *Stacks → Add stack*
   - **Repository:** URL `https://github.com/tk-05/map-renderer`, compose path
     `docker-compose.yml`, or
   - **Web editor:** paste the content of [`docker-compose.yml`](docker-compose.yml).
3. **Environment variables** (below the editor): at least `REALM`. Optionally
   `INTERVAL`, `PORT`, and `MAP_DIR` as an **absolute** host path (relative paths
   point into Portainer's data folder).
4. **Deploy the stack.**
5. **Sign in once:** *Containers → map-renderer-renderer → Logs*. On the first run
   the log shows the Microsoft sign-in link and code. Open the link and enter the
   code; the render then starts on its own. Alternatively open *Console* on the
   container (`/bin/sh`) and run `map-renderer realm login`.

### Step 1: Get the Docker images

**Option 1: from GitHub (recommended).** On every push to `main`, the GitHub Action
`.github/workflows/build-image.yml` builds two images and publishes them to the
GitHub Container Registry:

- `ghcr.io/tk-05/map-renderer`
- `ghcr.io/tk-05/map-renderer-renderer`

New packages on GitHub are **private** at first. Either make them public under
_Packages → Package settings → Change visibility_, or sign in on the server with
`docker login ghcr.io` (username plus a personal access token with `read:packages`).

**Option 2: build on the server** (Docker CLI only, not in Portainer). For the
all-in-one file use `docker-compose.build.yml` as shown in the
[quick start](#quick-start-all-in-one). To build the images by hand, e.g. for
`server/docker-compose.yml`:

```bash
git clone https://github.com/tk-05/map-renderer.git
cd map-renderer
docker build -t map-renderer .
docker build -t map-renderer-renderer tools
```

Then put these names in `.env` (see below):

```env
MAP_RENDERER_IMAGE=map-renderer
MAP_RENDERER_RENDERER_IMAGE=map-renderer-renderer
```

### Option A: Serve a finished map from a folder

You render the map on your PC (Tutorial 1 or 2) and copy it to the server. The server
itself doesn't render anything.

**1. Create the folder on the server**

```bash
sudo mkdir -p /srv/minecraft-map
```

**2. Create `.env`** in `server/` (next to `docker-compose.yml`):

```env
MAP_DIR=/srv/minecraft-map
```

**3. Start**

```bash
cd server
docker compose up -d
```

The page is now running on port **8080**. While the folder is empty it shows
"This map has not been rendered yet".

**4. Upload the map.** Either render locally as usual and copy the _contents_ of
`map/`:

```bash
rsync -av --delete map/ user@server:/srv/minecraft-map/
```

… or render straight into a folder that ends up on the server (network share, sync
folder):

```bash
map-renderer build --world "SMP" --output "\\server\minecraft-map" -y
```

No restart is needed. The new map is online right away.

> nginx in the container must be able to read the files. If tiles are missing:
> `chmod -R a+rX /srv/minecraft-map`

### Option B: Download and render a Realm automatically

The server downloads the Realm world at a fixed interval and re-renders the map.
Nobody has to be in the game for this.

**1. Create `.env`** in `server/`:

```env
COMPOSE_PROFILES=realm
REALM=My Realm
INTERVAL=6h

# optional: keep the map in a host folder instead of the Docker volume
# MAP_DIR=/srv/minecraft-map
```

**2. Sign in once**

```bash
cd server
docker compose run --rm renderer map-renderer realm login
```

Open the link, enter the code, and sign in with the Realm owner's account. The
sign-in is stored in the `cache` volume and survives restarts and updates.

**3. Check the Realm name**

```bash
docker compose run --rm renderer map-renderer realm list
```

**4. Start**

```bash
docker compose up -d
docker compose logs -f renderer
```

The log shows the first run: download, uNmINeD installation, rendering and the
structure scan. After that it repeats every `INTERVAL`. If a run fails, the previous
map stays online and the run is retried after the interval.

**Useful commands**

```bash
# Re-render everything right now
docker compose run --rm renderer map-renderer build --realm "My Realm" --force -y

# Overworld only, including spawners etc.
#   in .env:  BUILD_ARGS=--dims overworld --extras

# Sign out / switch account
docker compose run --rm renderer map-renderer realm logout

# Update the images
docker compose pull && docker compose up -d
```

### Reverse proxy / HTTPS

The web container listens on port 8080. For your own domain with HTTPS, put a reverse
proxy in front of it (e.g. Caddy, Traefik or nginx). Example for Caddy:

```
map.example.com {
    reverse_proxy localhost:8080
}
```

---

## Using the web map

| Key             | Action                                                                                    |
| --------------- | ----------------------------------------------------------------------------------------- |
| `1` / `2` / `3` | Overworld / Nether / End                                                                  |
| `S`             | Toggle the structure list (portals, villages, strongholds, ancient cities, end cities, …) |
| `I`             | Statistics (world size, chunks, regions, last render)                                     |
| `M`             | Measure distance. `Backspace` removes the last point, `Esc` cancels.                      |
| `Esc`           | Close the info panel                                                                      |

Clicking a structure shows its coordinates. **Copy /tp** copies the matching teleport
command. Switching between the Overworld and the Nether keeps your position
(converted 1:8).

The world seed is deliberately **not** stored, because it would let anyone locate
every structure in the world.

---

## Command reference

```
map-renderer                  interactive assistant
map-renderer build            render + scan for structures
map-renderer render           render only
map-renderer scan             scan for structures only
map-renderer worlds           list local Minecraft worlds
map-renderer realm ACTION     Realms: list | login | logout | download
map-renderer update           download the latest uNmINeD
```

On Windows the command is `map-renderer.bat …`, on Linux/macOS `./map-renderer.sh …`.

**Options for `build` / `render` / `scan`**

| Option                     | Meaning                                                                                         |
| -------------------------- | ----------------------------------------------------------------------------------------------- |
| `-w`, `--world NAME\|PATH` | local world (name, folder id or path)                                                           |
| `--realm NAME\|ID`         | download this Bedrock Realm instead                                                             |
| `--slot 1\|2\|3`           | Realm world slot (default: the active slot)                                                     |
| `-o`, `--output DIR`       | map folder to write to (default: `map/`)                                                        |
| `-d`, `--dims …`           | `overworld nether end` (default: all)                                                           |
| `-y`, `--yes`              | no questions, use defaults (for scripts)                                                        |
| `--ignore-running`         | render even while Minecraft is running                                                          |
| `--force`                  | re-render everything instead of only what changed (`build`/`render` only)                       |
| `--zoomin N`               | zoom-in levels with real tiles, 0–3 (each level needs about 4× the disk space)                  |
| `--zoomout N`              | zoom-out levels (default 6)                                                                     |
| `--extras`                 | also list very common finds: spawners, mineshafts, geodes, nether fossils (`build`/`scan` only) |
| `-- …`                     | extra uNmINeD arguments, e.g. `-- --shadows=3d`                                                 |
| `--project DIR`            | project folder (found automatically otherwise)                                                  |

---

## Environment variables

**For `map-renderer`**

| Variable                | Meaning                                                                                         |
| ----------------------- | ----------------------------------------------------------------------------------------------- |
| `MAP_RENDERER_OUTPUT`   | same as `--output`                                                                              |
| `MAP_RENDERER_PROJECT`  | same as `--project`                                                                             |
| `REALMS_CLIENT_VERSION` | Bedrock version reported to the Realms API (e.g. `1.26.30`), in case it asks for a newer client |
| `NO_COLOR`              | turn off colored output                                                                         |

**For the compose files** (in the `.env` next to the compose file: `.env` in the repo
root for the all-in-one file, `server/.env` for `server/docker-compose.yml`)

| Variable                      | Default                                      | Meaning                                                    |
| ----------------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| `MAP_DIR`                     | volume `map`                                 | host folder with the map (absolute, or starting with `./`) |
| `PORT`                        | `8080`                                       | port of the web map (all-in-one file only)                 |
| `COMPOSE_PROFILES`            | –                                            | `realm` also starts the renderer (`server/` file only)     |
| `REALM`                       | –                                            | Realm name or id                                           |
| `REALM_SLOT`                  | active slot                                  | world slot 1–3                                             |
| `INTERVAL`                    | `6h`                                         | pause between two runs (`30m`, `6h`, `1d`, …)              |
| `BUILD_ARGS`                  | –                                            | extra options for `map-renderer build`                     |
| `REALMS_CLIENT_VERSION`       | –                                            | see above                                                  |
| `MAP_RENDERER_IMAGE`          | `ghcr.io/tk-05/map-renderer:latest`          | image of the web page                                      |
| `MAP_RENDERER_RENDERER_IMAGE` | `ghcr.io/tk-05/map-renderer-renderer:latest` | image of the renderer                                      |

---

## Troubleshooting

**"Node.js 18 or newer is needed for Realm downloads"**
Install Node.js from [nodejs.org](https://nodejs.org/), then open a new terminal.

**"403 … Only the Realm owner can download the world"**
The signed-in account doesn't own the Realm. Sign out with `map-renderer realm logout`
and sign in again with the owner's account.

**"The Realms API wants a newer client version"**
Set `REALMS_CLIENT_VERSION` to the current Bedrock version, e.g. `1.26.30` (locally as
an environment variable, on the server in `server/.env`).

**"401 … The sign-in was rejected"**
The stored sign-in has expired or was revoked. Run `realm logout`, then `realm login`.

**The renderer container is waiting for a sign-in**
If you skipped `realm login`, the sign-in code is in the log:
`docker compose logs renderer`.

**"REALM is not set" in the renderer log**
`REALM=…` is missing in `server/.env`.

**The page shows "This map has not been rendered yet"**
That dimension is missing from the map folder. Option A: are `overworld/`, `nether/`
and `end/` directly in `MAP_DIR`, not in a `map/` subfolder? Option B: has the first
run finished (`docker compose logs -f renderer`)?

**"Minecraft is running"**
Close Minecraft so the world is fully saved, or pass `--ignore-running`.

**Tiles are missing or the map stays grey**
Check the read permissions (`chmod -R a+rX …`) and the render log in
`.cache/logs/render-<dimension>.log`.

---

## Project layout

```
index.html                 web interface (dimensions, structures, statistics, measuring)
map/                       generated map (empty in the repo, git-ignored)
map-renderer.bat / .sh     launchers for Windows / Linux / macOS
Dockerfile                 web image (nginx, without the map)
docker-compose.yml         all-in-one: web + renderer from the prebuilt images (Portainer-ready)
docker-compose.build.yml   override to build both images from source instead
.env.example               settings template for the compose files
server/
  docker-compose.yml       web + optional renderer, MAP_DIR
  nginx.conf               nginx configuration
  map-pending.html         notice shown while a dimension is missing
tools/
  map_renderer/            the Python tool (standard library only)
  realm_download/          Node.js helper for Realm sign-in and download
  docker/renderer.sh       loop of the renderer container
  Dockerfile               renderer image (Python + Node)
.cache/                    uNmINeD, Realm sign-in, downloaded worlds, logs (git-ignored)
```

---

## Licenses and privacy

- **uNmINeD** may not be redistributed. It is therefore not included in the
  repository or in any Docker image; the tool downloads it from unmined.net at
  runtime. See the [uNmINeD license terms](https://unmined.net).
- Realm downloads use [prismarine-auth](https://github.com/PrismarineJS/prismarine-auth)
  and [prismarine-realms](https://github.com/PrismarineJS/prismarine-realms). The
  Realms API is not officially documented and may change.
- **`.cache/realms/auth/` contains your Microsoft sign-in.** Don't share this folder
  (or the Docker volume `cache`). It is git- and docker-ignored.
- Only download worlds you are allowed to download.
