# Machine point sets (named templates of measurement points)

Contract between WorkshopService and the Machine page (bed view of Mesh and Level). Branch m7-service.

## What it is

A point set is a named list of X / Y positions in machine coordinates (mm), for example "corners" or "centre and edges". The Mesh and the Level
pages share the sets of the machine: a set made on one can be loaded on the other. The sets belong to the machine (they live on its SD card),
not to a browser or to a person.

## Store

A new settings store named `machine-pointsets` (file `0:/sys/workshop/config/machine-pointsets.json`). It is an ordinary revisioned store, NOT
service-only: it is read with `settings.get` and written with `settings.set` / `settings.merge`, exactly like `laser` or `jog`.

| Operation | Role | Use |
|---|---|---|
| `settings.get {name: "machine-pointsets"}` | operator | `{value, rev}`; `value` is `null` (rev `"0"`) until the first set is saved |
| `settings.set {name: "machine-pointsets", value, base_rev}` | technician | writes the whole value; a changed file answers `conflict` with the current value (the page merges and retries once) |

So: technician and above write, operator reads, viewer does not see it. No new operation and no new permission.

## Shape of the value (written and validated by the page; the service stores any object)

```
{
  "schema": 1,
  "sets": [
    {
      "id": "ps-<base36 time>",      // unique inside the file
      "name": "corners",             // 1..40 characters, unique case-insensitive
      "points": [{"x": 12.5, "y": 8}, ...],   // 1..100 points, mm, at most 3 decimals
      "ts": 1760000000,              // seconds since the epoch, when saved
      "user": "alejandro"            // who saved it ("" if unknown)
    }
  ]
}
```

At most 40 sets; the file stays far under the 2 MiB limit of the settings store. A set is only positions: whether they can be probed (reach,
margin) is decided when it is loaded, against the machine of that moment.

## What it does NOT do

Nothing here moves the machine, probes or fires the laser. A set is data.
