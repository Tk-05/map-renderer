# Minecraft Map Renderer

A web map for Minecraft worlds (Bedrock and Java). Browse the Overworld, Nether and
End in the browser, with a list of all structures found (portals, villages,
strongholds, ancient cities, …), an optional biome map, world statistics, and a
distance measuring tool.

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

**Biome map.** Answer "Also render biome maps?" with yes, or pass `--biomes`:

```bash
map-renderer build --world "SMP" --biomes -y
```

This renders the Overworld and the Nether a second time, colored by biome, into
`map/overworld-biomes/` and `map/nether-biomes/`, and writes the legend to
`map/biomes.json`. On the web page, **Layers → Biomes** (or key `B`) switches to the biome
map at the same position and shows the legend. The legend can be collapsed with the
arrow next to its title. Render time and disk space for these two dimensions roughly
double. The End has a single biome and gets no biome map.

For **Bedrock worlds** (including Realms), the tool also reads the surface biomes
straight from the world (about a minute for a large world) and writes them to
`map/biomedata/` (a few MB, one small file per region, in 4×4-block cells). The page
then shows the biome under the mouse pointer, or where you tap on a touch screen, and
the legend lists only the biomes that occur, with their share of the explored area.
Near biome borders the name can be off by a few blocks. For the Overworld it also
stores the surface height, used by the cursor info.

To **find a biome**, untick biomes in the legend (or click **Hide all** and tick only
the ones you are looking for; a group checkbox switches a whole group such as all
oceans). Hidden biomes are dimmed on the map, so the selected ones stand out, at any
zoom level. The selection is remembered in the browser.

**Cave map.** Answer "Also render a cave map?" with yes, or pass `--caves`:

```bash
map-renderer build --world "SMP" --caves -y
```

This renders the Overworld a second time with everything above y = −45 left out, into
`map/overworld-caves/`: a cut through the underground that shows caves, ancient cities
(around y = −51) and the deep dark. Choose another height with `--cave-top Y`. On the
web page, **Layers → Caves** (or key `C`) switches to it at the same position; the biome
map and the cave map are alternatives, so switching one on switches the other off.
It roughly doubles the Overworld's render time and disk space. Chunks last saved before
Minecraft 1.18 have no blocks below y = 0 and stay black.

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

# Also render biome maps
#   in .env:  BUILD_ARGS=--biomes

# Also render the cave map (or both: BUILD_ARGS=--biomes --caves)
#   in .env:  BUILD_ARGS=--caves

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

The tool bar on the right is grouped: **Search** · **Layers**, **Structures**,
**Statistics** · **Farm radius**, **Measure** · **Help**. **Layers** holds the map type
(normal, biome map, cave map) and the overlays (other dimension, chunk grid, slime
chunks); the number on its button says how many are switched on. **Help** (`?`) lists
every shortcut and the colours used on the map.

**Cursor info**: a line at the bottom shows the block under the mouse (or where you
tap): `X · Y · Z · biome · chunk · slime chunk`. Y and the biome come from the biome
data (Bedrock, rendered with `--biomes`); Y is the highest block of the 4 × 4 cell, so
trees and roofs count, and it is only shown for the Overworld (the Nether's height map
is its bedrock roof). Switch it off under **Layers → Cursor info**.

uNmINeD's own coordinate box, zoom buttons and coordinate grid are removed from the
map; the cursor info and the chunk grid replace them. Zoom with the mouse wheel or by
pinching. The scale bar stays.

**Right-click menu** (or a long press on touch screens), in the same style as the rest
of the page. Its header shows the spot (X · Y · Z, chunk, biome). It can copy the
coordinates, a `/tp` command or a `markers.json` line, mark the spot, put the farm
radius there, search for the nearest structure or biome from there, jump to the same
spot in the other dimension (÷ 8 / × 8), and switch the chunk grid, slime chunks,
other dimension, cursor info and scale bar. Arrow keys move through it, `Esc` closes it.

| Key             | Action                                                                                    |
| --------------- | ----------------------------------------------------------------------------------------- |
| `1` / `2` / `3` | Overworld / Nether / End                                                                  |
| `L`             | Layers: map type (normal, biomes, caves) and overlays (grid, slime chunks, other dimension) |
| `?`             | All keyboard shortcuts and what the colours mean                                          |
| `F` or `/`      | Search: coordinates, structures, biomes, waypoints (see below)                            |
| `K`             | Slime chunks (Bedrock, Overworld; zoom in to see them)                                    |
| `C`             | Cave map of the Overworld (only shown if rendered with `--caves`)                         |
| `S`             | Toggle the structure list (portals, villages, strongholds, ancient cities, end cities, …) |
| `I`             | Statistics (world size, chunks, regions, last render)                                     |
| `B`             | Biome map with legend (only shown if rendered with `--biomes`); press again to switch off. Hover or tap shows the biome (Bedrock) |
| `M`             | Measure distance. `Backspace` removes the last point, `Esc` cancels.                      |
| `R`             | Farm radius: spawn and despawn circles around a point (see below)                         |
| `G`             | Chunk and region grid                                                                     |
| `O`             | Other dimension: portals and waypoints of the Nether / Overworld (1:8) and portal links   |
| `Esc`           | Close the info panel                                                                      |

**Search** (magnifier button, `F` or `/`) measures from the map centre, marked with a
crosshair while the search is open:

- **Coordinates**: `120 -340`, `120 64 -340` or a pasted `/tp @s 120 64 -340` jumps
  there and drops a pin. You also get the same spot in the linked dimension
  (Overworld ÷ 8 = Nether).
- **Structures**: e.g. `village`, `stronghold`, `fortress` lists the nearest ones with
  distance and direction; also from the other dimension (a Nether fortress from the
  Overworld, measured from the matching Nether position).
- **Biomes** (Bedrock): e.g. `mushroom` finds the nearest occurrence. **Highlight**
  switches to the biome map with only that biome visible.
- Empty: the nearest village, stronghold, ancient city, trial chamber and so on.

Arrow keys choose a result, `Enter` jumps, `Esc` closes.

After a jump, the result's info panel opens. Closing it (**Close**, `Esc` or a click on
the map) brings the search back with the same results, the visited one selected, so
`↓` + `Enter` goes to the next one. Distances stay measured from where you searched;
**Measure from here** switches to the current map centre. `Esc` in the search box ends
the search.

**Farm radius** (target button, `R`): click the map to set the centre, e.g. the AFK
spot of a mob farm. Circles show the Bedrock distances around it (from the Minecraft
Wiki, "Simulation distance"):

| Circle | Meaning (Bedrock) |
| --- | --- |
| 24 | no natural spawning closer to the player |
| 32 | mobs can despawn randomly from here on |
| 44 | spawning and despawning limit at simulation distance 4 (the default) |
| 128 | limit at simulation distance 6 and more |
| own | any radius you enter |

At simulation distance 6+, Bedrock also spawns mobs only within *n − 1* chunks
(taxicab distance) of the player's chunk; choose the simulation distance to draw that
diamond of chunks. It is usually smaller than the 128 circle, so it is what limits a
farm. All distances are spherical, so the circles hold at the centre's height and the
area shrinks above and below it. **Copy /tp** copies a teleport to the centre. The
chosen circles are remembered in the browser.

**Chunk and region grid** (Layers → Chunk grid, `G`): close up, chunk borders (16 blocks) with
the chunk coordinates in each chunk, and when zoomed in further also the block
coordinates of its corner; further out, region borders (512 blocks = 32 × 32 chunks)
in yellow with region coordinates. It lines up with slime chunks and the spawn diamond
of the farm radius, works in every dimension and map, and is remembered in the browser.

**Other dimension and portal links** (Layers → Other dimension, `O`; Overworld and
Nether): the other dimension's nether portals and waypoints appear as translucent,
dashed "ghosts" where they land on this map (Nether × 8 on the Overworld, Overworld ÷ 8
on the Nether), so you see right away where a portal comes out. Each portal gets a line
to the ghost of the portal it links to:

| Line | Meaning |
| --- | --- |
| green | the link works both ways |
| orange, dashed | one-way: going back, you arrive at a different portal |
| red ring | no portal on the other side: the game would build a new one |

Clicking a ghost shows the real portal or waypoint with its own coordinates. A
portal's info also says where the way back leads. The links are predicted from the
scanned portals (`map-renderer scan`), using the 1:8 rule and the search radius of the
target dimension.

**Placed things are kept:** the radius centre and the last measured line are saved in
your browser, per dimension, and are back when you open the tool again, also after a
reload. **Clear** removes them. They are not shared with other visitors.

**Slime chunks** (Layers → Slime chunks, `K`): in Bedrock, slime chunks depend only on the chunk
coordinates, not on the seed, so the map can show them exactly without revealing the
seed. Shown in green (outlined when zoomed in) on the Overworld of Bedrock worlds.

### Waypoints

Your own places (bases, farms, shops, …) go into a `markers.json` that is kept outside
the image and the map, in its own folder:

- **Server:** set `MARKERS_DIR` (in `.env` or the Portainer stack) to a host folder,
  e.g. `MARKERS_DIR=/srv/map-markers`, and put `markers.json` there. It is mounted
  read-only at `/markers/`. A folder is mounted rather than the single file, so edits
  show up even when an editor replaces the file while saving.
- **Locally:** `markers/markers.json` next to `index.html` (git-ignored).
- Fallback for older setups: `map/markers.json`.

The page reads the file on every load (no caching), so editing it is enough:

```json
{
  "markers": [
    { "name": "Main base", "dim": "overworld", "x": 120, "y": 64, "z": -340,
      "icon": "🏠", "color": "#e67e22", "description": "Storage and beds" },
    { "name": "Iron farm", "x": 260, "z": -180, "icon": "⚙️", "color": "#7f8c8d" },
    { "name": "Nether hub", "dim": "nether", "x": 10, "y": 70, "z": -20, "icon": "🧭" }
  ]
}
```

Only `name`, `x` and `z` are required. `dim` defaults to `overworld`, `icon` to 📍 and
`color` to red. Waypoints are drawn above the structures with their name, can be
switched off in the structure list (**Waypoints**), and are found by the search (by name
or description; with an empty search they come first).

To create an entry, open a place (a structure, or coordinates from the search) and
click **Copy waypoint**: a ready line for `markers.json` is copied to the clipboard.

**Paths and areas** go into the same file, next to `markers`: roads, ice highways and
rails as `paths`, towns and claims as `areas`. Points are `[x, z]` block coordinates
(an area is closed automatically):

```json
{
  "markers": [ … ],
  "paths": [
    { "name": "Main road", "points": [[120, -340], [200, -260], [260, -180]],
      "color": "#f5f6fa", "width": 5, "description": "Base to iron farm" },
    { "name": "Ice highway north", "dim": "nether", "points": [[10, -20], [10, -300]],
      "color": "#74b9ff", "dashed": true }
  ],
  "areas": [
    { "name": "Spawn town", "points": [[-40, -160], [90, -160], [90, -40], [-40, -40]],
      "color": "#f6b93b", "description": "Shared town" }
  ]
}
```

`name` and `points` are required (a path needs 2 points, an area 3); `dim`, `color`,
`width` (1–12), `dashed` and `description` are optional. Paths show their name along
the line, areas a light fill and their name. Clicking a path, or an area's outline or
name, shows its length or size; the inside of an area stays clickable for the map.
They can be switched off in the structure list (**Paths & areas**) and are found by the
search. The easiest way to get the points: draw the route with the **Measure** tool
(`M`) and click **Copy as path** or **Copy as area**.

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
| `--biomes`                 | also render biome maps of the Overworld and Nether (`build`/`render` only)                      |
| `--caves`                  | also render a cave map of the Overworld (`build`/`render` only)                                 |
| `--cave-top Y`             | height the cave map starts at (default −45)                                                     |
| `--nether-top Y`           | render the Nether from height Y down, below its bedrock roof (default 100; `0` = from the top)  |
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
| `MARKERS_DIR`                 | volume `markers`                             | host folder with `markers.json` (own waypoints)            |
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

**The Nether is only grey**
That is the bedrock roof seen from above. The Nether is rendered from y = 100 down by
default (`--nether-top`). A map rendered before that setting existed must be redrawn
completely: `map-renderer render --dims nether --force`.

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
