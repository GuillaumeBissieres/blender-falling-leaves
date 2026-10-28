# blender-falling-leaves
An add-on to create and animate realistic falling leaves in Blender

<img width="4167" height="2083" alt="Falling_img_01" src="https://github.com/user-attachments/assets/a8edc86e-fd5a-48e2-a229-2d541f34272f" />

<!-- Add a banner screenshot here: drag & drop an image into the GitHub editor -->

#

**Falling Leaves**

This add-on builds a complete falling-leaves scene in one click: an emitter, a leaf mesh, a ground with collision and a fully configured particle system. You can then tune the simulation, swap in your own leaf, add wind and bake the result — all from within Blender's N panel.


# Requirements

- **Blender 4.2 or newer**
- **Asset pack** (about 127 MB): the ready-made leaf objects are hosted on Hugging Face and downloaded from the add-on preferences — no terminal needed. An internet connection is required for this one-time download.
- **OpenCV** (`opencv-python-headless`): required only for **Import Leaf from Image**. Install it into Blender's Python, for example on Windows:

```
"C:\Program Files\Blender Foundation\Blender 5.0\5.0\python\bin\python.exe" -m pip install opencv-python-headless
```

Adjust the path to match your Blender version.

The asset pack is hosted here: [GBissieres/falling_leaves_assets](https://huggingface.co/datasets/GBissieres/falling_leaves_assets)

<img width="647" height="365" alt="Capture d&#39;écran 2026-10-28 211633" src="https://github.com/user-attachments/assets/0aff4ee0-7d54-4293-a988-22ab17c3b1a6" />

###

<!-- Screenshot: add-on preferences with the Download Asset Pack button -->

# Installation

Download the ZIP file.

Open Blender and go to **Edit** > **Preferences** > **Get Extensions**.

Click the arrow in the top-right corner, choose **Install from Disk**, and select the ZIP file.

Enable the add-on by checking the corresponding box.

Go to **Edit** > **Preferences** > **System** > **Network** and enable **Allow Online Access**.

Go to **Edit** > **Preferences** > **Add-ons** > **Falling Leaves** and click **Download Asset Pack**. A progress counter shows the download status and Blender stays responsive.

Access **Falling Leaves** in the **N menu** (sidebar) under the **Falling Leaves tab**.

If you use a full version that already includes the asset pack, the download step is not needed.


# How to Use — Quick Start

1. **Run Falling Leaves** : Creates an Emitter plane above the scene, a Leaf object, a Ground plane with Collision and a particle system (500 leaves by default) with Newtonian physics, Brownian motion, drag, damping and random rotation. Press play and the leaves fall.

<!-- Screenshot: the scene right after clicking Run Falling Leaves -->

2. **Delete Setup** : The trash icon next to the Run button removes the Emitter, Leaf and Ground objects in one click.

###

<img width="340" height="211" alt="Capture d&#39;écran 2026-10-28 230946" src="https://github.com/user-attachments/assets/8ac4e2fd-fa7b-4926-91a9-7a1577f884ba" />

###

<img width="1894" height="998" alt="falling_leaves_6" src="https://github.com/user-attachments/assets/bb0e2ec3-bca6-4fc1-864a-4b63a72db0e0" />


<!-- Screenshot: the main panel with the Run button and trash icon -->

###


# How to Use — Leaf Mesh

1. **Import Leaf from Image** : Select a PNG or JPG with transparency. The add-on reads the alpha channel to extract the leaf silhouette, then builds a leaf mesh with UV mapping and a material. Adjust **Subdivisions** and **Displacement** in the Adjust Last Operation panel for a more organic shape.

2. **Replace Leaf Mesh** : Select any object in the scene and click this button to use it as the instanced leaf of the particle system. The current leaf object is displayed in the panel.

###

<!-- Screenshot: Leaf Mesh panel -->

###


# How to Use — Asset Panel

Click an icon in the grid to append the matching ready-made leaf object into your scene. **Import Asset** opens Blender's append browser on the asset pack, so you can pick any object from it.

If the pack is not installed yet, the panel shows a **Download Asset Pack** button.

###

<img width="432" height="275" alt="Capture d&#39;écran 2026-10-28 231211" src="https://github.com/user-attachments/assets/5413b8e4-2567-4e19-936c-8809d583cd99" />

<!-- Screenshot: Asset Panel icon grid -->

###

<img width="1894" height="998" alt="falling_leaves_10 (2)" src="https://github.com/user-attachments/assets/e15339c4-2b88-4fbe-b8ae-8b8d0e66b364" />


###


# How to Use — Simulation Settings

Fine-tune the particle system without leaving the N panel:

- **Particles** : Leaf Count, Lifetime, Start Frame, End Frame
- **Size** : leaf size and size randomness
- **Physics** : Mass, Brownian, Drag, Damping
- **Rotation** : Randomize and Angular Velocity

### Settings Export

- **Export to Clipboard** : Copies all particle and wind settings as text.
- **Apply from Clipboard** : Pastes them back — handy to reuse a look in another scene.
- **Reset** : Restores the default values.

###

<img width="442" height="477" alt="Capture d&#39;écran 2026-10-28 234453" src="https://github.com/user-attachments/assets/db97228c-8d68-4495-90d3-ad0515c3aeb7" />


<!-- Screenshot: Simulation Settings panel -->

###


# How to Use — Wind & Forces

1. **Add Wind** : Adds a Wind force field with a ready-made preset and adjusts the particle settings to match, so leaves drift naturally.
2. **Strength / Noise** : Two sliders control the wind directly from the panel.
3. **Delete Wind** : The trash icon next to Add Wind removes the wind field in one click.
4. **Bake Simulation** : Bakes the particle simulation for reliable playback and rendering.

<img width="346" height="153" alt="Capture d&#39;écran 2026-10-28 224025" src="https://github.com/user-attachments/assets/37d0811f-6dd6-4390-b712-a349cf6bdc0b" />

###

<img width="1894" height="998" alt="falling_leaves_5" src="https://github.com/user-attachments/assets/d0ee873d-c904-42bc-9c69-51e02caede3e" />


###

<!-- Screenshot: Wind & Forces panel -->

###


# Advanced Options

- **On-demand Asset Pack** : The heavy `.blend` and textures are not bundled in the add-on, which keeps the install small. Download them once from the preferences.
- **Online Access Only on Click** : The add-on connects to the internet only when you press the download button, and only if **Allow Online Access** is enabled in Blender.
- **Survives Updates** : The asset pack is stored in the extension's user folder, so updating the add-on does not remove it.
- **Background Download** : The pack downloads in a separate thread with a progress counter — Blender never freezes.
- **Safe Download** : Files are written to a temporary `.part` file and size-checked before being validated, so an interrupted download never leaves a corrupted pack.
- **Copy & Share Settings** : Particle and wind settings can be exported to the clipboard and applied in another scene.
- **Non-destructive Cleanup** : Delete Setup and Delete Wind only remove the objects created by the add-on.
