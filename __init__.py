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
import collections
import json
import math
import mathutils
import os
import re
from bpy_extras.io_utils import ImportHelper
from bpy.props import (StringProperty, IntProperty, FloatProperty,
                       BoolProperty, EnumProperty, PointerProperty)

# ---------------------------------------------------------------------------
# Asset library
#   * 3 bundled assets (assets/asset_N.blend): a plane driven by a Geometry
#     Nodes modifier each
#   * the user's own assets, saved with a viewport thumbnail (Studio Library
#     style). Everything lives on disk, no network access is needed.
# ---------------------------------------------------------------------------
_ASSETS = os.path.join(os.path.dirname(__file__), 'assets')

# identifier, label, file inside assets/
_BUILTIN = (
    ('asset_1', 'Asset 1', 'asset_1.blend'),
    ('asset_2', 'Asset 2', 'asset_2.blend'),
    ('asset_3', 'Asset 3', 'asset_3.blend'),
)
_USER_PREFIX = 'user:'
_DOWNLOAD_PREFIX = 'dl:'
_DOWNLOADED_DIR = 'downloaded'   # optional assets fetched from the repository
_ONLINE = False                 # set to True by the optional online block
_ONLINE_CLASSES = ()
_THUMB_SIZE = 256

_icons = None          # preview collection: thumbnails + default glyph

_Item = collections.namedtuple('_Item', 'ident label blend thumb builtin obj',
                               defaults=(None,))   # obj: one object of a shared .blend


def _user_dir(sub, create=False):
    """Persistent folder that survives add-on updates."""
    try:
        return bpy.utils.extension_path_user(__package__, path=sub, create=create)
    except Exception:
        try:
            return bpy.utils.user_resource(
                'CONFIG', path=os.path.join('falling_leaves', sub), create=create)
        except Exception:
            return None


def _safe_name(name):
    name = re.sub(r'[^\w\- ]', '_', name or '').strip()[:64]
    if name.upper() in {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'LPT1', 'LPT2'}:
        name += '_'
    return name


_ASSET_NAME = re.compile(r'^asset[ _\-]?\d+', re.I)
_names_cache = {}


def _blend_object_names(path):
    """Object names stored in a .blend (cached until the file changes)."""
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
        if key not in _names_cache:
            with bpy.data.libraries.load(path) as (src, _dst):
                _names_cache[key] = set(src.objects)
        return _names_cache[key]
    except Exception:
        return set()


def _library_items():
    """All assets: the bundled ones first, then the user's (sorted by name)."""
    items = []
    tdir = _user_dir('thumbnails')
    for ident, label, fname in _BUILTIN:
        thumb = os.path.join(tdir, ident + '.png') if tdir else None
        items.append(_Item(ident, label, os.path.join(_ASSETS, fname), thumb, True))
    ddir = _user_dir(_DOWNLOADED_DIR)
    if ddir and os.path.isdir(ddir):
        files = sorted(os.listdir(ddir), key=str.lower)
        images = {}
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() in ('.png', '.jpg', '.jpeg') and stem not in images:
                images[stem] = os.path.join(ddir, f)
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() != '.blend':
                continue
            path = os.path.join(ddir, f)
            names = _blend_object_names(path)
            # a pack holds several assets: one item per visual / per asset object,
            # added separately (never the whole pack at once)
            picked = sorted((n for n in images if n in names), key=str.lower)
            if not picked:
                picked = sorted((n for n in names if _ASSET_NAME.match(n)), key=str.lower)
            if picked:
                for n in picked:
                    items.append(_Item(_DOWNLOAD_PREFIX + stem + ':' + n, n, path,
                                       images.get(n, os.path.join(ddir, n + '.png')),
                                       False, n))
            else:
                items.append(_Item(_DOWNLOAD_PREFIX + stem, stem, path,
                                   images.get(stem, os.path.join(ddir, stem + '.png')),
                                   False))
    ldir = _user_dir('library')
    if ldir and os.path.isdir(ldir):
        for f in sorted(os.listdir(ldir), key=str.lower):
            stem, ext = os.path.splitext(f)
            if ext.lower() == '.blend':
                items.append(_Item(_USER_PREFIX + stem, stem, os.path.join(ldir, f),
                                   os.path.join(ldir, stem + '.png'), False))
    return items


def _current_item(context):
    ident = context.scene.fl_asset_selection
    for item in _library_items():
        if item.ident == ident:
            return item
    return None


def _has_thumb(item):
    return bool(item.thumb) and os.path.isfile(item.thumb)


def _thumb_target(item):
    """Where the thumbnail of an item is written (creates the folder)."""
    if item.builtin:
        d = _user_dir('thumbnails', create=True)
        return os.path.join(d, item.ident + '.png') if d else None
    return item.thumb


# ---------------------------------------------------------------------------
# Preview icons (thumbnails are loaded from disk, no image ships with the add-on)
# ---------------------------------------------------------------------------
_item_map = dict()   # keeps enum tuples alive (Blender needs stable pointers)


def make_enum_item(_id, name, descr, preview_id, uid):
    lookup = str(_id) + "\0" + str(name) + "\0" + str(descr) + "\0" + str(preview_id) + "\0" + str(uid)
    if lookup not in _item_map:
        _item_map[lookup] = (_id, name, descr, preview_id, uid)
    return _item_map[lookup]


def _thumb_icon(path):
    """Icon id of a PNG on disk; reloaded automatically when the file changes."""
    if _icons is None:
        return 0
    try:
        st = os.stat(path)
        key = '%s|%d|%d' % (path, st.st_mtime_ns, st.st_size)
        if key not in _icons:
            _icons.load(key, path, 'IMAGE')
        return _icons[key].icon_id
    except Exception:
        return 0


def _default_pixels(n=96):
    """RGBA floats of a small procedural leaf (placeholder before a capture)."""
    s = math.sqrt(0.5)
    px = []
    for j in range(n):
        for i in range(n):
            x = (i + 0.5) / n - 0.5
            y = (j + 0.5) / n - 0.5
            u = (x * s + y * s + 0.36) / 0.72          # 0..1 along the leaf
            v = -x * s + y * s                         # across the leaf
            a = 0.0
            if 0.0 < u < 1.0:
                half = 0.19 * math.sin(math.pi * u) ** 0.75
                a = min(max((half - abs(v)) * n / 1.5 + 0.5, 0.0), 1.0)
                if 0.1 < u < 0.88:                      # midrib
                    a *= 1.0 - min(max((0.011 - abs(v)) * n / 1.5 + 0.5, 0.0), 1.0)
            px.extend((0.78, 0.82, 0.78, a))
    return px


def _default_icon():
    if _icons is None:
        return 0
    try:
        if 'default' not in _icons:
            n = 96
            p = _icons.new('default')
            pixels = _default_pixels(n)
            p.image_size = (n, n)
            p.image_pixels_float = pixels
            p.icon_size = (n, n)
            p.icon_pixels_float = pixels
        return _icons['default'].icon_id
    except Exception:
        return 0


def sna_asset_enum_items(self, context):
    """Enum items of the Asset Panel grid."""
    items = []
    for i, it in enumerate(_library_items()):
        icon = _thumb_icon(it.thumb) if _has_thumb(it) else _default_icon()
        tip = ('Bundled asset' if it.builtin else
               'Downloaded asset' if it.ident.startswith(_DOWNLOAD_PREFIX) else 'My asset')
        items.append(make_enum_item(it.ident, it.label, tip, icon, i))
    if not items:
        items.append(('NONE', 'No Assets', '', 0, 0))
    return items


# ---------------------------------------------------------------------------
# Append / save / viewport capture
# ---------------------------------------------------------------------------

def _append_objects(context, blend_path, tag='', only=None):
    """Append the asset of a .blend (object + modifiers + node groups).

    A saved asset can also carry its leaf collection (a dependency of the
    Geometry Nodes modifier): those objects stay inside their collection and
    are not dropped into the scene, only the asset objects are."""
    with bpy.data.libraries.load(blend_path, link=False) as (src, dst):
        if only:      # one asset of a pack (its dependencies come along)
            dst.objects = [only] if only in src.objects else []
        else:
            dst.objects = list(src.objects)
    objs = [o for o in dst.objects if o is not None]
    for o in objs:
        o.use_fake_user = False
    roots = [o for o in objs if not o.users_collection] or objs
    coll = context.collection or context.scene.collection
    for o in roots:
        o['fl_asset'] = tag          # marks the objects the Asset Panel may remove
        coll.objects.link(o)
    for o in context.view_layer.objects:
        o.select_set(False)
    for o in roots:
        o.select_set(True)
    if roots:
        context.view_layer.objects.active = roots[0]
    return roots


# --- leaf collection <-> Collection Info node of an asset ------------------

def _collection_input_identifier(node_group):
    """Identifier of the group input that feeds the Collection Info node."""
    inputs = {it.identifier: it for it in node_group.interface.items_tree
              if getattr(it, 'in_out', '') == 'INPUT'}
    for node in node_group.nodes:
        if node.bl_idname != 'GeometryNodeCollectionInfo':
            continue
        sock = node.inputs.get('Collection')
        for _ in range(16):                       # follow reroutes
            link = next((l for l in node_group.links if l.to_socket == sock), None)
            if link is None:
                break
            src = link.from_node
            if src.bl_idname == 'NodeGroupInput':
                if link.from_socket.identifier in inputs:
                    return link.from_socket.identifier
                break
            if src.bl_idname == 'NodeReroute':
                sock = src.inputs[0]
                continue
            break
    for ident, it in inputs.items():              # fallback: first collection input
        if it.socket_type == 'NodeSocketCollection':
            return ident
    return None


def _set_modifier_input(mod, identifier, value):
    """Set a Geometry Nodes modifier input (new 5.2 API first, legacy after)."""
    props = getattr(mod, 'properties', None)
    group = getattr(props, 'inputs', None) if props is not None else None
    sock = getattr(group, identifier, None) if group is not None else None
    if sock is not None and hasattr(sock, 'value'):
        sock.value = value
    else:
        mod[identifier] = value
    mod.id_data.update_tag()


def _assign_leaf_collection(objs, collection):
    """Plug a collection into the Collection Info input of each asset object.
    Returns the number of objects that were updated."""
    done = 0
    for o in objs:
        for mod in o.modifiers:
            if mod.type != 'NODES' or mod.node_group is None:
                continue
            ident = _collection_input_identifier(mod.node_group)
            if ident is None:
                continue
            try:
                _set_modifier_input(mod, ident, collection)
                done += 1
            except Exception:
                pass
    return done


def _remove_if_unused(datablocks, collection_prop):
    for db in list(datablocks):
        try:
            if db is not None and db.users == 0:
                collection_prop.remove(db)
        except (ReferenceError, RuntimeError):
            pass


def _find_view3d(context):
    """(window, area, region) of a 3D viewport, the current one first."""
    cands = []
    if context.area and context.area.type == 'VIEW_3D' and context.window:
        cands.append((context.window, context.area))
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                cands.append((win, area))
    for win, area in cands:
        for region in area.regions:
            if region.type == 'WINDOW':
                return win, area, region
    return None


def _capture_viewport(context, filepath):
    """Save what the 3D viewport shows as a small transparent PNG."""
    found = _find_view3d(context)
    if not found:
        raise RuntimeError('No 3D viewport found')
    window, area, region = found
    scene = context.scene
    render = scene.render
    ims = render.image_settings
    view_prefs = context.preferences.view
    saved = (render.resolution_x, render.resolution_y, render.resolution_percentage,
             render.film_transparent, ims.file_format, ims.color_mode,
             ims.color_depth, view_prefs.render_display_type)
    tmp = filepath + '.tmp'
    try:
        render.resolution_x = render.resolution_y = _THUMB_SIZE
        render.resolution_percentage = 100
        render.film_transparent = True
        ims.file_format = 'PNG'
        ims.color_mode = 'RGBA'
        ims.color_depth = '8'
        view_prefs.render_display_type = 'NONE'      # no pop-up render window
        with context.temp_override(window=window, area=area, region=region):
            result = bpy.ops.render.opengl(view_context=True)
        if 'FINISHED' not in result:
            raise RuntimeError('Viewport render was cancelled')
        img = bpy.data.images.get('Render Result')
        if img is None:
            raise RuntimeError('No render result')
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        img.save_render(tmp, scene=scene)
        os.replace(tmp, filepath)
    finally:
        (render.resolution_x, render.resolution_y, render.resolution_percentage,
         render.film_transparent, ims.file_format, ims.color_mode,
         ims.color_depth, view_prefs.render_display_type) = saved
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


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


_PATH_EMITTER = 'PathEmitter'
_PATH_PS      = 'FallingLeavesPath'


def _get_path_emitter():
    """The extra emitter created by Apply Path (separate particle system)."""
    obj = bpy.data.objects.get(_PATH_EMITTER)
    if obj:
        for ps in obj.particle_systems:
            if ps.name == _PATH_PS:
                return obj, ps
    return None, None


def _helpers_hidden():
    """True when the emitter plane (and ground) are currently hidden."""
    emitter, ps = _get_emitter()
    if emitter:
        return not emitter.show_instancer_for_viewport
    ground = bpy.data.objects.get('Ground')
    return bool(ground and ground.hide_render)


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
        _remove_path_setup()
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


class FALLINGLEAVES_OT_ToggleHelpers(bpy.types.Operator):
    bl_idname     = 'fallingleaves.toggle_helpers'
    bl_label      = 'Hide / Show Emitter & Ground'
    bl_description = ('Hide or show the emitter plane and the ground plane. '
                      'The falling leaves and the collision keep working')
    bl_options    = {'REGISTER', 'UNDO'}

    def execute(self, context):
        emitter, ps = _get_emitter()
        ground = bpy.data.objects.get('Ground')
        pemit, _pps = _get_path_emitter()
        if not emitter and not ground:
            self.report({'WARNING'}, "Run Falling Leaves first")
            return {'CANCELLED'}
        hide = not _helpers_hidden()
        for em in (emitter, pemit):
            if em:
                em.show_instancer_for_viewport = not hide
                em.show_instancer_for_render = not hide
        if ground:
            ground.hide_render = hide
            try:
                ground.hide_set(hide)
            except RuntimeError:
                pass  # object not in the current view layer
        return {'FINISHED'}


def _base_leaves_modifier():
    emitter, ps = _get_emitter()
    if emitter and ps:
        for m in emitter.modifiers:
            if m.type == 'PARTICLE_SYSTEM' and m.particle_system == ps:
                return m
    return None


class FALLINGLEAVES_OT_ToggleBaseLeaves(bpy.types.Operator):
    bl_idname     = 'fallingleaves.toggle_base_leaves'
    bl_label      = 'Hide / Show Leaves'
    bl_description = ('Hide or show the leaves of the base Falling Leaves particle system '
                      '(viewport and render). The Leaf Path leaves are not affected')
    bl_options    = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mod = _base_leaves_modifier()
        if not mod:
            self.report({'WARNING'}, "Run Falling Leaves first")
            return {'CANCELLED'}
        show = not mod.show_viewport
        mod.show_viewport = show
        mod.show_render = show
        return {'FINISHED'}


class FALLINGLEAVES_OT_ToggleWindEmitter(bpy.types.Operator):
    bl_idname     = 'fallingleaves.toggle_wind_emitter'
    bl_label      = 'Hide / Show Wind'
    bl_description = 'Hide or show the Wind object in the viewport. The wind keeps working'
    bl_options    = {'REGISTER', 'UNDO'}

    def execute(self, context):
        wind = bpy.data.objects.get('Wind_FallingLeaves')
        if not wind:
            self.report({'WARNING'}, "No wind to hide")
            return {'CANCELLED'}
        hidden = wind.hide_get() or wind.hide_viewport
        if hidden:
            wind.hide_viewport = False
        try:
            wind.hide_set(not hidden)
        except RuntimeError:
            wind.hide_viewport = not hidden
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
    metallic: FloatProperty(
        name='Metallic', default=1.0, min=0.0, max=1.0,
        description='Metallic of the leaf material. 1.0 keeps the colors of the '
                    'image rich; 0.0 adds a white specular veil on top')
    roughness: FloatProperty(
        name='Roughness', default=1.0, min=0.0, max=1.0,
        description='Roughness of the leaf material (1.0 = fully matte)')

    def execute(self, context):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.report({'ERROR'},
                "OpenCV (cv2) could not be loaded. It is bundled with this "
                "extension: make sure the extension is enabled, then restart Blender.")
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
        leaf_coll = None                     # created with the first leaf

        for i, contour in enumerate(contours):
            hull     = cv2.convexHull(contour)
            vertices = [(p[0][0] / w - 0.5, -(p[0][1] / h - 0.5), 0.0)
                        for p in hull]
            if len(vertices) < 3:
                continue

            if leaf_coll is None:
                leaf_coll = bpy.data.collections.new(f"{base}_Leaves")
                leaf_coll['fl_leaves'] = True        # lets the bin button delete it
                (context.collection or context.scene.collection).children.link(leaf_coll)

            name = f"{base}_Leaf_{i+1}" if len(contours) > 1 else f"{base}_Leaf"
            mesh = bpy.data.meshes.new(name)
            obj  = bpy.data.objects.new(name, mesh)
            leaf_coll.objects.link(obj)

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
                tex.image = bpy.data.images.load(path, check_existing=True)
            except Exception as e:
                self.report({'WARNING'}, f"Could not load texture: {e}")

            bsdf.inputs['Metallic'].default_value  = self.metallic
            bsdf.inputs['Roughness'].default_value = self.roughness

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

        if leaf_coll is None:
            self.report({'WARNING'}, "No usable leaf found in the image.")
            return {'CANCELLED'}
        context.scene.fl_leaf_collection = leaf_coll
        self.report({'INFO'},
            f"Created {len(leaf_coll.objects)} leaf mesh(es) from "
            f"{os.path.basename(path)} in '{leaf_coll.name}'")
        return {'FINISHED'}


class FALLINGLEAVES_OT_DeleteLeafCollection(bpy.types.Operator):
    bl_idname      = 'fallingleaves.delete_leaf_collection'
    bl_label       = 'Delete Leaf Collection'
    bl_description = ('Delete the current leaf collection created by Import Leaf '
                      'from Image, with its leaves')
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        coll = context.scene.fl_leaf_collection
        return coll is not None and 'fl_leaves' in coll.keys()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        coll = context.scene.fl_leaf_collection
        if coll is None:
            return {'CANCELLED'}
        name = coll.name
        objs   = list(coll.all_objects)
        meshes = {o.data for o in objs if o.type == 'MESH' and o.data}
        mats   = {m for me in meshes for m in me.materials if m}
        imgs   = {n.image for m in mats if m.node_tree for n in m.node_tree.nodes
                  if n.bl_idname == 'ShaderNodeTexImage' and n.image}
        texs   = {md.texture for o in objs for md in o.modifiers
                  if md.type == 'DISPLACE' and md.texture}
        for o in objs:
            bpy.data.objects.remove(o, do_unlink=True)

        def drop(c):
            for child in list(c.children):
                drop(child)
            bpy.data.collections.remove(c)
        drop(coll)

        # data nobody uses any more (the pieces created by the import)
        _remove_if_unused(meshes, bpy.data.meshes)
        _remove_if_unused(mats, bpy.data.materials)
        _remove_if_unused(texs, bpy.data.textures)
        _remove_if_unused(imgs, bpy.data.images)
        self.report({'INFO'}, f"'{name}' deleted ({len(objs)} leaves).")
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


class FALLINGLEAVES_OT_AddAsset(bpy.types.Operator):
    bl_idname      = 'fallingleaves.add_asset'
    bl_label       = 'Add Asset to Scene'
    bl_description = 'Add the selected asset (object + Geometry Nodes modifier) to the scene'
    bl_options     = {'REGISTER', 'UNDO'}

    use_leaf_collection: BoolProperty(
        name='Use the current leaf collection', default=True,
        description='Plug the current leaf collection into the Collection Info '
                    'node of the asset')

    @classmethod
    def poll(cls, context):
        return context.scene.fl_asset_selection not in ('', 'NONE')

    def invoke(self, context, event):
        if context.scene.fl_leaf_collection is None:
            return self.execute(context)          # nothing to offer: no pop-up
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        coll = context.scene.fl_leaf_collection
        if coll is not None:
            layout.label(text='Use your leaves in the Collection Info node?')
            layout.label(text=coll.name, icon='OUTLINER_COLLECTION')
            layout.prop(self, 'use_leaf_collection')

    def execute(self, context):
        item = _current_item(context)
        if item is None or not os.path.isfile(item.blend):
            self.report({'ERROR'}, 'Asset file not found.')
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            objs = _append_objects(context, item.blend, tag=item.ident, only=item.obj)
        except Exception as e:
            self.report({'ERROR'}, f'Could not load the asset: {e}')
            return {'CANCELLED'}
        if not objs:
            self.report({'WARNING'}, 'This asset contains no object.')
            return {'CANCELLED'}
        leaves = context.scene.fl_leaf_collection
        if self.use_leaf_collection and leaves is not None:
            if _assign_leaf_collection(objs, leaves):
                self.report({'INFO'}, f"Asset '{item.label}' added with '{leaves.name}'.")
            else:
                self.report({'WARNING'}, f"Asset '{item.label}' added, but it has no "
                                         "Collection Info input to fill.")
            return {'FINISHED'}
        self.report({'INFO'}, f"Asset '{item.label}' added.")
        return {'FINISHED'}


class FALLINGLEAVES_OT_RemoveAsset(bpy.types.Operator):
    bl_idname      = 'fallingleaves.remove_asset'
    bl_label       = 'Remove Asset from Scene'
    bl_description = 'Remove the active asset (added from the Asset Panel) from the scene'
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and 'fl_asset' in obj.keys()

    def execute(self, context):
        obj = context.active_object
        name, mesh = obj.name, obj.data
        groups = [m.node_group for m in obj.modifiers
                  if m.type == 'NODES' and m.node_group is not None]
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and hasattr(mesh, 'users'):
            _remove_if_unused([mesh], bpy.data.meshes)
        _remove_if_unused(groups, bpy.data.node_groups)
        self.report({'INFO'}, f"'{name}' removed.")
        return {'FINISHED'}


class FALLINGLEAVES_OT_UpdateThumbnail(bpy.types.Operator):
    bl_idname      = 'fallingleaves.update_thumbnail'
    bl_label       = 'Capture Thumbnail'
    bl_description = ('Take a picture of the 3D viewport and keep it as the '
                      'thumbnail of the selected asset')
    bl_options     = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene.fl_asset_selection not in ('', 'NONE')

    def execute(self, context):
        item = _current_item(context)
        target = _thumb_target(item) if item else None
        if not target:
            self.report({'ERROR'}, 'Could not find the thumbnail folder.')
            return {'CANCELLED'}
        try:
            _capture_viewport(context, target)
        except Exception as e:
            self.report({'ERROR'}, f'Capture failed: {e}')
            return {'CANCELLED'}
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
        self.report({'INFO'}, f"Thumbnail of '{item.label}' updated.")
        return {'FINISHED'}


class FALLINGLEAVES_OT_SaveAsset(bpy.types.Operator):
    bl_idname      = 'fallingleaves.save_asset'
    bl_label       = 'Save Selection to Library'
    bl_description = ('Save the selected objects (with their Geometry Nodes modifiers) '
                      'as your own asset, with a picture of the 3D viewport')
    bl_options     = {'REGISTER'}

    asset_name: StringProperty(name='Name', default='')

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def invoke(self, context, event):
        if not self.asset_name:
            obj = context.active_object or context.selected_objects[0]
            self.asset_name = obj.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        name = _safe_name(self.asset_name)
        if not name:
            self.report({'ERROR'}, 'Please enter a name.')
            return {'CANCELLED'}
        folder = _user_dir('library', create=True)
        if not folder:
            self.report({'ERROR'}, 'Could not find the library folder.')
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')   # flush edit-mode data
            except RuntimeError:
                pass
        taken = {os.path.splitext(f)[0].lower() for f in os.listdir(folder)}
        final, n = name, 1
        while final.lower() in taken:
            n += 1
            final = f'{name}_{n}'
        blend = os.path.join(folder, final + '.blend')
        try:
            bpy.data.libraries.write(blend, set(context.selected_objects),
                                     path_remap='ABSOLUTE', fake_user=True, compress=True)
        except Exception as e:
            self.report({'ERROR'}, f'Could not save the asset: {e}')
            return {'CANCELLED'}
        context.scene.fl_asset_selection = _USER_PREFIX + final
        try:
            _capture_viewport(context, os.path.join(folder, final + '.png'))
        except Exception as e:
            self.report({'WARNING'}, f"Asset '{final}' saved, but the thumbnail failed: {e}")
            return {'FINISHED'}
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
        self.report({'INFO'}, f"Asset '{final}' saved to your library.")
        return {'FINISHED'}


class FALLINGLEAVES_OT_DeleteAsset(bpy.types.Operator):
    bl_idname      = 'fallingleaves.delete_asset'
    bl_label       = 'Delete Asset'
    bl_description = ('Delete the selected asset from your library '
                      '(a bundled asset only loses its custom thumbnail)')
    bl_options     = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        item = _current_item(context)
        return bool(item) and (not (item.builtin or item.obj) or _has_thumb(item))

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        item = _current_item(context)
        if item is None:
            return {'CANCELLED'}
        try:
            if not (item.builtin or item.obj) and os.path.isfile(item.blend):
                os.remove(item.blend)
            if _has_thumb(item):
                os.remove(item.thumb)
        except OSError as e:
            self.report({'ERROR'}, f'Could not delete: {e}')
            return {'CANCELLED'}
        if not (item.builtin or item.obj):
            context.scene.fl_asset_selection = _BUILTIN[0][0]
        self.report({'INFO'}, f"'{item.label}' removed.")
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


# Slider ranges for the wind sliders (values outside can still be typed in)
_WIND_STRENGTH_MAX = 5.0
_WIND_NOISE_MAX    = 2.0


def _wind_field_get(attr):
    def getter(self):
        wind = bpy.data.objects.get('Wind_FallingLeaves')
        return getattr(wind.field, attr) if wind and wind.field else 0.0
    return getter


def _wind_field_set(attr):
    def setter(self, value):
        wind = bpy.data.objects.get('Wind_FallingLeaves')
        if wind and wind.field:
            setattr(wind.field, attr, value)
    return setter


def _wind_objects():
    return [o for o in bpy.data.objects if o.name.startswith('Wind_FallingLeaves')]


class FALLINGLEAVES_OT_DeleteWind(bpy.types.Operator):
    bl_idname      = 'fallingleaves.delete_wind'
    bl_label       = 'Delete Wind'
    bl_description = 'Remove the Wind force field added by Falling Leaves'
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_wind_objects())

    def execute(self, context):
        for obj in _wind_objects():
            bpy.data.objects.remove(obj, do_unlink=True)
        self.report({'INFO'}, 'Wind removed')
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
                     icon='PARTICLES')
        lmod = _base_leaves_modifier()
        if lmod:
            row.operator('fallingleaves.toggle_base_leaves', text='',
                         icon='HIDE_ON' if not lmod.show_viewport else 'HIDE_OFF')
        row.operator('fallingleaves.delete', text='', icon='TRASH')


# ---------------------------------------------------------------------------
# Asset Panel
# ---------------------------------------------------------------------------

def _draw_online_assets(layout):
    pass     # replaced by the optional online block


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
        layout.template_icon_view(
            context.scene,
            'fl_asset_selection',
            show_labels=True,
            scale=5.0,
            scale_popup=5.0,
        )
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator('fallingleaves.add_asset', text='Add to Scene', icon='ADD')
        row.operator('fallingleaves.remove_asset', text='', icon='TRASH')

        row = layout.row(align=True)
        row.operator('fallingleaves.update_thumbnail', text='Capture Thumbnail',
                     icon='CAMERA_DATA')
        row.operator('fallingleaves.delete_asset', text='', icon='X')

        layout.operator('fallingleaves.save_asset', icon='ASSET_MANAGER')
        _draw_online_assets(layout)

        folder = _user_dir('library')
        if folder and os.path.isdir(folder):
            op = layout.operator('wm.path_open', text='Open Library Folder',
                                 icon='FILE_FOLDER')
            op.filepath = folder


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
        hidden = _helpers_hidden()
        layout.operator('fallingleaves.toggle_helpers',
                        text='Show Emitter & Ground' if hidden else 'Hide Emitter & Ground',
                        icon='HIDE_ON' if hidden else 'HIDE_OFF')
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
        row = layout.row(align=True)
        row.operator('fallingleaves.import_leaf_mesh',
                     text='Import Leaf from Image',
                     icon='IMAGE_DATA')
        row.operator('fallingleaves.delete_leaf_collection', text='', icon='TRASH')
        layout.prop(context.scene, 'fl_leaf_collection', text='Leaves')
        layout.separator()
        layout.operator('fallingleaves.replace_leaf_mesh',
                        text='Replace Leaf Mesh',
                        icon='FILE_REFRESH')

        emitter, ps, cfg = _leaf_settings(context)
        if cfg and cfg.instance_object:
            box = layout.box()
            box.label(text=f"Current: {cfg.instance_object.name}", icon='MESH_DATA')


# ---------------------------------------------------------------------------
# Leaf path: draw a free curve that the leaves (and the wind) follow
# ---------------------------------------------------------------------------

_PATH_NAME = 'LeafPath'


def _get_path():
    """The curve currently used as the leaf path (picked or created by the add-on)."""
    obj = getattr(bpy.context.scene, 'fl_path_object', None)
    if obj and obj.type == 'CURVE':
        return obj
    obj = bpy.data.objects.get(_PATH_NAME)
    return obj if obj and obj.type == 'CURVE' else None


def _is_addon_path(obj):
    return bool(obj.get('fl_created') or obj.name.startswith(_PATH_NAME))


def _discard_path(obj):
    """Stop using a path. Curves made by the add-on are deleted; a curve the
    user picked is kept (only its guide force is removed)."""
    _remove_path_setup()
    if obj and _is_addon_path(obj):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            bpy.data.curves.remove(data)


def _path_has_spline(obj):
    return bool(obj and obj.data.splines and
                any(len(sp.bezier_points) or len(sp.points) for sp in obj.data.splines))


def _remove_path_setup():
    """Remove the path emitter and give the base system back its guide weight
    (keeps the curve itself)."""
    pe, pps = _get_path_emitter()
    if pe:
        cfg = pps.settings if pps else None
        mesh = pe.data
        bpy.data.objects.remove(pe, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        if cfg and cfg.users == 0:
            bpy.data.particles.remove(cfg)
    _base, bps = _get_emitter()
    if bps:
        bps.settings.effector_weights.curve_guide = 1.0
    path = _get_path()
    if path and path.field:
        path.field.type = 'NONE'


def _ensure_field(obj):
    """Objects have no .field until a force field is added (Physics tab)."""
    if obj.field is None:
        with bpy.context.temp_override(object=obj, active_object=obj,
                                       selected_objects=[obj]):
            bpy.ops.object.forcefield_toggle()
    return obj.field


def _action_fcurves(action):
    """fcurves of an action, on both the legacy and the slotted-action API."""
    try:
        return action.fcurves
    except AttributeError:
        pass
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                return bag.fcurves
    return []


def _path_spin_get(self):
    _e, ps = _get_path_emitter()
    return ps.settings.angular_velocity_factor if ps else 0.0


def _path_spin_set(self, value):
    _e, ps = _get_path_emitter()
    if ps:
        cfg = ps.settings
        cfg.use_rotations = True
        # random-axis spin: unlike 'Velocity' it does not fade when the
        # leaves slide slowly along the path
        cfg.angular_velocity_mode = 'RAND'
        cfg.angular_velocity_factor = value


def _path_noise_get(self):
    path = _get_path()
    if path and path.field and path.field.type == 'GUIDE':
        return path.field.guide_kink_amplitude
    return 0.0


def _path_noise_set(self, value):
    path = _get_path()
    if path and path.field and path.field.type == 'GUIDE':
        f = path.field
        f.guide_kink_amplitude = value
        f.guide_kink_type = 'WAVE' if value > 0.0 else 'NONE'
        if value > 0.0 and f.guide_kink_frequency < 0.5:
            f.guide_kink_frequency = 2.0


def _path_guide():
    path = _get_path()
    if path and path.field and path.field.type == 'GUIDE':
        return path, path.field
    return None, None


def _emitter_base_width(emitter):
    """Width of the emitter plane at scale 1 (read from the mesh, because
    obj.dimensions is only refreshed after a depsgraph update)."""
    xs = [v.co.x for v in emitter.data.vertices]
    return (max(xs) - min(xs)) if xs else 1.0


def _update_path_clump():
    """The flow gets narrower or wider along the path: the ratio between the
    end width and the start width becomes the Curve Guide clumping amount
    (positive = narrows towards the end, negative = widens)."""
    path, f = _path_guide()
    emitter, _ps = _get_path_emitter()
    if not f or not emitter:
        return
    start = max(_emitter_base_width(emitter) * emitter.scale.x, 0.01)
    end = path.get('fl_end_width', 0.0)
    ratio = end / start
    # narrowing: 1 -> 0 ; widening: 0 -> -1 (never reaches the limit, so the
    # slider keeps having an effect for large ratios)
    f.guide_clump_amount = (1.0 - ratio) if ratio <= 1.0 else -(1.0 - 1.0 / ratio)


def _path_start_get(self):
    emitter, _ps = _get_path_emitter()
    return _emitter_base_width(emitter) * emitter.scale.x if emitter else 0.0


def _path_start_set(self, value):
    emitter, _ps = _get_path_emitter()
    if not emitter:
        return
    base = _emitter_base_width(emitter) or 1.0
    factor = max(value, 0.01) / base
    emitter.scale = (factor, factor, emitter.scale.z)
    _update_path_clump()


def _path_end_get(self):
    path, f = _path_guide()
    return path.get('fl_end_width', 0.0) if f else 0.0


def _path_end_set(self, value):
    path, f = _path_guide()
    if f:
        path['fl_end_width'] = value
        _update_path_clump()


def _path_length(path):
    """Approximate world-space length of the first spline of the path."""
    from mathutils import geometry
    sp = path.data.splines[0]
    mw = path.matrix_world
    pts = []
    if sp.type == 'BEZIER' and len(sp.bezier_points) > 1:
        bp = sp.bezier_points
        for a, b in zip(bp[:-1], bp[1:]):
            pts += geometry.interpolate_bezier(a.co, a.handle_right,
                                               b.handle_left, b.co, 16)
    else:
        pts = [p.co.xyz for p in sp.points]
    pts = [mw @ p for p in pts]
    return sum((b - a).length for a, b in zip(pts[:-1], pts[1:]))


def _fps(scene):
    return scene.render.fps / (scene.render.fps_base or 1.0)


def _path_speed_get(self):
    path, f = _path_guide()
    _e, ps = _get_path_emitter()
    if not f or not ps or ps.settings.lifetime <= 0:
        return 0.0
    seconds = ps.settings.lifetime / _fps(bpy.context.scene)
    return _path_length(path) / (seconds * max(1.0 - f.guide_free, 0.05))


def _path_speed_set(self, value):
    path, f = _path_guide()
    _e, ps = _get_path_emitter()
    if not f or not ps:
        return
    travel = _path_length(path) / max(value, 0.01) * _fps(bpy.context.scene)
    ps.settings.lifetime = travel / max(1.0 - f.guide_free, 0.05)


def _path_free_get(self):
    _path, f = _path_guide()
    return f.guide_free if f else 0.0


def _path_free_set(self, value):
    """Changing Free keeps the speed along the path constant."""
    path, f = _path_guide()
    _e, ps = _get_path_emitter()
    if not f:
        return
    speed = _path_speed_get(self)
    f.guide_free = value
    if ps and speed > 0.0:
        _path_speed_set(self, speed)


_HIDE_START_WIDTH = 0.05


def _path_hide_start_get(self):
    path, f = _path_guide()
    return bool(f and path.get('fl_hide_start', False))


def _path_hide_start_set(self, value):
    """On: the leaves are born exactly on the path (tiny entry), so none is
    visible off the curve before reaching it. The entry diameter is restored
    when switched off."""
    path, f = _path_guide()
    if not f:
        return
    if value and not path.get('fl_hide_start', False):
        path['fl_saved_start'] = _path_start_get(self)
        path['fl_hide_start'] = True
        _path_start_set(self, _HIDE_START_WIDTH)
    elif not value and path.get('fl_hide_start', False):
        path['fl_hide_start'] = False
        _path_start_set(self, path.get('fl_saved_start', 1.0))


def _path_vanish_get(self):
    _path, f = _path_guide()
    return bool(f and f.guide_free <= 0.0)


def _path_vanish_set(self, value):
    path, f = _path_guide()
    if not f:
        return
    if value:
        if f.guide_free > 0.0:
            path['fl_free'] = f.guide_free
        _path_free_set(self, 0.0)
    else:
        _path_free_set(self, path.get('fl_free', 0.4))


def _create_path_emitter(context, base, base_ps):
    """New emitter plane + particle system (copy of the base one) for the path."""
    mesh = base.data.copy()
    mesh.name = _PATH_EMITTER
    pe = bpy.data.objects.new(_PATH_EMITTER, mesh)
    context.scene.collection.objects.link(pe)
    mod = pe.modifiers.new(_PATH_PS, 'PARTICLE_SYSTEM')
    pps = mod.particle_system
    pps.name = _PATH_PS
    pps.settings = base_ps.settings.copy()
    pps.settings.name = _PATH_PS
    pps.seed = base_ps.seed + 1
    pe.show_instancer_for_viewport = base.show_instancer_for_viewport
    pe.show_instancer_for_render = base.show_instancer_for_render
    return pe, pps


class FALLINGLEAVES_OT_DrawPath(bpy.types.Operator):
    bl_idname     = 'fallingleaves.draw_path'
    bl_label      = 'Draw Path'
    bl_description = ('Draw a free curve in the viewport. The leaves will follow it. '
                      'The stroke is drawn on a plane through the 3D cursor, facing the view')
    bl_options    = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Use this button in the 3D viewport")
            return {'CANCELLED'}
        old = _get_path()
        if old:
            _discard_path(old)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        cu = bpy.data.curves.new(_PATH_NAME, 'CURVE')
        cu.dimensions = '3D'
        obj = bpy.data.objects.new(_PATH_NAME, cu)
        obj['fl_created'] = True
        context.scene.collection.objects.link(obj)
        context.scene.fl_path_object = obj
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')

        cps = context.scene.tool_settings.curve_paint_settings
        for attr, val in (('curve_type', 'BEZIER'), ('depth_mode', 'CURSOR'),
                          ('surface_plane', 'VIEW')):
            try:
                setattr(cps, attr, val)
            except (AttributeError, TypeError):
                pass
        try:
            bpy.ops.curve.draw('INVOKE_DEFAULT', wait_for_input=True)
        except (TypeError, RuntimeError):
            try:
                bpy.ops.curve.draw('INVOKE_DEFAULT')
            except RuntimeError as e:
                self.report({'WARNING'}, f"Could not start drawing: {e}")
        self.report({'INFO'}, "Draw the path, then click Apply Path")
        return {'FINISHED'}


class FALLINGLEAVES_OT_ApplyPath(bpy.types.Operator):
    bl_idname     = 'fallingleaves.apply_path'
    bl_label      = 'Apply Path'
    bl_description = ('Make the leaves flow along the drawn curve (Curve Guide force). '
                      'A separate emitter is created at the start of the curve; the '
                      'base Falling Leaves system is not modified')
    bl_options    = {'REGISTER', 'UNDO'}

    def execute(self, context):
        path = _get_path()
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if not _path_has_spline(path):
            self.report({'WARNING'}, "Draw a path first")
            return {'CANCELLED'}
        base, bps = _get_emitter()
        if not bps:
            self.report({'WARNING'}, "Run Falling Leaves first")
            return {'CANCELLED'}

        # The path gets its OWN emitter + particle system (a copy of the base
        # one); the base Falling Leaves system is left untouched and active.
        pe, pps = _get_path_emitter()
        first_time = pe is None or not path.get('fl_configured', False)
        if pe is None:
            pe, pps = _create_path_emitter(context, base, bps)
        # ... and the base system ignores the curve guide
        bps.settings.effector_weights.curve_guide = 0.0
        pps.settings.effector_weights.curve_guide = 1.0

        path.data.use_path = True
        _ensure_field(path)
        f = path.field
        f.type = 'GUIDE'
        f.falloff_power      = 0.0
        f.use_guide_path_add = False
        f.use_guide_path_weight = False
        f.use_max_distance   = False
        if first_time:
            # Default look (tuned by hand): a fine stream that follows the path
            f.strength           = 0.0
            f.guide_minimum      = 0.0
            f.guide_free         = 0.0
            f.guide_clump_shape  = -0.651
            f.guide_kink_type    = 'WAVE'
            f.guide_kink_amplitude = 0.92
            f.guide_kink_frequency = 2.1
            path['fl_configured'] = True
            path['fl_end_width'] = 0.0
            path['fl_hide_start'] = False

        # The path emitter sits at the start of the drawn curve
        sp = path.data.splines[0]
        first = sp.bezier_points[0].co if sp.type == 'BEZIER' else sp.points[0].co.xyz
        pe.location = path.matrix_world @ first
        if first_time:
            sc = context.scene
            _path_start_set(sc, 5.1)
            _path_spin_set(sc, 10.0)
            _path_speed_set(sc, 5.63)
        _update_path_clump()
        self.report({'INFO'}, "Path applied: the leaves now flow along the curve")
        return {'FINISHED'}


_FIELD_ATTRS = ('strength', 'guide_minimum', 'guide_free', 'guide_clump_shape',
                'guide_clump_amount', 'guide_kink_type', 'guide_kink_amplitude',
                'guide_kink_frequency', 'guide_kink_shape', 'guide_kink_axis',
                'falloff_power')
_PATH_PROPS = ('fl_end_width', 'fl_hide_start', 'fl_saved_start', 'fl_free')


def _snapshot_path(path):
    """All the path settings, so they can be re-applied to another curve."""
    f = path.field if path else None
    if not f or f.type != 'GUIDE':
        return None
    sc = bpy.context.scene
    return {'field': {a: getattr(f, a) for a in _FIELD_ATTRS},
            'props': {k: path[k] for k in _PATH_PROPS if k in path},
            'speed': sc.fl_path_speed, 'start': sc.fl_path_start_width,
            'spin': sc.fl_path_spin}


def _restore_path(path, snap):
    sc = bpy.context.scene
    f = path.field
    for a, v in snap['field'].items():
        setattr(f, a, v)
    for k, v in snap['props'].items():
        path[k] = v
    path['fl_configured'] = True
    _path_start_set(sc, snap['start'])
    _path_spin_set(sc, snap['spin'])
    _path_speed_set(sc, snap['speed'])
    _update_path_clump()


class FALLINGLEAVES_OT_TransferPath(bpy.types.Operator):
    bl_idname     = 'fallingleaves.transfer_path'
    bl_label      = 'Use Settings on Curve'
    bl_description = ('Make the picked curve the leaf path, with the same settings '
                      '(diameters, speed, noise, spin...) as the current path')
    bl_options    = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        src = _get_path()
        target = sc.fl_path_target
        snap = _snapshot_path(src)
        if snap is None:
            self.report({'WARNING'}, "Apply the current path first")
            return {'CANCELLED'}
        if target is None or target.type != 'CURVE':
            self.report({'WARNING'}, "Pick a curve first")
            return {'CANCELLED'}
        if target == src:
            self.report({'WARNING'}, "This curve is already the path")
            return {'CANCELLED'}
        if not _path_has_spline(target):
            self.report({'WARNING'}, "The picked curve is empty")
            return {'CANCELLED'}
        if src.field:
            src.field.type = 'NONE'
        sc.fl_path_object = target
        sc.fl_path_target = None
        if bpy.ops.fallingleaves.apply_path() != {'FINISHED'}:
            return {'CANCELLED'}
        _restore_path(target, snap)
        self.report({'INFO'}, f"'{target.name}' is now the leaf path")
        return {'FINISHED'}


class FALLINGLEAVES_OT_AddPresetPath(bpy.types.Operator):
    bl_idname     = 'fallingleaves.add_preset_path'
    bl_label      = 'Add Straight / Spiral Path'
    bl_description = ('Create a straight or spiral curve at the 3D cursor and use it as '
                      'the leaf path. The current path settings are kept')
    bl_options    = {'REGISTER', 'UNDO'}

    shape: EnumProperty(name='Shape', items=[('STRAIGHT', 'Straight', 'Straight line'),
                                             ('SIMPLE', 'Simple', 'Simple smooth curve'),
                                             ('SPIRAL', 'Spiral', 'Spiral / helix')],
                        default='SPIRAL')
    angle:      FloatProperty(name='Angle', default=0.0, min=0.0, max=math.pi / 2,
                              subtype='ANGLE',
                              description='Inclination of the curve (or of the spiral axis): '
                                          '0\u00b0 = horizontal, 45\u00b0 = diagonal, 90\u00b0 = vertical (going down)')
    length:     FloatProperty(name='Length', default=10.0, min=0.1, max=500.0,
                              unit='LENGTH', description='Length of the line / simple curve')
    bend:       FloatProperty(name='Bend', default=2.0, min=-100.0, max=100.0,
                              unit='LENGTH', description='Simple curve: sideways bend of the middle')
    radius:     FloatProperty(name='Start Radius', default=2.0, min=0.01, max=200.0,
                              unit='LENGTH')
    end_radius: FloatProperty(name='End Radius', default=2.0, min=0.01, max=200.0,
                              unit='LENGTH')
    turns:      FloatProperty(name='Turns', default=3.0, min=0.25, max=50.0)
    height:     FloatProperty(name='Height', default=8.0, min=0.1, max=500.0,
                              unit='LENGTH', description='Spiral: total length along its axis')

    reuse: BoolProperty(default=False, options={'SKIP_SAVE', 'HIDDEN'},
                        description='Internal: eye button, only toggles the visibility of the '
                                    'existing curve and brings back this panel')

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, 'shape')
        col.prop(self, 'angle', slider=True)
        if self.shape == 'STRAIGHT':
            col.prop(self, 'length')
        elif self.shape == 'SIMPLE':
            col.prop(self, 'length')
            col.prop(self, 'bend')
        else:
            col.prop(self, 'radius')
            col.prop(self, 'end_radius')
            col.prop(self, 'turns')
            col.prop(self, 'height')

    def execute(self, context):
        if self.reuse:
            # Eye button: this operator becomes the last operation again, so its
            # "Adjust Last Operation" panel is shown, with the curve's parameters.
            self.reuse = False
            path = _get_path()
            if not path:
                return {'CANCELLED'}
            hidden = path.hide_get() or path.hide_viewport
            if hidden:
                path.hide_viewport = False
            try:
                path.hide_set(not hidden)
            except RuntimeError:
                path.hide_viewport = not hidden
            return {'FINISHED'}
        base, bps = _get_emitter()
        if not bps:
            self.report({'WARNING'}, "Run Falling Leaves first")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        old = _get_path()
        snap = _snapshot_path(old) if old else None
        if old:
            _discard_path(old)

        # main direction: along +X, tilted down by 'angle' (0 = horizontal, 90 = vertical)
        d = (math.cos(self.angle), 0.0, -math.sin(self.angle))
        u = (0.0, 1.0, 0.0)                       # sideways axis (perpendicular to d)
        v = (d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2],
             d[0] * u[1] - d[1] * u[0])           # d x u
        if self.shape == 'STRAIGHT':
            pts = [(0.0, 0.0, 0.0), tuple(c * self.length for c in d)]
        elif self.shape == 'SIMPLE':
            half = self.length * 0.5
            pts = [(0.0, 0.0, 0.0),
                   tuple(d[i] * half + u[i] * self.bend for i in range(3)),
                   tuple(c * self.length for c in d)]
        else:
            n = max(int(self.turns * 8), 4)
            total = self.turns * 2.0 * math.pi
            pts = []
            for i in range(n + 1):
                k = i / n
                r = self.radius + (self.end_radius - self.radius) * k
                a = total * k
                pts.append(tuple(d[j] * self.height * k
                                 + r * (math.cos(a) * u[j] + math.sin(a) * v[j])
                                 for j in range(3)))

        cu = bpy.data.curves.new(_PATH_NAME, 'CURVE')
        cu.dimensions = '3D'
        sp = cu.splines.new('BEZIER')
        sp.bezier_points.add(len(pts) - 1)
        kind = 'VECTOR' if self.shape == 'STRAIGHT' else 'AUTO'
        for bp, co in zip(sp.bezier_points, pts):
            bp.co = co
            bp.handle_left_type = bp.handle_right_type = kind
        obj = bpy.data.objects.new(_PATH_NAME, cu)
        obj['fl_created'] = True
        obj['fl_preset'] = json.dumps({
            'shape': self.shape, 'angle': self.angle, 'length': self.length,
            'bend': self.bend, 'radius': self.radius, 'end_radius': self.end_radius,
            'turns': self.turns, 'height': self.height})
        obj.location = context.scene.cursor.location
        context.scene.collection.objects.link(obj)
        context.scene.fl_path_object = obj

        if bpy.ops.fallingleaves.apply_path() != {'FINISHED'}:
            return {'CANCELLED'}
        if snap:
            _restore_path(obj, snap)
        return {'FINISHED'}


class FALLINGLEAVES_OT_TogglePath(bpy.types.Operator):
    bl_idname     = 'fallingleaves.toggle_path'
    bl_label      = 'Hide / Show Path'
    bl_description = 'Hide or show the drawn curve in the viewport. The leaves still follow it'
    # No REGISTER / UNDO: this operator must not replace the last operation, so
    # the "Adjust Last Operation" panel of the curve stays displayed.
    bl_options    = set()

    def execute(self, context):
        path = _get_path()
        if not path:
            self.report({'WARNING'}, "No path to hide")
            return {'CANCELLED'}
        hidden = path.hide_get() or path.hide_viewport
        if hidden:
            path.hide_viewport = False
        try:
            path.hide_set(not hidden)
        except RuntimeError:
            path.hide_viewport = not hidden
        return {'FINISHED'}


class FALLINGLEAVES_OT_ClearPath(bpy.types.Operator):
    bl_idname     = 'fallingleaves.clear_path'
    bl_label      = 'Delete Path'
    bl_description = 'Remove the drawn path and restore the emitter'
    bl_options    = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        path = _get_path()
        if not path:
            self.report({'WARNING'}, "No path to delete")
            return {'CANCELLED'}
        _discard_path(path)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Ground wind: the leaves lying on the ground become real rigid bodies that a
# Wind + Turbulence field blows around (they slide, tumble and pile up)
# ---------------------------------------------------------------------------

_GW_COLLECTION = 'GroundLeaves'
_GW_WIND       = 'GroundWind'
_GW_TURB       = 'GroundTurbulence'
_GW_SPREAD     = 'GroundSpread'
_GW_FLOOR      = 'GroundWindFloor'


def _gw_target(context):
    """Ground asset the wind acts on: the picked object, else the active asset."""
    sc = context.scene
    obj = getattr(sc, 'fl_ground_target', None)
    if obj is not None and obj.name in bpy.data.objects:
        return obj
    obj = context.active_object
    if (obj is not None and obj.type == 'MESH' and
            any(m.type == 'NODES' for m in obj.modifiers)):
        return obj
    return None


def _gw_wind():
    return bpy.data.objects.get(_GW_WIND)


def _gw_leaves():
    col = bpy.data.collections.get(_GW_COLLECTION)
    return list(col.objects) if col else []


def _gw_active():
    return bool(_gw_leaves())


def _gw_fcurves(obj):
    ad = obj.animation_data
    act = ad.action if ad else None
    if act is None:
        return []
    try:
        return list(_action_fcurves(act))
    except Exception:
        pass
    out = []
    slot = getattr(ad, 'action_slot', None)
    for layer in getattr(act, 'layers', []):
        for strip in getattr(layer, 'strips', []):
            try:
                bag = strip.channelbag(slot) if slot is not None else None
            except Exception:
                bag = None
            if bag is not None:
                out.extend(bag.fcurves)
    return out


def _gw_instances(target):
    """World matrix + source mesh of every leaf the asset currently shows."""
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for oi in dg.object_instances:
        if not (oi.is_instance and oi.parent and oi.parent.original == target):
            continue
        src = oi.object.original
        if src is not None and src.type == 'MESH':
            out.append((oi.matrix_world.copy(), src))
    return out


# physics mode: the sliders act on the fields / rigid bodies, scaled so that the leaves
# behave like the real-time (Geometry Nodes) mode
_GW_K = {'strength': 8.0, 'spread': 0.03, 'turb': 0.3, 'noise': 0.0, 'damp': 6.0, 'power': 0.0, 'rscale': 1.0}
_GW_PHYS_DEFAULT = {'strength': 8.6, 'radius': 1.0, 'spread': 43.0, 'turb': 3.0,
                    'orient': 1.0, 'gravity': 0.3, 'friction': 0.6, 'keep': 0.2}


def _gw_phys_value(prop, default):
    w = _gw_wind()
    if w is not None and ('fl_' + prop) in w.keys():
        return w['fl_' + prop]
    return _GW_PHYS_DEFAULT.get(prop, default)


def _gw_apply(context=None):
    """Push the slider values to the fields, the rigid body world and the leaves."""
    ctx = context or bpy.context
    w = _gw_wind()
    if w is None:
        return
    v = {p: _gw_phys_value(p, d) for p, d in _GW_PHYS_DEFAULT.items()}
    turb, spread = bpy.data.objects.get(_GW_TURB), bpy.data.objects.get(_GW_SPREAD)
    for ob in (w, turb, spread):
        if ob is not None and ob.field:
            ob.field.falloff_power = _GW_K['power']
    if w.field:
        w.field.strength = v['strength'] * _GW_K['strength']
        w.field.distance_max = v['radius'] * _GW_K['rscale']
        w.field.noise = _GW_K['noise'] * v['orient']
    if spread is not None and spread.field:
        spread.field.strength = v['spread'] * _GW_K['spread']
        spread.field.distance_max = v['radius'] * _GW_K['rscale']
    if turb is not None and turb.field:
        turb.field.strength = v['turb'] * _GW_K['turb'] * (0.5 + 0.5 * v['orient'])
        turb.field.distance_max = v['radius'] * 1.35 * _GW_K['rscale']
    rng = bpy.data.objects.get(_GW_RANGE)
    if rng is not None:
        rng.scale = (v['radius'],) * 3
    rbw = ctx.scene.rigidbody_world
    if rbw is not None:
        rbw.effector_weights.gravity = v['gravity']
    for o in _gw_leaves():
        rb = o.rigid_body
        if rb is None:
            continue
        rb.friction = v['friction']
        rb.linear_damping = 1.0 - math.exp(-_GW_K['damp'] * v['friction'])
        rb.angular_damping = min(0.99, rb.linear_damping)
        left = o.get('fl_rand', 1.0) < v['keep']
        wanted = 'PASSIVE' if left else 'ACTIVE'
        if rb.type != wanted:
            rb.type = wanted
            rb.kinematic = False


def _gw_prop(prop, default):
    """Scene property proxied to the ground wind (modifier or physics fields)."""
    def getter(self):
        rt = _gw_rt_mod(_gw_target(bpy.context))
        if rt is not None and prop in _GW_RT_INPUT:
            return _gw_rt_get(rt, _GW_RT_INPUT[prop], default)
        return _gw_phys_value(prop, default)
    return getter


def _gw_set(prop):
    def setter(self, value):
        rt = _gw_rt_mod(_gw_target(bpy.context))
        if rt is not None:
            if prop in _GW_RT_INPUT:
                _gw_rt_set(rt, _GW_RT_INPUT[prop], value)
                if prop == 'radius':
                    rng = bpy.data.objects.get(_GW_RANGE)
                    if rng is not None:
                        rng.scale = (value,) * 3
            return
        w = _gw_wind()
        if w is None:
            return
        w['fl_' + prop] = value
        _gw_apply()
    return setter


def _gw_key_sweep(context, wind, floor_z, bounds, frames, height=-0.01):
    """Key the gust across the ground along +X (the direction it blows)."""
    (x0, y0), (x1, y1) = bounds
    margin = 0.15 * (x1 - x0)
    cy, cz = (y0 + y1) / 2, floor_z + height
    f0 = context.scene.frame_start
    if wind.animation_data:
        wind.animation_data_clear()
    wind.location = (x0 - margin, cy, cz)
    wind.keyframe_insert('location', frame=f0)
    wind.location = (x1 + margin, cy, cz)
    wind.keyframe_insert('location', frame=f0 + max(1, frames))
    wind.location = (x0 - margin, cy, cz)
    for fc in _gw_fcurves(wind):
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'


def _gw_make_floor(context, bounds, z):
    (x0, y0), (x1, y1) = bounds
    sx, sy = (x1 - x0), (y1 - y0)
    mesh = bpy.data.meshes.new(_GW_FLOOR)
    h = max(sx, sy) * 0.6 + 8.0     # leaves can be blown far: keep the ground under them
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    b = z - 5.0                     # a thick slab: thin planes let fast leaves through
    mesh.from_pydata(
        [(cx - h, cy - h, z), (cx + h, cy - h, z), (cx + h, cy + h, z), (cx - h, cy + h, z),
         (cx - h, cy - h, b), (cx + h, cy - h, b), (cx + h, cy + h, b), (cx - h, cy + h, b)],
        [], [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)])
    obj = bpy.data.objects.new(_GW_FLOOR, mesh)
    context.scene.collection.objects.link(obj)
    obj.display_type = 'WIRE'
    obj.hide_render = True
    return obj


def _gw_rigid_body(context, objs, kind):
    if not objs:
        return
    with context.temp_override(object=objs[0], active_object=objs[0],
                               selected_objects=list(objs),
                               selected_editable_objects=list(objs)):
        bpy.ops.rigidbody.objects_add(type=kind)


def _gw_clear(context):
    """Remove everything the ground wind created and show the asset again."""
    for o in _gw_leaves():
        bpy.data.objects.remove(o, do_unlink=True)
    col = bpy.data.collections.get(_GW_COLLECTION)
    if col:
        bpy.data.collections.remove(col)
    for name in (_GW_RANGE, _GW_WIND, _GW_TURB, _GW_SPREAD, _GW_FLOOR):
        o = bpy.data.objects.get(name)
        if o:
            bpy.data.objects.remove(o, do_unlink=True)
    for o in bpy.data.objects:
        m = _gw_rt_mod(o)
        if m is not None:
            o.modifiers.remove(m)
        if o.get('fl_gw_hidden'):
            o.hide_set(False)
            o.hide_render = False
            del o['fl_gw_hidden']


# --- real-time mode: Geometry Nodes simulation acting on every leaf of the asset ----

_GW_RT       = 'FL_GroundWindRT'
_GW_RANGE    = 'GroundWindRange'
_GW_RT_INPUT = {'strength': 'Strength', 'radius': 'Radius', 'spread': 'Spread',
                'turb': 'Turbulence', 'friction': 'Friction', 'keep': 'Leaves Left Behind',
                'gravity': 'Gravity', 'orient': 'Orientation'}


def _gw_rt_group():
    """Simulation zone: the gust sweeps the leaves like a vehicle passing over them.
    Each leaf keeps its own velocity and tilt (stored on the instance): it is pushed
    ahead of the gust, flung sideways at the front, pulled back in the wake, tilts and
    flips with the wind strength, then falls back flat and stops by friction."""
    ng = bpy.data.node_groups.get(_GW_RT)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(_GW_RT, 'GeometryNodeTree')
    it = ng.interface

    def sock(name, st, io='INPUT', default=None, lo=None, hi=None):
        s_ = it.new_socket(name, in_out=io, socket_type=st)
        if default is not None:
            s_.default_value = default
        if lo is not None:
            s_.min_value = lo
        if hi is not None:
            s_.max_value = hi
    sock('Geometry', 'NodeSocketGeometry')
    sock('Geometry', 'NodeSocketGeometry', io='OUTPUT')
    sock('Wind', 'NodeSocketObject')
    sock('Strength', 'NodeSocketFloat', default=8.6, lo=0.0, hi=1000.0)
    sock('Radius', 'NodeSocketFloat', default=1.0, lo=0.01, hi=1000.0)
    sock('Spread', 'NodeSocketFloat', default=43.0, lo=-1000.0, hi=1000.0)
    sock('Turbulence', 'NodeSocketFloat', default=3.0, lo=0.0, hi=1000.0)
    sock('Orientation', 'NodeSocketFloat', default=1.0, lo=0.0, hi=5.0)
    sock('Friction', 'NodeSocketFloat', default=0.6, lo=0.0, hi=10.0)
    sock('Gravity', 'NodeSocketFloat', default=0.3, lo=0.0, hi=10.0)
    sock('Leaves Left Behind', 'NodeSocketFloat', default=0.2, lo=0.0, hi=1.0)
    sock('Seed', 'NodeSocketInt', default=0)

    N, L = ng.nodes, ng.links.new
    gin, gout = N.new('NodeGroupInput'), N.new('NodeGroupOutput')
    sim_in, sim_out = N.new('GeometryNodeSimulationInput'), N.new('GeometryNodeSimulationOutput')
    sim_in.pair_with_output(sim_out)
    dt = sim_in.outputs['Delta Time']

    def math(op, a=None, b=None, clamp=False):
        n = N.new('ShaderNodeMath'); n.operation = op; n.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                L(v, n.inputs[i])
        return n.outputs[0]

    def vmath(op, a=None, b=None, scale=None):
        n = N.new('ShaderNodeVectorMath'); n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (tuple, list)):
                n.inputs[i].default_value = v
            else:
                L(v, n.inputs[i])
        if scale is not None:
            if isinstance(scale, (int, float)):
                n.inputs['Scale'].default_value = scale
            else:
                L(scale, n.inputs['Scale'])
        return n.outputs['Value'] if op in ('LENGTH', 'DISTANCE', 'DOT_PRODUCT') else n.outputs['Vector']

    def sepxyz(vec):
        n = N.new('ShaderNodeSeparateXYZ'); L(vec, n.inputs[0]); return n

    def combine(x=None, y=None, z=None):
        n = N.new('ShaderNodeCombineXYZ')
        for name, v in (('X', x), ('Y', y), ('Z', z)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[name].default_value = v
            else:
                L(v, n.inputs[name])
        return n.outputs[0]

    def flat(vec):
        s_ = sepxyz(vec)
        return combine(s_.outputs['X'], s_.outputs['Y'], 0.0)

    def named(name, kind):
        n = N.new('GeometryNodeInputNamedAttribute'); n.data_type = kind
        n.inputs['Name'].default_value = name
        return n.outputs[0]

    def store(geo, name, value, kind='FLOAT_VECTOR'):
        n = N.new('GeometryNodeStoreNamedAttribute'); n.data_type = kind
        n.domain = 'INSTANCE'; n.inputs['Name'].default_value = name
        L(geo, n.inputs['Geometry']); L(value, n.inputs['Value'])
        return n.outputs[0]

    def rand(kind, seed, lo=None, hi=None, prob=None):
        n = N.new('FunctionNodeRandomValue'); n.data_type = kind
        if lo is not None:
            n.inputs['Min'].default_value = lo
        if hi is not None:
            n.inputs['Max'].default_value = hi
        if prob is not None:
            L(prob, n.inputs['Probability'])
        L(seed, n.inputs['Seed'])
        return n.outputs[0]

    # ---- gust geometry (relative to the object that carries the modifier)
    oi = N.new('GeometryNodeObjectInfo'); oi.transform_space = 'RELATIVE'
    L(gin.outputs['Wind'], oi.inputs['Object'])
    pos = N.new('GeometryNodeInputPosition').outputs[0]
    rel = flat(vmath('SUBTRACT', pos, oi.outputs['Location']))
    dist = vmath('LENGTH', rel)
    t = math('SUBTRACT', 1.0, math('DIVIDE', dist, gin.outputs['Radius']), clamp=True)
    w = math('MULTIPLY', t, math('SUBTRACT', 3.0, math('MULTIPLY', t, 2.0)))      # smoothstep
    w = math('MULTIPLY', w, t)
    rv = N.new('FunctionNodeRotateVector'); rv.inputs['Vector'].default_value = (0.0, 0.0, 1.0)
    L(oi.outputs['Rotation'], rv.inputs['Rotation'])
    wdir = vmath('NORMALIZE', flat(rv.outputs[0]))
    along = vmath('DOT_PRODUCT', rel, wdir)
    front = math('DIVIDE', along, gin.outputs['Radius'])           # +1 ahead of the gust, -1 in its wake
    front = math('MAXIMUM', math('MINIMUM', front, 1.0), -1.0)
    perp = vmath('NORMALIZE', vmath('SUBTRACT', rel, vmath('SCALE', wdir, scale=along)))

    # ---- per-leaf randomness
    seed = gin.outputs['Seed']
    react = rand('FLOAT', seed, 0.6, 1.4)
    movable = rand('BOOLEAN', math('ADD', seed, 7), prob=math('SUBTRACT', 1.0, gin.outputs['Leaves Left Behind']))
    spin_dir = rand('FLOAT', math('ADD', seed, 13), -1.0, 1.0)
    gain = math('MULTIPLY', math('MULTIPLY', math('MULTIPLY', w, react), movable), 3.0)

    # ---- smooth, coherent turbulence (space + time), not white noise
    secs = N.new('GeometryNodeInputSceneTime').outputs['Seconds']
    nz = N.new('ShaderNodeTexNoise'); nz.noise_dimensions = '4D'
    L(pos, nz.inputs['Vector']); L(math('MULTIPLY', secs, 0.8), nz.inputs['W'])
    nz.inputs['Scale'].default_value = 1.6; nz.inputs['Detail'].default_value = 1.0
    cn = vmath('SUBTRACT', nz.outputs['Color'], (0.5, 0.5, 0.5))
    cn = vmath('SCALE', cn, scale=2.0)                                  # -1..1, smooth
    cs = sepxyz(cn)

    push = math('MULTIPLY', gin.outputs['Strength'], math('ADD', 0.6, math('MULTIPLY', front, 0.4)))
    acc = vmath('SCALE', wdir, scale=push)                                # pushed ahead of the gust
    acc = vmath('ADD', acc, vmath('SCALE', perp,
                scale=math('MULTIPLY', math('MULTIPLY', gin.outputs['Spread'], 0.15), front)))
    swirl = combine(cs.outputs['X'], cs.outputs['Y'],
                    math('MULTIPLY', math('MAXIMUM', cs.outputs['Z'], 0.0), 25.0))   # coherent flutter + lift
    acc = vmath('ADD', acc, vmath('SCALE', swirl, scale=math('MULTIPLY', gin.outputs['Turbulence'], 0.35)))
    acc = vmath('SCALE', acc, scale=gain)
    acc = vmath('ADD', acc, combine(0.0, 0.0, math('MULTIPLY', gin.outputs['Gravity'], -9.81)))

    # ---- velocity and tilt, stored on every leaf
    decay = math('POWER', 2.718281828, math('MULTIPLY', math('MULTIPLY', gin.outputs['Friction'], dt), -4.0))
    vel = vmath('SCALE', vmath('ADD', named('fl_vel', 'FLOAT_VECTOR'), vmath('SCALE', acc, scale=dt)), scale=decay)
    vlen = vmath('LENGTH', vel)
    lift = vmath('CROSS_PRODUCT', vel, (0.0, 0.0, 1.0))                   # lifts the leading edge
    lift = vmath('SCALE', lift, scale=math('MINIMUM', math('MULTIPLY', gin.outputs['Orientation'], 0.3),
                                         math('DIVIDE', 1.2, math('ADD', vlen, 0.001))))
    amp = math('MULTIPLY', math('MULTIPLY', math('MINIMUM', math('MULTIPLY', gin.outputs['Strength'], 0.1), 1.0),
                                gin.outputs['Orientation']), math('MULTIPLY', math('MULTIPLY', w, movable), 0.8))
    flutter = vmath('SCALE', combine(cs.outputs['Y'], math('MULTIPLY', cs.outputs['X'], -1.0), 0.0), scale=amp)
    target = vmath('ADD', lift, flutter)
    tilt_old = named('fl_tilt', 'FLOAT_VECTOR')
    follow = math('SUBTRACT', 1.0, math('POWER', 2.718281828, math('MULTIPLY', dt, -7.0)))
    dtilt = vmath('SCALE', vmath('SUBTRACT', target, tilt_old), scale=follow)

    g = sim_in.outputs[1]
    g = store(g, 'fl_dtilt', dtilt)
    g = store(g, 'fl_tilt', vmath('ADD', named('fl_tilt', 'FLOAT_VECTOR'), named('fl_dtilt', 'FLOAT_VECTOR')))
    g = store(g, 'fl_vel', vel)

    tr = N.new('GeometryNodeTranslateInstances')
    tr.inputs['Local Space'].default_value = False
    L(g, tr.inputs['Instances'])
    L(vmath('SCALE', named('fl_vel', 'FLOAT_VECTOR'), scale=dt), tr.inputs['Translation'])

    # ground: lift back what went below, cancel the downward speed
    pz = sepxyz(N.new('GeometryNodeInputPosition').outputs[0]).outputs['Z']
    below = math('MAXIMUM', math('SUBTRACT', named('fl_rest', 'FLOAT'), pz), 0.0)
    tr2 = N.new('GeometryNodeTranslateInstances')
    tr2.inputs['Local Space'].default_value = False
    L(tr.outputs[0], tr2.inputs['Instances']); L(combine(0.0, 0.0, below), tr2.inputs['Translation'])
    vs = sepxyz(named('fl_vel', 'FLOAT_VECTOR'))
    pz2 = sepxyz(N.new('GeometryNodeInputPosition').outputs[0]).outputs['Z']
    grounded = math('LESS_THAN', math('SUBTRACT', pz2, named('fl_rest', 'FLOAT')), 0.0005)
    vz = math('ADD', vs.outputs['Z'], math('MULTIPLY', grounded,
              math('MAXIMUM', math('MULTIPLY', vs.outputs['Z'], -1.0), 0.0)))
    g2 = store(tr2.outputs[0], 'fl_vel', combine(vs.outputs['X'], vs.outputs['Y'], vz))

    # orientation is set from absolute values (no drift): initial rotation, then the yaw
    # picked up while sliding and the current tilt
    yaw = math('ADD', named('fl_yaw', 'FLOAT'),
               math('MULTIPLY', math('MULTIPLY', vmath('LENGTH', named('fl_vel', 'FLOAT_VECTOR')), spin_dir),
                    math('MULTIPLY', dt, 4.0)))
    g2 = store(g2, 'fl_yaw', yaw, 'FLOAT')
    tl = sepxyz(named('fl_tilt', 'FLOAT_VECTOR'))
    e2r = N.new('FunctionNodeEulerToRotation')
    L(combine(tl.outputs['X'], tl.outputs['Y'], named('fl_yaw', 'FLOAT')), e2r.inputs[0])
    rr = N.new('FunctionNodeRotateRotation'); rr.rotation_space = 'GLOBAL'
    L(named('fl_r0', 'QUATERNION'), rr.inputs['Rotation']); L(e2r.outputs[0], rr.inputs['Rotate By'])
    ct = N.new('FunctionNodeCombineTransform')
    L(N.new('GeometryNodeInputPosition').outputs[0], ct.inputs['Translation'])
    L(rr.outputs[0], ct.inputs['Rotation'])
    L(named('fl_s0', 'FLOAT_VECTOR'), ct.inputs['Scale'])
    sit = N.new('GeometryNodeSetInstanceTransform')
    L(g2, sit.inputs['Instances']); L(ct.outputs[0], sit.inputs['Transform'])
    g3 = sit.outputs[0]

    # height of every leaf at rest, remembered before the simulation starts
    rest = store(gin.outputs['Geometry'], 'fl_rest',
                 sepxyz(N.new('GeometryNodeInputPosition').outputs[0]).outputs['Z'], 'FLOAT')
    rest = store(rest, 'fl_r0', N.new('GeometryNodeInputInstanceRotation').outputs[0], 'QUATERNION')
    rest = store(rest, 'fl_s0', N.new('GeometryNodeInputInstanceScale').outputs[0])
    L(rest, sim_in.inputs[0])
    L(g3, sim_out.inputs[1])
    L(sim_out.outputs[0], gout.inputs['Geometry'])
    return ng


def _gw_rt_mod(target):
    if target is None:
        return None
    for m in target.modifiers:
        if m.type == 'NODES' and m.node_group is not None and m.node_group.name.startswith(_GW_RT):
            return m
    return None


def _gw_rt_ident(mod, name):
    for item in mod.node_group.interface.items_tree:
        if getattr(item, 'in_out', '') == 'INPUT' and item.name == name:
            return item.identifier
    return None


def _gw_rt_get(mod, name, default):
    ident = _gw_rt_ident(mod, name)
    props = getattr(mod, 'properties', None)
    group = getattr(props, 'inputs', None) if props is not None else None
    sock = getattr(group, ident, None) if group is not None else None
    if sock is not None and hasattr(sock, 'value'):
        return sock.value
    try:
        return mod[ident]
    except Exception:
        return default


def _gw_rt_set(mod, name, value):
    _set_modifier_input(mod, _gw_rt_ident(mod, name), value)


def _gw_setup(context, target, animate, frames):
    """Gust empty + real-time modifier on the ground asset. Returns the gust or None."""
    sc = context.scene
    _gw_clear(context)
    insts = _gw_instances(target)
    if not insts:
        return None
    sc.fl_ground_target = target
    xs = [m.translation.x for m, _ in insts]
    ys = [m.translation.y for m, _ in insts]
    zs = [m.translation.z for m, _ in insts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    half = max((max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2, 0.25)
    bounds = ((cx - half, cy - half), (cx + half, cy + half))
    z = sum(zs) / len(zs)
    radius = 1.0

    wind = bpy.data.objects.new(_GW_WIND, None)
    sc.collection.objects.link(wind)
    wind.empty_display_type = 'SINGLE_ARROW'
    wind.rotation_euler = (0.0, math.radians(90.0), 0.0)   # +Z -> +X
    rng = bpy.data.objects.new(_GW_RANGE, None)
    sc.collection.objects.link(rng)
    rng.empty_display_type = 'SPHERE'
    rng.parent = wind
    rng.scale = (radius,) * 3
    if animate:
        _gw_key_sweep(context, wind, z, bounds, frames)
    else:
        wind.location = (cx, cy, z)

    mod = target.modifiers.new(_GW_RT, 'NODES')
    mod.node_group = _gw_rt_group()
    _gw_rt_set(mod, 'Wind', wind)
    return wind


class FALLINGLEAVES_OT_AddGroundWindRT(bpy.types.Operator):
    bl_idname      = 'fallingleaves.add_ground_wind_rt'
    bl_label       = 'Add Real-time Ground Wind'
    bl_description = ('Blow every leaf of the ground asset in real time (Geometry Nodes '
                      'simulation): the leaves slide, spin and stop by friction')
    bl_options     = {'REGISTER', 'UNDO'}

    animate: BoolProperty(name='Sweep Across the Ground', default=True,
                          description='Key the gust so it crosses the ground')
    frames: IntProperty(name='Duration (frames)', default=120, min=1, max=100000)

    @classmethod
    def poll(cls, context):
        return _gw_target(context) is not None

    def execute(self, context):
        sc = context.scene
        target = _gw_target(context)
        if target is None:
            self.report({'WARNING'}, "Select the ground asset first")
            return {'CANCELLED'}
        if _gw_setup(context, target, self.animate, self.frames) is None:
            self.report({'WARNING'}, "This asset shows no leaves: add a leaf collection "
                                     "(Import Leaf) first")
            return {'CANCELLED'}
        sc.frame_set(sc.frame_start)
        return {'FINISHED'}


class FALLINGLEAVES_OT_RemoveGroundWind(bpy.types.Operator):
    bl_idname      = 'fallingleaves.remove_ground_wind'
    bl_label       = 'Remove Ground Wind'
    bl_description = 'Remove the simulated leaves and the fields, and show the asset again'
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _gw_clear(context)
        return {'FINISHED'}


class FALLINGLEAVES_OT_ToggleGroundWind(bpy.types.Operator):
    bl_idname      = 'fallingleaves.toggle_ground_wind'
    bl_label       = 'Show / Hide Ground Wind Gust'
    bl_description = 'Show or hide the wind and turbulence emitters in the viewport'
    bl_options     = set()

    def execute(self, context):
        objs = [bpy.data.objects.get(n) for n in (_GW_WIND, _GW_RANGE, _GW_TURB, _GW_SPREAD, _GW_FLOOR)]
        objs = [o for o in objs if o]
        if not objs:
            return {'CANCELLED'}
        hide = not objs[0].hide_get()
        for o in objs:
            o.hide_set(hide)
        return {'FINISHED'}


class FALLINGLEAVES_PT_GroundWind(bpy.types.Panel):
    bl_label      = 'Ground Wind'
    bl_idname     = 'FALLINGLEAVES_PT_ground_wind'
    bl_space_type = 'VIEW_3D'
    bl_region_type= 'UI'
    bl_category   = 'Falling Leaves'
    bl_parent_id  = 'FALLINGLEAVES_PT_wind'
    bl_options    = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        sc = context.scene
        layout.prop(sc, 'fl_ground_target', text='Ground')
        target = _gw_target(context)
        ready = _gw_rt_mod(target) is not None and not _gw_active()
        row = layout.row(align=True)
        if not ready:
            row.operator('fallingleaves.add_ground_wind_rt', icon='FORCE_WIND')
            if target is None:
                layout.label(text="Select your ground asset", icon='INFO')
            return
        row.operator('fallingleaves.add_ground_wind_rt', text='Rebuild', icon='FILE_REFRESH')
        wind = _gw_wind()
        if wind is not None:
            row.operator('fallingleaves.toggle_ground_wind', text='',
                         icon='HIDE_ON' if wind.hide_get() else 'HIDE_OFF')
        row.operator('fallingleaves.remove_ground_wind', text='', icon='TRASH')
        col = layout.column(align=True)
        col.prop(sc, 'fl_gw_strength', text='Wind Strength')
        col.prop(sc, 'fl_gw_radius', text='Wind Radius')
        col.prop(sc, 'fl_gw_spread', text='Spread')
        col.prop(sc, 'fl_gw_turb', text='Turbulence')
        col.prop(sc, 'fl_gw_orient', text='Orientation')
        col.prop(sc, 'fl_gw_gravity', text='Gravity')
        col.prop(sc, 'fl_gw_friction', text='Friction')
        col.prop(sc, 'fl_gw_keep', text='Leaves Left Behind', slider=True)
        layout.label(text="Play the timeline: it runs in real time", icon='INFO')


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
        row = layout.row(align=True)
        row.operator('fallingleaves.add_wind', icon='FORCE_WIND')
        wind = bpy.data.objects.get('Wind_FallingLeaves')
        if wind:
            whidden = wind.hide_get() or wind.hide_viewport
            row.operator('fallingleaves.toggle_wind_emitter', text='',
                         icon='HIDE_ON' if whidden else 'HIDE_OFF')
        row.operator('fallingleaves.delete_wind', text='', icon='TRASH')

        if wind and wind.field:
            box = layout.box()
            box.label(text="Wind Settings:", icon='FORCE_WIND')
            col = box.column(align=True)
            col.prop(context.scene, 'fl_wind_strength', text="Strength", slider=True)
            col.prop(context.scene, 'fl_wind_noise',    text="Noise",    slider=True)

        layout.separator()
        layout.operator('fallingleaves.bake', icon='RENDER_ANIMATION')


class FALLINGLEAVES_PT_Path(bpy.types.Panel):
    bl_label      = 'Leaf Path'
    bl_idname     = 'FALLINGLEAVES_PT_path'
    bl_space_type = 'VIEW_3D'
    bl_region_type= 'UI'
    bl_category   = 'Falling Leaves'
    bl_parent_id  = 'FALLINGLEAVES_PT_main'
    bl_order      = 5
    bl_options    = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        box = layout
        path = _get_path()
        row = box.row(align=True)
        row.operator('fallingleaves.draw_path', text='Draw Path', icon='GREASEPENCIL')
        if path:
            hidden = path.hide_get() or path.hide_viewport
            eye = 'HIDE_ON' if hidden else 'HIDE_OFF'
            preset = path.get('fl_preset')
            if preset:
                # same eye, but it re-opens the curve's "Adjust Last Operation" panel
                op = row.operator('fallingleaves.add_preset_path', text='', icon=eye)
                op.reuse = True
                try:
                    for k, v in json.loads(preset).items():
                        setattr(op, k, v)
                except (ValueError, AttributeError, TypeError):
                    pass
            else:
                row.operator('fallingleaves.toggle_path', text='', icon=eye)
        row.operator('fallingleaves.clear_path', text='', icon='TRASH')
        row = box.row(align=True)
        op = row.operator('fallingleaves.add_preset_path', text='Straight', icon='IPO_LINEAR')
        op.shape = 'STRAIGHT'
        op.angle = 0.0
        op = row.operator('fallingleaves.add_preset_path', text='Simple', icon='CURVE_BEZCURVE')
        op.shape = 'SIMPLE'
        op.angle = math.radians(30.0)
        op = row.operator('fallingleaves.add_preset_path', text='Spiral', icon='FORCE_VORTEX')
        op.shape = 'SPIRAL'
        op.angle = math.pi / 2
        guide = bool(path and path.field and path.field.type == 'GUIDE')
        if _path_has_spline(path):
            box.operator('fallingleaves.apply_path',
                         text='Update Path' if guide else 'Apply Path',
                         icon='CHECKMARK')
            if guide:
                col = box.column(align=True)
                col.prop(path.field, 'strength', text="Strength")
                col.prop(path.field, 'guide_minimum', text="Minimum Distance")
                col.prop(path.field, 'guide_clump_shape', text="Shape", slider=True)
                col = box.column(align=True)
                col.label(text="Flow Diameter:")
                row = col.row()
                row.active = not context.scene.fl_path_hide_start
                row.prop(context.scene, 'fl_path_start_width', text="Entry")
                col.prop(context.scene, 'fl_path_end_width', text="Exit")
                col = box.column(align=True)
                col.label(text="Flow Speed:")
                col.prop(context.scene, 'fl_path_speed', text="Speed")
                col.prop(context.scene, 'fl_path_free', text="Free", slider=True)
                col.prop(context.scene, 'fl_path_hide_start', text="Disappear at Beginning of Path")
                col.prop(context.scene, 'fl_path_vanish', text="Disappear at End of Path")
                col = box.column(align=True)
                col.prop(context.scene, 'fl_path_spin', text="Spin", slider=True)
                col.prop(context.scene, 'fl_path_noise', text="Noise", slider=True)
                if path.field.guide_kink_type != 'NONE':
                    col.prop(path.field, 'guide_kink_frequency', text="Noise Frequency")
                col = box.column(align=True)
                col.label(text="Use these settings on another curve:")
                row = col.row(align=True)
                row.prop(context.scene, 'fl_path_target', text='')
                row.operator('fallingleaves.transfer_path', text='Apply', icon='EYEDROPPER')



# <ONLINE>
# ---------------------------------------------------------------------------
# Optional online asset pack (Hugging Face). Only in the full version:
# the Blender Extensions build strips this whole block.
# ---------------------------------------------------------------------------
import json
import posixpath
import threading
import urllib.parse
import urllib.request

_ONLINE = True
_HF_REPO = 'GBissieres/falling_leaves_assets'
_HF_API  = f'https://huggingface.co/api/datasets/{_HF_REPO}/tree/main/assets?recursive=true'
_HF_FILE = f'https://huggingface.co/datasets/{_HF_REPO}/resolve/main/'
_IMG_EXT = ('.png', '.jpg', '.jpeg')
_dl = {'running': False, 'error': None, 'current': '', 'index': 0, 'count': 0,
       'done': 0, 'total': 0}


def _http(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={'User-Agent': 'FallingLeaves-Blender'}),
        timeout=30)


def _download_worker(dest_dir):
    tmp = None
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with _http(_HF_API) as r:
            tree = json.loads(r.read().decode('utf-8'))
        files = {e['path']: e for e in tree if e.get('type') == 'file'}
        wanted = []
        for path in sorted(files):
            low = path.lower()
            if '/menu_icons/' in low:         # the old panel icons: not assets
                continue
            # the .blend packs + every image, also from sub-folders such as
            # assets/icons/ (the visuals of the assets)
            if low.endswith('.blend') or low.endswith(_IMG_EXT):
                wanted.append(path)
        if not any(p.lower().endswith('.blend') for p in wanted):
            raise IOError('No .blend asset found in the repository')
        _dl['count'] = len(wanted)
        for i, path in enumerate(wanted, 1):
            entry = files[path]
            size = (entry.get('lfs') or {}).get('size') or entry.get('size') or 0
            target = os.path.join(dest_dir, posixpath.basename(path))
            _dl.update(current=posixpath.basename(path), index=i, done=0, total=size)
            if size and os.path.isfile(target) and os.path.getsize(target) == size:
                continue                      # already up to date
            tmp = target + '.part'
            with _http(_HF_FILE + urllib.parse.quote(path)) as r, open(tmp, 'wb') as f:
                _dl['total'] = int(r.headers.get('Content-Length') or size or 0)
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    _dl['done'] += len(chunk)
            if _dl['total'] and os.path.getsize(tmp) != _dl['total']:
                raise IOError(f'Incomplete download: {path}')
            os.replace(tmp, target)
            tmp = None
    except Exception as e:
        _dl['error'] = str(e)
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    finally:
        _dl['running'] = False


class FALLINGLEAVES_OT_DownloadAssets(bpy.types.Operator):
    bl_idname      = 'fallingleaves.download_assets'
    bl_label       = 'Download Assets'
    bl_description = ('Download the optional assets (with their thumbnails) from the '
                      'Hugging Face repository. They are added after the bundled ones')

    _timer = None

    def execute(self, context):
        if _dl['running']:
            return {'CANCELLED'}
        if not getattr(bpy.app, 'online_access', True):
            self.report({'ERROR'}, "Enable 'Allow Online Access' in "
                                   "Preferences > System > Network")
            return {'CANCELLED'}
        dest = _user_dir(_DOWNLOADED_DIR, create=True)
        if not dest:
            self.report({'ERROR'}, 'Could not find the add-on user folder.')
            return {'CANCELLED'}
        _dl.update(running=True, error=None, current='', index=0, count=0, done=0, total=0)
        threading.Thread(target=_download_worker, args=(dest,), daemon=True).start()
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
        if _dl['running']:
            return {'PASS_THROUGH'}
        context.window_manager.event_timer_remove(self._timer)
        if _dl['error']:
            self.report({'ERROR'}, f"Download failed: {_dl['error']}")
            return {'CANCELLED'}
        self.report({'INFO'}, 'Assets downloaded: they are now in the Asset Panel.')
        return {'FINISHED'}


def _downloaded_count():
    d = _user_dir(_DOWNLOADED_DIR)
    if d and os.path.isdir(d):
        return len([f for f in os.listdir(d) if f.lower().endswith('.blend')])
    return 0


def _draw_download_status(layout):
    if _dl['running']:
        mb = _dl['done'] / 1048576
        total = _dl['total'] / 1048576
        txt = f"Downloading {_dl['current']} ({_dl['index']}/{_dl['count']})"
        if total:
            txt += f": {mb:.0f} / {total:.0f} MB"
        layout.label(text=txt, icon='SORTTIME')
    else:
        if _dl['error']:
            layout.label(text=f"Error: {_dl['error']}", icon='CANCEL')
        n = _downloaded_count()
        layout.operator('fallingleaves.download_assets',
                        text='Update Online Assets' if n else 'Download Assets',
                        icon='IMPORT')


def _draw_online_assets(layout):
    n = _downloaded_count()
    box = layout.box()
    box.label(text=f"Online assets: {n} downloaded" if n else "Online assets (optional)",
              icon='URL')
    _draw_download_status(box)


class FALLINGLEAVES_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        n = _downloaded_count()
        if n:
            box.label(text=f'{n} online asset(s) downloaded', icon='CHECKMARK')
        else:
            box.label(text='No online asset downloaded (the 3 bundled assets always work)',
                      icon='INFO')
        _draw_download_status(box)
        box.label(text='Connects to the internet only when you click the button.')
        d = _user_dir(_DOWNLOADED_DIR)
        if d and os.path.isdir(d):
            op = box.operator('wm.path_open', text='Open assets folder', icon='FILE_FOLDER')
            op.filepath = d


_ONLINE_CLASSES = (FALLINGLEAVES_OT_DownloadAssets, FALLINGLEAVES_Preferences)
# </ONLINE>


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

classes = (
    FALLINGLEAVES_OT_Run,
    FALLINGLEAVES_OT_Delete,
    FALLINGLEAVES_OT_ToggleHelpers,
    FALLINGLEAVES_OT_ToggleBaseLeaves,
    FALLINGLEAVES_OT_ToggleWindEmitter,
    FALLINGLEAVES_OT_DrawPath,
    FALLINGLEAVES_OT_ApplyPath,
    FALLINGLEAVES_OT_ClearPath,
    FALLINGLEAVES_OT_TogglePath,
    FALLINGLEAVES_OT_TransferPath,
    FALLINGLEAVES_OT_AddPresetPath,
    FALLINGLEAVES_OT_ImportLeafMesh,
    FALLINGLEAVES_OT_ReplaceLeafMesh,
    FALLINGLEAVES_OT_AddAsset,
    FALLINGLEAVES_OT_RemoveAsset,
    FALLINGLEAVES_OT_DeleteLeafCollection,
    FALLINGLEAVES_OT_UpdateThumbnail,
    FALLINGLEAVES_OT_SaveAsset,
    FALLINGLEAVES_OT_DeleteAsset,
    FALLINGLEAVES_OT_AddWind,
    FALLINGLEAVES_OT_DeleteWind,
    FALLINGLEAVES_OT_BakeAnimation,
    FALLINGLEAVES_OT_AddGroundWindRT,
    FALLINGLEAVES_OT_RemoveGroundWind,
    FALLINGLEAVES_OT_ToggleGroundWind,
    FALLINGLEAVES_OT_ExportSettings,
    FALLINGLEAVES_OT_ApplySettings,
    FALLINGLEAVES_OT_ResetSettings,
    FALLINGLEAVES_PT_Main,
    FALLINGLEAVES_PT_AssetPanel,
    FALLINGLEAVES_PT_Settings,
    FALLINGLEAVES_PT_LeafMesh,
    FALLINGLEAVES_PT_Wind,
    FALLINGLEAVES_PT_GroundWind,
    FALLINGLEAVES_PT_Path,
)


def register():
    global _icons
    _icons = bpy.utils.previews.new()

    # EnumProperty pour la grille d'icônes de l'Asset Panel
    bpy.types.Scene.fl_asset_selection = EnumProperty(
        name='Asset',
        description='Asset to add to the scene',
        items=sna_asset_enum_items,
    )

    bpy.types.Scene.fl_leaf_collection = PointerProperty(
        name='Leaves', type=bpy.types.Collection,
        description='Current leaf collection: used by the Asset Panel and '
                    'deleted by the bin button')

    bpy.types.Scene.fl_wind_strength = FloatProperty(
        name='Strength', description='Wind strength',
        min=-1000.0, max=1000.0, soft_min=0.0, soft_max=_WIND_STRENGTH_MAX,
        step=5, precision=2,
        get=_wind_field_get('strength'), set=_wind_field_set('strength'))
    bpy.types.Scene.fl_wind_noise = FloatProperty(
        name='Noise', description='Wind noise amount',
        min=0.0, max=1000.0, soft_min=0.0, soft_max=_WIND_NOISE_MAX,
        step=5, precision=2,
        get=_wind_field_get('noise'), set=_wind_field_set('noise'))

    bpy.types.Scene.fl_path_spin = FloatProperty(
        name='Spin', description='How fast the leaves spin on themselves',
        min=0.0, max=100.0, soft_min=0.0, soft_max=10.0, precision=2,
        get=_path_spin_get, set=_path_spin_set)
    bpy.types.Scene.fl_path_noise = FloatProperty(
        name='Noise', description='Waviness of the flow around the path',
        min=0.0, max=100.0, soft_min=0.0, soft_max=3.0, precision=2,
        get=_path_noise_get, set=_path_noise_set)

    bpy.types.Scene.fl_path_start_width = FloatProperty(
        name='Entry Diameter', description='Diameter of the flow where the leaves enter the path '
                                        '(size of the emitter plane)',
        min=0.01, max=1000.0, soft_min=0.01, soft_max=20.0, unit='LENGTH', precision=2,
        get=_path_start_get, set=_path_start_set)
    bpy.types.Scene.fl_path_end_width = FloatProperty(
        name='Exit Diameter', description='Diameter of the flow where the leaves leave the path. '
                                      'Smaller than Entry Diameter: the flow narrows; larger: it widens',
        min=0.0, max=1000.0, soft_min=0.0, soft_max=20.0, unit='LENGTH', precision=2,
        get=_path_end_get, set=_path_end_set)
    bpy.types.Scene.fl_path_speed = FloatProperty(
        name='Speed', description='Speed of the leaves along the path, in meters per '
                                  'second (this drives the particle Lifetime)',
        min=0.01, max=1000.0, soft_min=0.1, soft_max=20.0, precision=2,
        get=_path_speed_get, set=_path_speed_set)
    bpy.types.Scene.fl_path_free = FloatProperty(
        name='Free', description='Part of the leaves\' life spent free after the path '
                                 '(0 = they follow the path until the end of their life)',
        min=0.0, max=0.95, precision=2,
        get=_path_free_get, set=_path_free_set)
    bpy.types.Scene.fl_path_object = PointerProperty(
        name='Leaf Path', type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'CURVE')
    bpy.types.Scene.fl_path_target = PointerProperty(
        name='Curve', type=bpy.types.Object,
        description='Pick a curve of the scene: it becomes the leaf path and gets '
                    'the current path settings',
        poll=lambda self, obj: obj.type == 'CURVE')
    bpy.types.Scene.fl_path_hide_start = BoolProperty(
        name='Disappear at Beginning of Path',
        description='On: the leaves are born exactly on the path, so none is visible '
                    'off the curve before it has reached it. The Entry Diameter is '
                    'restored when switched off',
        get=_path_hide_start_get, set=_path_hide_start_set)
    bpy.types.Scene.fl_path_vanish = BoolProperty(
        name='Disappear at End of Path',
        description='On: the leaves vanish when they reach the end of the curve. '
                    'Off: they leave the path and keep falling',
        get=_path_vanish_get, set=_path_vanish_set)

    bpy.types.Scene.fl_ground_target = PointerProperty(
        name='Ground', type=bpy.types.Object,
        description='Ground asset (Geometry Nodes object) the wind blows on. '
                    'Empty: the active object is used',
        poll=lambda self, obj: obj.type == 'MESH')
    bpy.types.Scene.fl_gw_strength = FloatProperty(
        name='Wind Strength', description='Strength of the Wind field',
        min=0.0, soft_max=100.0, precision=1,
        get=_gw_prop('strength', 8.6), set=_gw_set('strength'))
    bpy.types.Scene.fl_gw_radius = FloatProperty(
        name='Wind Radius', description='Max distance of the Wind field (m)',
        min=0.01, soft_max=50.0, precision=2, unit='LENGTH',
        get=_gw_prop('radius', 1.0), set=_gw_set('radius'))
    bpy.types.Scene.fl_gw_mode = EnumProperty(
        name='Mode', items=[
            ('REALTIME', 'Real-time', 'Geometry Nodes simulation on every leaf, live in the viewport'),
            ('PHYSICS', 'Physics', 'Rigid bodies and force fields, tuned to look like the real-time mode')],
        default='REALTIME')
    bpy.types.Scene.fl_gw_orient = FloatProperty(
        name='Orientation', description='How much the wind tilts and flips the leaves',
        min=0.0, soft_max=3.0, precision=2,
        get=_gw_prop('orient', 1.0), set=_gw_set('orient'))
    bpy.types.Scene.fl_gw_keep = FloatProperty(
        name='Leaves Left Behind', description='Share of the leaves the gust does not move',
        min=0.0, max=1.0, precision=2,
        get=_gw_prop('keep', 0.2), set=_gw_set('keep'))
    bpy.types.Scene.fl_gw_spread = FloatProperty(
        name='Spread', description='Radial force at the centre of the gust: pushes the '
                                   'leaves apart instead of in a straight line',
        min=-1000.0, soft_min=-100.0, soft_max=200.0, precision=1,
        get=_gw_prop('spread', 43.0), set=_gw_set('spread'))
    bpy.types.Scene.fl_gw_turb = FloatProperty(
        name='Turbulence', description='Strength of the Turbulence field that makes '
                                       'the leaves tumble',
        min=0.0, soft_max=100.0, precision=1,
        get=_gw_prop('turb', 3.0), set=_gw_set('turb'))
    bpy.types.Scene.fl_gw_gravity = FloatProperty(
        name='Gravity', description='How fast the lifted leaves fall back (low values let '
                                    'them float)',
        min=0.0, max=1.0, precision=3,
        get=_gw_prop('gravity', 0.3), set=_gw_set('gravity'))
    bpy.types.Scene.fl_gw_friction = FloatProperty(
        name='Friction', description='Friction of the leaves on the ground',
        min=0.0, max=1.0, precision=2,
        get=_gw_prop('friction', 0.6), set=_gw_set('friction'))

    for cls in classes + _ONLINE_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    global _icons
    if _icons:
        bpy.utils.previews.remove(_icons)
        _icons = None

    for cls in reversed(classes + _ONLINE_CLASSES):
        bpy.utils.unregister_class(cls)

    if hasattr(bpy.types.Scene, 'fl_asset_selection'):
        del bpy.types.Scene.fl_asset_selection
    for name in ('fl_wind_strength', 'fl_wind_noise', 'fl_leaf_collection',
                 'fl_path_spin', 'fl_path_noise',
                 'fl_path_start_width', 'fl_path_end_width', 'fl_path_vanish',
                 'fl_path_speed', 'fl_path_free', 'fl_path_hide_start',
                 'fl_path_object', 'fl_path_target', 'fl_ground_target',
                 'fl_gw_strength', 'fl_gw_radius', 'fl_gw_turb', 'fl_gw_spread', 'fl_gw_mode', 'fl_gw_keep', 'fl_gw_orient', 'fl_gw_gravity',
                 'fl_gw_friction'):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
