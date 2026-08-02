# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import bpy
import bpy.utils.previews
import os
from bpy_extras.io_utils import ImportHelper
from bpy.props import (StringProperty, IntProperty, FloatProperty,
                       BoolProperty, EnumProperty)

# ---------------------------------------------------------------------------
# Preview icons
# ---------------------------------------------------------------------------
_icons = None
_ASSETS = os.path.join(os.path.dirname(__file__), 'assets')
_ICONS  = os.path.join(_ASSETS, 'icons')
_MENU   = os.path.join(_ICONS, 'Menu_icons')

# Item map for enum stability (Blender requires stable pointers)
_item_map = dict()


def make_enum_item(_id, name, descr, preview_id, uid):
    lookup = str(_id) + "\0" + str(name) + "\0" + str(descr) + "\0" + str(preview_id) + "\0" + str(uid)
    if lookup not in _item_map:
        _item_map[lookup] = (_id, name, descr, preview_id, uid)
    return _item_map[lookup]


def _icon(filename):
    """Return icon_id for a filename inside assets/icons/Menu_icons/."""
    global _icons
    path = os.path.join(_MENU, filename)
    if _icons is None:
        return 0
    if path not in _icons:
        if os.path.exists(path):
            _icons.load(path, path, 'IMAGE')
        else:
            return 0
    return _icons[path].icon_id


def _preview_icon(path):
    """Return icon_id for an absolute path (loads if needed)."""
    global _icons
    if _icons is None or not os.path.exists(path):
        return 0
    if path not in _icons:
        _icons.load(path, path, 'IMAGE')
    return _icons[path].icon_id


# ---------------------------------------------------------------------------
# Asset Panel – enum items (lists PNGs from assets/icons/)
# ---------------------------------------------------------------------------

def _asset_icon_files():
    """Return sorted list of PNG absolute paths from assets/icons/ (not subfolders)."""
    result = []
    if os.path.isdir(_ICONS):
        for f in sorted(os.listdir(_ICONS)):
            if f.lower().endswith('.png'):
                result.append(os.path.join(_ICONS, f))
    return result


def sna_asset_enum_items(self, context):
    """Enum items for the Asset Panel icon grid."""
    items = []
    for i, path in enumerate(_asset_icon_files()):
        name = os.path.splitext(os.path.basename(path))[0]
        icon_id = _preview_icon(path)
        items.append(make_enum_item(path, name, '', icon_id, i))
    if not items:
        items.append(('', 'No Assets', '', 0, 0))
    return items


def sna_asset_enum_update(self, context):
    """When the user clicks an icon, append the matching object from asset_1.blend."""
    selected_path = self.sna_asset_selection
    if not selected_path or not os.path.exists(selected_path):
        return
    # Derive object name from filename (strip extension)
    obj_name = os.path.splitext(os.path.basename(selected_path))[0]
    blend_path = os.path.join(_ASSETS, 'asset_1.blend')
    if not os.path.exists(blend_path):
        return
    before = set(bpy.data.objects)
    bpy.ops.wm.append(
        directory=blend_path + r'\Object',
        filename=obj_name,
        link=False,
    )
    new_objs = [o for o in bpy.data.objects if o not in before]
    if new_objs:
        context.view_layer.objects.active = new_objs[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_emitter():
    """Find the first object that has our particle system."""
    for obj in bpy.data.objects:
        for ps in obj.particle_systems:
            if ps.name == 'FallingLeaves':
                return obj, ps
    return None, None


def _get_leaf():
    """Find the Leaf object used as instance."""
    return bpy.data.objects.get('Leaf')


def _leaf_settings(context):
    """Return (emitter, particle_system, particle_settings) or (None,None,None)."""
    emitter, ps = _get_emitter()
    if emitter and ps:
        return emitter, ps, ps.settings
    return None, None, None


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class FALLINGLEAVES_OT_Run(bpy.types.Operator):
    bl_idname     = 'fallingleaves.run'
    bl_label      = 'Run Falling Leaves'
    bl_description = ('Create the full falling leaves setup: emitter plane, '
                      'leaf mesh, ground plane with collision, and particle system')
    bl_options    = {'REGISTER', 'UNDO'}

    leaf_count:      IntProperty(name='Leaf Count',   default=500,  min=1,   max=10000)
    lifetime:        IntProperty(name='Lifetime',     default=200,  min=10,  max=1000)
    leaf_size:       FloatProperty(name='Leaf Size',  default=0.2,  min=0.01, max=5.0)
    size_random:     FloatProperty(name='Size Random',default=0.5,  min=0.0,  max=1.0)
    emitter_height:  FloatProperty(name='Emitter Height', default=5.0, min=0.1, max=50.0)
    emitter_size:    FloatProperty(name='Emitter Size',   default=10.0, min=1.0, max=100.0)
    ground_size:     FloatProperty(name='Ground Size',    default=12.0, min=1.0, max=100.0)
    brownian:        FloatProperty(name='Brownian',   default=0.47, min=0.0, max=10.0)

    def execute(self, context):
        # --- Leaf mesh ---
        bpy.ops.mesh.primitive_plane_add(size=0.5, location=(0, 0, 0))
        leaf = context.active_object
        leaf.name = 'Leaf'

        # --- Emitter ---
        bpy.ops.mesh.primitive_plane_add(
            size=self.emitter_size,
            location=(0, 0, self.emitter_height))
        emitter = context.active_object
        emitter.name = 'Emitter'

        bpy.ops.object.particle_system_add()
        ps   = emitter.particle_systems[-1]
        ps.name = 'FallingLeaves'
        cfg  = ps.settings
        cfg.type                    = 'EMITTER'
        cfg.count                   = self.leaf_count
        cfg.lifetime                = self.lifetime
        cfg.frame_start             = 1
        cfg.frame_end               = 200
        cfg.normal_factor           = 0.1
        cfg.physics_type            = 'NEWTON'
        cfg.mass                    = 0.01
        cfg.brownian_factor         = self.brownian
        cfg.drag_factor             = 0.108844
        cfg.damping                 = 0.306122
        cfg.integrator              = 'MIDPOINT'
        cfg.timestep                = 0.04
        cfg.use_rotations           = True
        cfg.rotation_mode           = 'VEL'
        cfg.rotation_factor_random  = 1.0
        cfg.phase_factor            = 0.367347
        cfg.phase_factor_random     = 0.721088
        cfg.use_dynamic_rotation    = True
        cfg.angular_velocity_mode   = 'VELOCITY'
        cfg.angular_velocity_factor = 2.3
        cfg.render_type             = 'OBJECT'
        cfg.instance_object         = leaf
        cfg.particle_size           = self.leaf_size
        cfg.size_random             = self.size_random
        cfg.use_scale_instance      = True
        cfg.use_self_effect         = True
        cfg.effector_amount         = 26

        # --- Ground ---
        bpy.ops.mesh.primitive_plane_add(
            size=self.ground_size,
            location=(0, 0, 0))
        ground = context.active_object
        ground.name = 'Ground'
        bpy.ops.object.modifier_add(type='COLLISION')
        coll = ground.modifiers[-1]
        coll.settings.damping         = 1.0
        coll.settings.friction_factor = 1.0

        context.scene.gravity[2] = -9.81
        context.scene.frame_start = 1
        context.scene.frame_end   = 250
        context.view_layer.update()

        self.report({'INFO'}, f"Falling leaves created — {self.leaf_count} leaves")
        return {'FINISHED'}


class FALLINGLEAVES_OT_Delete(bpy.types.Operator):
    bl_idname     = 'fallingleaves.delete'
    bl_label      = 'Delete Setup'
    bl_description = 'Remove the Emitter, Leaf and Ground objects created by Run Falling Leaves'
    bl_options    = {'REGISTER', 'UNDO'}

    def execute(self, context):
        names = {'Leaf', 'Emitter', 'Ground'}
        removed = []
        for name in names:
            obj = bpy.data.objects.get(name)
            if obj:
                bpy.data.objects.remove(obj, do_unlink=True)
                removed.append(name)
        if removed:
            self.report({'INFO'}, f"Removed: {', '.join(removed)}")
        else:
            self.report({'WARNING'}, "No Falling Leaves objects found to delete")
        return {'FINISHED'}


class FALLINGLEAVES_OT_ImportLeafMesh(bpy.types.Operator, ImportHelper):
    bl_idname     = 'fallingleaves.import_leaf_mesh'
    bl_label      = 'Import Leaf Image'
    bl_description = ('Import a PNG/JPG image and create a leaf mesh from its '
                      'alpha channel silhouette, with UV mapping and material')
    bl_options    = {'REGISTER', 'UNDO'}

    filename_ext  = '.png'
    filter_glob:  StringProperty(default='*.png;*.jpg;*.jpeg', options={'HIDDEN'})

    subdivisions: IntProperty(
        name='Subdivisions', default=2, min=0, max=4,
        description='Subdivision surface levels for the leaf mesh')
    displacement: FloatProperty(
        name='Displacement', default=0.05, min=0.0, max=1.0,
        description='Displacement modifier strength for organic feel')

    def execute(self, context):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.report({'ERROR'},
                "OpenCV (cv2) is required for Import Leaf Image. "
                "Please install it via pip: pip install opencv-python-headless")
            return {'CANCELLED'}

        path = self.filepath
        if not os.path.isabs(path):
            self.report({'ERROR'}, "Please provide an absolute path.")
            return {'CANCELLED'}

        image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if image is None:
            self.report({'ERROR'}, f"Cannot load image: {path}")
            return {'CANCELLED'}

        if image.shape[2] < 4:
            self.report({'ERROR'}, "Image must have an alpha channel (RGBA).")
            return {'CANCELLED'}

        _, _, _, alpha = cv2.split(image)
        _, mask = cv2.threshold(alpha, 1, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            self.report({'WARNING'}, "No contours found in image.")
            return {'CANCELLED'}

        h, w = image.shape[:2]
        base = os.path.splitext(os.path.basename(path))[0]

        for i, contour in enumerate(contours):
            hull     = cv2.convexHull(contour)
            vertices = [(p[0][0] / w - 0.5, -(p[0][1] / h - 0.5), 0.0)
                        for p in hull]
            if len(vertices) < 3:
                continue

            name = f"{base}_Leaf_{i+1}" if len(contours) > 1 else f"{base}_Leaf"
            mesh = bpy.data.meshes.new(name)
            obj  = bpy.data.objects.new(name, mesh)
            context.collection.objects.link(obj)

            mesh.from_pydata(vertices, [], [list(range(len(vertices)))])
            mesh.update()

            # UV
            uv = mesh.uv_layers.new()
            for loop in mesh.loops:
                vx, vy, _ = vertices[loop.vertex_index]
                uv.data[loop.index].uv = (vx + 0.5, vy + 0.5)

            # Material
            mat  = bpy.data.materials.new(name + '_Mat')
            mat.use_nodes = True
            mat.blend_method = 'CLIP'
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links
            nodes.clear()

            out  = nodes.new('ShaderNodeOutputMaterial')
            bsdf = nodes.new('ShaderNodeBsdfPrincipled')
            tex  = nodes.new('ShaderNodeTexImage')
            uvc  = nodes.new('ShaderNodeTexCoord')
            try:
                tex.image = bpy.data.images.load(path)
            except Exception as e:
                self.report({'WARNING'}, f"Could not load texture: {e}")

            links.new(uvc.outputs['UV'],    tex.inputs['Vector'])
            links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
            links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
            links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
            obj.data.materials.append(mat)

            # Modifiers
            sub = obj.modifiers.new('Subdivision', 'SUBSURF')
            sub.levels = self.subdivisions
            sub.render_levels = self.subdivisions

            if self.displacement > 0:
                disp     = obj.modifiers.new('Displacement', 'DISPLACE')
                disp_tex = bpy.data.textures.new(name + '_Disp', type='CLOUDS')
                disp.texture   = disp_tex
                disp.mid_level = 0.5
                disp.strength  = self.displacement

        self.report({'INFO'},
            f"Created {len(contours)} leaf mesh(es) from {os.path.basename(path)}")
        return {'FINISHED'}


class FALLINGLEAVES_OT_ReplaceLeafMesh(bpy.types.Operator):
    bl_idname     = 'fallingleaves.replace_leaf_mesh'
    bl_label      = 'Replace Leaf Mesh'
    bl_description = ('Replace the particle system instance object with the '
                      'currently selected object')
    bl_options    = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        new_leaf = context.active_object
        emitter, ps = _get_emitter()
        if emitter is None:
            self.report({'ERROR'}, "No Falling Leaves particle system found. "
                        "Run Falling Leaves first.")
            return {'CANCELLED'}
        ps.settings.instance_object = new_leaf
        self.report({'INFO'}, f"Leaf mesh replaced with '{new_leaf.name}'")
        return {'FINISHED'}


class FALLINGLEAVES_OT_ImportAsset(bpy.types.Operator):
    bl_idname     = 'fallingleaves.import_asset'
    bl_label      = 'Import Asset'
    bl_description = 'Open the asset_1.blend file browser to append any object'
    bl_options    = {'REGISTER', 'UNDO'}

    def execute(self, context):
        blend_path = os.path.join(_ASSETS, 'asset_1.blend')
        if not os.path.exists(blend_path):
            self.report({'ERROR'}, "Asset file not found.")
            return {'CANCELLED'}
        bpy.ops.wm.append('INVOKE_DEFAULT', filepath=blend_path)
        return {'FINISHED'}


class FALLINGLEAVES_OT_AddWind(bpy.types.Operator):
    bl_idname     = 'fallingleaves.add_wind'
    bl_label      = 'Add Wind'
    bl_description = 'Add a Wind force field to the scene to push the leaves'
    bl_options    = {'REGISTER', 'UNDO'}

    strength: FloatProperty(name='Strength', default=2.0, min=0.0, max=50.0)
    noise:    FloatProperty(name='Noise',    default=0.5, min=0.0, max=10.0)

    def execute(self, context):
        bpy.ops.object.effector_add(type='WIND', location=(0.0, -9.56842041015625, 2.0))
        wind = context.active_object
        wind.name = 'Wind_FallingLeaves'

        wind.rotation_euler[0] = -1.773547649383545
        wind.field.strength = 0.3999999761581421
        wind.field.flow = 5.960464477539063e-08
        wind.field.noise = 0.0
        wind.field.seed = 1
        wind.field.use_absorption = True
        wind.field.falloff_type = 'SPHERE'
        wind.field.z_direction = 'BOTH'

        emitter, ps = _get_emitter()
        if ps:
            cfg = ps.settings
            cfg.count = 25
            cfg.frame_start = -158.79998779296875
            cfg.frame_end = 200.0
            cfg.lifetime = 364.5999755859375
            cfg.particle_size = 0.9385526776313782
            cfg.size_random = 0.2631578743457794
            cfg.mass = 0.009999999776482582
            cfg.brownian_factor = 0.0
            cfg.drag_factor = 0.2579667568206787
            cfg.damping = 0.0
            cfg.use_rotations = True
            cfg.rotation_factor_random = 1.0
            cfg.angular_velocity_factor = 2.299999952316284

        self.report({'INFO'}, 'Wind preset applied')
        return {'FINISHED'}


class FALLINGLEAVES_OT_BakeAnimation(bpy.types.Operator):
    bl_idname     = 'fallingleaves.bake'
    bl_label      = 'Bake Simulation'
    bl_description = 'Bake the particle simulation for reliable playback'
    bl_options    = {'REGISTER'}

    def execute(self, context):
        emitter, ps = _get_emitter()
        if emitter is None:
            self.report({'ERROR'}, "No Falling Leaves setup found.")
            return {'CANCELLED'}
        context.view_layer.objects.active = emitter
        bpy.ops.ptcache.bake_all(bake=True)
        self.report({'INFO'}, "Simulation baked.")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Settings Export / Apply / Reset operators
# ---------------------------------------------------------------------------

_DEFAULT_PARTICLE = {
    'count':                   500,
    'frame_start':             1,
    'frame_end':               200,
    'lifetime':                200,
    'lifetime_random':         0.0,
    'particle_size':           0.2,
    'size_random':             0.5,
    'mass':                    0.01,
    'brownian_factor':         0.47,
    'drag_factor':             0.108844,
    'damping':                 0.306122,
    'use_rotations':           True,
    'rotation_factor_random':  1.0,
    'angular_velocity_factor': 2.3,
}
_DEFAULT_WIND = {
    'strength':       0.4,
    'flow':           0.0,
    'noise':          0.0,
    'seed':           1,
    'use_absorption': True,
    'falloff_type':   'SPHERE',
    'z_direction':    'BOTH',
    'distance_min':   0.0,
    'distance_max':   0.0,
}


def _build_export_text():
    lines = []
    lines.append("=" * 60)
    lines.append("FALLING LEAVES - EXPORT SETTINGS")
    lines.append("=" * 60)
    for obj in bpy.data.objects:
        for ps in obj.particle_systems:
            s = ps.settings
            lines.append(f"\nPARTICLE_SYSTEM={ps.name}")
            lines.append(f"OBJECT={obj.name}")
            lines.append("\n--- EMISSION ---")
            lines.append(f"count={s.count}")
            lines.append(f"frame_start={s.frame_start}")
            lines.append(f"frame_end={s.frame_end}")
            lines.append(f"lifetime={s.lifetime}")
            lines.append(f"lifetime_random={s.lifetime_random}")
            lines.append("\n--- SIZE ---")
            lines.append(f"particle_size={s.particle_size}")
            lines.append(f"size_random={s.size_random}")
            lines.append("\n--- PHYSICS ---")
            lines.append(f"mass={s.mass}")
            lines.append(f"brownian_factor={s.brownian_factor}")
            lines.append(f"drag_factor={s.drag_factor}")
            lines.append(f"damping={s.damping}")
            lines.append("\n--- ROTATION ---")
            lines.append(f"use_rotations={s.use_rotations}")
            lines.append(f"rotation_factor_random={s.rotation_factor_random}")
            lines.append(f"angular_velocity_factor={s.angular_velocity_factor}")
    lines.append("\n\n" + "=" * 60)
    lines.append("WIND FORCE FIELDS")
    lines.append("=" * 60)
    for obj in bpy.data.objects:
        field = getattr(obj, 'field', None)
        if field and field.type == 'WIND':
            lines.append(f"\nWIND_OBJECT={obj.name}")
            lines.append("\n--- MAIN ---")
            lines.append(f"strength={field.strength}")
            lines.append(f"flow={field.flow}")
            lines.append("\n--- NOISE ---")
            lines.append(f"noise={field.noise}")
            lines.append("\n--- WIND ---")
            lines.append(f"seed={field.seed}")
            lines.append(f"use_absorption={field.use_absorption}")
            lines.append("\n--- FALLOFF ---")
            lines.append(f"falloff_type={field.falloff_type}")
            lines.append(f"z_direction={field.z_direction}")
            lines.append(f"distance_min={field.distance_min}")
            lines.append(f"distance_max={field.distance_max}")
            lines.append("\n--- TRANSFORM ---")
            lines.append(f"location={tuple(obj.location)}")
            lines.append(f"rotation={tuple(obj.rotation_euler)}")
            lines.append(f"scale={tuple(obj.scale)}")
    return "\n".join(lines)


def _parse_clipboard(text):
    particle = {}
    wind = {}
    current = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('PARTICLE_SYSTEM='):
            current = 'particle'
            continue
        if line.startswith('WIND_OBJECT='):
            current = 'wind'
            continue
        if '=' not in line or line.startswith('-') or line.startswith('='):
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        val = val.strip()
        try:
            if val in ('True', 'False'):
                val = val == 'True'
            elif '.' in val:
                val = float(val)
            else:
                val = int(val)
        except ValueError:
            pass
        if current == 'particle':
            particle[key] = val
        elif current == 'wind':
            wind[key] = val
    return particle, wind


class FALLINGLEAVES_OT_ExportSettings(bpy.types.Operator):
    bl_idname      = 'fallingleaves.export_settings'
    bl_label       = 'Export Settings'
    bl_description = 'Copy all particle and wind settings to the clipboard'
    bl_options     = {'REGISTER'}

    def execute(self, context):
        context.window_manager.clipboard = _build_export_text()
        self.report({'INFO'}, "Settings copied to clipboard !")
        return {'FINISHED'}


class FALLINGLEAVES_OT_ApplySettings(bpy.types.Operator):
    bl_idname      = 'fallingleaves.apply_settings'
    bl_label       = 'Apply from Clipboard'
    bl_description = 'Paste and apply settings previously exported to clipboard'
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        text = context.window_manager.clipboard
        if not text:
            self.report({'WARNING'}, "Clipboard is empty.")
            return {'CANCELLED'}
        particle_data, wind_data = _parse_clipboard(text)
        applied_ps = 0
        for obj in bpy.data.objects:
            for ps in obj.particle_systems:
                s = ps.settings
                for key, val in particle_data.items():
                    if hasattr(s, key):
                        try:
                            setattr(s, key, val)
                        except Exception:
                            pass
                applied_ps += 1
        applied_wind = 0
        for obj in bpy.data.objects:
            field = getattr(obj, 'field', None)
            if field and field.type == 'WIND':
                for key, val in wind_data.items():
                    if key in ('location', 'rotation', 'scale'):
                        continue
                    if hasattr(field, key):
                        try:
                            setattr(field, key, val)
                        except Exception:
                            pass
                applied_wind += 1
        msg = f"Applied to {applied_ps} particle system(s)"
        if applied_wind:
            msg += f" and {applied_wind} wind object(s)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class FALLINGLEAVES_OT_ResetSettings(bpy.types.Operator):
    bl_idname      = 'fallingleaves.reset_settings'
    bl_label       = 'Reset to Defaults'
    bl_description = 'Reset particle and wind settings to addon defaults'
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in bpy.data.objects:
            for ps in obj.particle_systems:
                s = ps.settings
                for key, val in _DEFAULT_PARTICLE.items():
                    if hasattr(s, key):
                        try:
                            setattr(s, key, val)
                        except Exception:
                            pass
        for obj in bpy.data.objects:
            field = getattr(obj, 'field', None)
            if field and field.type == 'WIND':
                for key, val in _DEFAULT_WIND.items():
                    if hasattr(field, key):
                        try:
                            setattr(field, key, val)
                        except Exception:
                            pass
        self.report({'INFO'}, "Settings reset to defaults.")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

class FALLINGLEAVES_PT_Main(bpy.types.Panel):
    bl_label      = 'Falling Leaves'
    bl_idname     = 'FALLINGLEAVES_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type= 'UI'
    bl_category   = 'Falling Leaves'
    bl_order      = 0

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator('fallingleaves.run',    text='Run Falling Leaves !',
                     icon_value=_icon('leaves.png'))
        row.operator('fallingleaves.delete', text='', icon='TRASH')


# ---------------------------------------------------------------------------
# Asset Panel  (réimplémentation fidèle à la v1.3.0)
# ---------------------------------------------------------------------------

class FALLINGLEAVES_PT_AssetPanel(bpy.types.Panel):
    bl_label      = 'Asset Panel'
    bl_idname     = 'FALLINGLEAVES_PT_asset_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type= 'UI'
    bl_category   = 'Falling Leaves'
    bl_parent_id  = 'FALLINGLEAVES_PT_main'
    bl_order      = 2

    def draw(self, context):
        layout = self.layout
        # Bouton Import Asset (ouvre le browser .blend)
        layout.operator('fallingleaves.import_asset',
                        text='Import Asset',
                        icon_value=_icon('leaf-nature.png'),
                        emboss=True)
        # Grille d'icônes — identique à la v1.3.0
        layout.template_icon_view(
            context.scene,
            'sna_asset_selection',
            show_labels=False,
            scale=5.0,
            scale_popup=5.0,
        )


class FALLINGLEAVES_PT_Settings(bpy.types.Panel):
    bl_label      = 'Simulation Settings'
    bl_idname     = 'FALLINGLEAVES_PT_settings'
    bl_space_type = 'VIEW_3D'
    bl_region_type= 'UI'
    bl_category   = 'Falling Leaves'
    bl_parent_id  = 'FALLINGLEAVES_PT_main'
    bl_order      = 3
    bl_options    = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout

        # --- Export / Apply / Reset row ---
        layout.operator('fallingleaves.export_settings',
                        text='Export to Clipboard', icon='COPYDOWN')
        row = layout.row(align=True)
        row.operator('fallingleaves.apply_settings',
                     text='Apply from Clipboard', icon='PASTEDOWN')
        row.operator('fallingleaves.reset_settings',
                     text='', icon='LOOP_BACK')
        layout.separator()

        emitter, ps, cfg = _leaf_settings(context)
        if cfg is None:
            layout.label(text="Run Falling Leaves first", icon='INFO')
            return

        col = layout.column(align=True)
        col.label(text="Particles:")
        col.prop(cfg, 'count',        text="Leaf Count")
        col.prop(cfg, 'lifetime',     text="Lifetime")
        col.prop(cfg, 'frame_start',  text="Start Frame")
        col.prop(cfg, 'frame_end',    text="End Frame")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Size:")
        col.prop(cfg, 'particle_size', text="Size",   slider=True)
        col.prop(cfg, 'size_random',   text="Random", slider=True)

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Physics:")
        col.prop(cfg, 'mass',            text="Mass",     slider=True)
        col.prop(cfg, 'brownian_factor', text="Brownian", slider=True)
        col.prop(cfg, 'drag_factor',     text="Drag",     slider=True)
        col.prop(cfg, 'damping',         text="Damping",  slider=True)

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Rotation:")
        col.prop(cfg, 'rotation_factor_random', text="Randomize", slider=True)
        col.prop(cfg, 'angular_velocity_factor',text="Angular Velocity", slider=True)


class FALLINGLEAVES_PT_LeafMesh(bpy.types.Panel):
    bl_label      = 'Leaf Mesh'
    bl_idname     = 'FALLINGLEAVES_PT_leafmesh'
    bl_space_type = 'VIEW_3D'
    bl_region_type= 'UI'
    bl_category   = 'Falling Leaves'
    bl_parent_id  = 'FALLINGLEAVES_PT_main'
    bl_order      = 1
    bl_options    = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator('fallingleaves.import_leaf_mesh',
                        text='Import Leaf from Image',
                        icon_value=_icon('four-leaves.png'))
        layout.separator()
        layout.operator('fallingleaves.replace_leaf_mesh',
                        text='Replace Leaf Mesh',
                        icon_value=_icon('three_leaves.png'))

        emitter, ps, cfg = _leaf_settings(context)
        if cfg and cfg.instance_object:
            box = layout.box()
            box.label(text=f"Current: {cfg.instance_object.name}", icon='MESH_DATA')


class FALLINGLEAVES_PT_Wind(bpy.types.Panel):
    bl_label      = 'Wind & Forces'
    bl_idname     = 'FALLINGLEAVES_PT_wind'
    bl_space_type = 'VIEW_3D'
    bl_region_type= 'UI'
    bl_category   = 'Falling Leaves'
    bl_parent_id  = 'FALLINGLEAVES_PT_main'
    bl_order      = 4
    bl_options    = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator('fallingleaves.add_wind', icon='FORCE_WIND')

        wind = bpy.data.objects.get('Wind_FallingLeaves')
        if wind and wind.field:
            box = layout.box()
            box.label(text="Wind Settings:", icon='FORCE_WIND')
            col = box.column(align=True)
            col.prop(wind.field, 'strength', text="Strength", slider=True)
            col.prop(wind.field, 'noise',    text="Noise",    slider=True)

        layout.separator()
        layout.operator('fallingleaves.bake', icon='RENDER_ANIMATION')


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

classes = (
    FALLINGLEAVES_OT_Run,
    FALLINGLEAVES_OT_Delete,
    FALLINGLEAVES_OT_ImportLeafMesh,
    FALLINGLEAVES_OT_ReplaceLeafMesh,
    FALLINGLEAVES_OT_ImportAsset,
    FALLINGLEAVES_OT_AddWind,
    FALLINGLEAVES_OT_BakeAnimation,
    FALLINGLEAVES_OT_ExportSettings,
    FALLINGLEAVES_OT_ApplySettings,
    FALLINGLEAVES_OT_ResetSettings,
    FALLINGLEAVES_PT_Main,
    FALLINGLEAVES_PT_AssetPanel,
    FALLINGLEAVES_PT_Settings,
    FALLINGLEAVES_PT_LeafMesh,
    FALLINGLEAVES_PT_Wind,
)


def register():
    global _icons
    _icons = bpy.utils.previews.new()

    # EnumProperty pour la grille d'icônes de l'Asset Panel
    bpy.types.Scene.sna_asset_selection = EnumProperty(
        name='Asset Selection',
        description='Sélectionner un asset à importer',
        items=sna_asset_enum_items,
        update=sna_asset_enum_update,
    )

    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _icons
    if _icons:
        bpy.utils.previews.remove(_icons)
        _icons = None

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    if hasattr(bpy.types.Scene, 'sna_asset_selection'):
        del bpy.types.Scene.sna_asset_selection
