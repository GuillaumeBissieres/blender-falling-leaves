# blender-falling-leaves
Create and animate realistic falling leaves
Falling Leaves
An add-on to create and animate realistic falling leaves in Blender

Falling Leaves — Particle System + Wind

This add-on builds a complete falling-leaves scene in one click: an emitter, a leaf mesh, a ground with collision and a fully configured particle system. You can then tune the simulation, swap in your own leaf, add wind and bake the result — all from Blender's N panel.

How to Use — Quick Start

1. Run Falling Leaves
Creates an Emitter plane above the scene, a Leaf object, a Ground plane with Collision and a particle system (500 leaves by default) with Newtonian physics, Brownian motion, drag, damping and random rotation. Press play and the leaves fall.

2. Delete Setup
The trash icon next to the Run button removes the Emitter, Leaf and Ground objects in one click.

How to Use — Leaf Mesh

Import Leaf from Image
Select a PNG or JPG with transparency. The add-on reads the alpha channel to extract the leaf silhouette, then builds a leaf mesh with UV mapping and a material. Adjust Subdivisions and Displacement for a more organic shape.

Replace Leaf Mesh
Select any object in the scene and click this button to use it as the instanced leaf of the particle system.

How to Use — Asset Panel

Click an icon in the grid to append the matching ready-made leaf object into your scene. Import Asset opens Blender's append browser on the asset pack, so you can pick any object from it.

How to Use — Simulation Settings

Fine-tune the particle system without leaving the N panel:
- Particles: leaf count, lifetime, start and end frame
- Size: leaf size and size randomness
- Physics: mass, Brownian motion, drag, damping
- Rotation: randomness and angular velocity

Export to Clipboard copies all particle and wind settings as text, Apply from Clipboard pastes them back (handy to share a look between scenes), and Reset restores the defaults.

How to Use — Wind & Forces

Add Wind
Adds a Wind force field with a ready-made preset and adjusts the particle settings to match, so leaves drift naturally.

Strength / Noise
Two sliders control the wind directly from the panel.

Delete Wind (trash icon)
Removes the wind field in one click.

Bake Simulation
Bakes the particle simulation for reliable playback and rendering.

Advanced Options

- On-demand asset pack: the leaf asset pack (about 127 MB) is not bundled in the extension. Download it once from the add-on preferences with the Download Asset Pack button.
- Online access only on click: the add-on connects to the internet only when you press the download button, and only if Allow Online Access is enabled in Blender's preferences.
- Survives updates: the pack is stored in the extension's user folder, so updating the add-on does not remove it.
- Non-destructive: Delete Setup and Delete Wind only remove the objects created by the add-on.

Requirements

- Blender 4.2 or newer.
- Import Leaf from Image requires OpenCV (opencv-python-headless).
