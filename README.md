# Portland transit in space-time

A browser visualization of 755 scheduled TriMet, Portland Streetcar, and Portland Aerial Tram trips that depart between 07:00 and 09:00 on Monday 16 November 2026.

## Run it

```sh
make serve
```

Open <http://localhost:8000>. A local server is needed because browsers do not allow `fetch()` from a `file://` page. Use `HTTP_PORT=9000 make serve` for another port.

## Read it

- Horizontal position is longitude and latitude.
- Vertical position is scheduled time, with later times upward.
- Color is each trip's average scheduled speed.
- A fast route covers more horizontal distance for the same vertical rise, so its line is flatter.

Drag to orbit, scroll/pinch to zoom, and hover a line for its route, times, endpoints, distance, and speed.

## Data

- Source: [TriMet GTFS](https://developer.trimet.org/GTFS.shtml)
- Feed version: `20261011-20261021-0903`
- Feed archive: `data/trimet-gtfs.zip`
- Terms: [TriMet developer terms of use](https://developer.trimet.org/terms_of_use.shtml)

Regenerate the compact browser data after replacing `data/trimet-gtfs.zip`:

```sh
make download           # fetch the current official GTFS archive
make                    # fetch pinned browser assets and build data/portland-space-time.json
make clean              # delete generated browser data and temporary files
make distclean          # also delete downloaded GTFS and Three.js files
```

The generator selects the service date, keeps trips whose first departure is in the window, follows GTFS shapes between stops, and decimates shape vertices to at least 50 m spacing. Times come from GTFS stop arrivals and departures.
