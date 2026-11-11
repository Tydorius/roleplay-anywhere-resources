# Smooth edges

Water and road shores lose their cell-grid steps — corners cut diagonally, one-cell-wide ends
rounded — and natural region edges fade along their true outline. It works on existing
scenarios with no changes; scenarios can fine-tune it.

No bundle patch: it repaints through the loader's two render hooks.

**Game version:** Anywhere RPG 1.0 (Steam alpha build 26557354), with code-mod loader 2.2.0.

## What the game already does

- Every liquid or road cell is an opaque 12×12 square on a per-chunk canvas; the chunk is
  blurred by 7 px and cropped into a tile. The water shader masks water by that canvas's alpha
  and draws shore foam where alpha passes 0.5 — so the canvas's steps are the shore's steps.
- Every region's ground fades at its edges with one alpha per vertex: the blurred mean of the
  four cells the vertex touches. An organic blob's rounded rim gets the rectangle's blocky
  fade, and an edge cut by water a ragged one.

Walking never changes: the game decides walkability per cell, and this mod only redraws.

## What the mod does

**Shores** (the liquid-canvas hook): one read of the chunk's cell grid — a single
`getImageData`, sampled at cell centres, colours compared exactly, so water, roads and
different liquids each keep their own edges — then marching squares over every 2×2 block:

- a convex corner of a liquid area is cut diagonally: the outer half-cell triangle is cleared;
- a concave corner is filled diagonally, but only when both orthogonal neighbours are the same
  colour, so a checkerboard diagonal stays open;
- a one-cell-wide end (a cell with at most one same-colour neighbour) is rounded with a
  half-cell circle; a lone cell becomes a dot.

Every op stays inside one cell's own square. The blur drops from 7 to 5 px: with the steps
gone, less smear is needed to look soft. The flow canvas is untouched — the game already
spreads the liquid kind two cells past every shore.

**Ground fades** (the ground-fade hook):

- a region whose mask is exactly 1.0's own organic blob (reproduced bit-exactly, checked
  against the game's golden masks in the test suite) fades along the blob's continuous
  outline;
- any other mask is a region cut by water: the cut fades by its signed distance to the mask's
  boundary, marching squares at 0.5, so corners cut diagonally there too;
- vertices more than 3 cells from a masked-out cell, or from the blob's outline, keep the
  game's own fade — so rectangles keep their normal edge blend.

Each mask's fade is built once and cached: the renderer refills the ground tile whenever the
fade array changes identity, so the same array goes back every sync.

## Scenario settings (optional)

```json
"arpgMods": {
  "smooth-edges": { "shores": true, "ground": true, "blur": 5 }
}
```

- `shores: false` leaves the water and road canvases as the game paints them, with the game's
  7 px blur.
- `ground: false` leaves the region fades as the game computes them.
- `blur` is the chunk blur radius (default 5).
- `"smooth-edges": false` turns the whole mod off for that scenario.

## Debugging

```js
__arpg.smoothEdges.setEnabled(false) // compare with the plain game; true turns it back on
__arpg.smoothEdges.stats()           // chunks, msPerChunk, fades, msPerFade
__arpg.smoothEdges.resetStats()      // start counting afresh
```

The pure pieces (`shoreOps`, `paintShores`, `organicFade`, `maskFade`, `blob`) sit on the same
object; the test suite drives them directly.

## How it hooks in

`onLiquidCanvas` runs once per water/road chunk between the painting and the blur: whatever is
on the colour canvas is what gets blurred into the tile, so reshaping it costs nothing extra.
`onGroundFade` runs when the game fades a region's ground; the first hook returning a
same-length `Float32Array` wins. A toggle rebuilds what is on screen: the water tiles are the
terrain layer's, dropped and cleared the way the layer's own `drop` does and rebuilt by its
`sync`, the ground tiles by the scene's `syncGroundTiles`. Every access is guarded: on a scene
without those pieces, nothing happens.
